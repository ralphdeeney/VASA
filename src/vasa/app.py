import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from vasa.config import Settings
from vasa.control.product import no_store
from vasa.control.product import router as product_router
from vasa.control.routes import router as control_router
from vasa.dashboard.router import router as dashboard_router
from vasa.evolution.client import EvolutionCalls
from vasa.knowledge.service import KnowledgeService
from vasa.logging import configure_logging
from vasa.request_limits import ControlBodyLimit
from vasa.saas.admin import router as admin_router
from vasa.saas.identity import router as identity_router
from vasa.saas.identity import site_router
from vasa.saas.mailer import SMTPMailer
from vasa.saas.team import router as team_router
from vasa.storage.cache import CallRegistry
from vasa.storage.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(
            configuration.database_url.get_secret_value(),
            timeout_seconds=configuration.dependency_timeout_seconds,
        )
        cache: Redis | None = None
        knowledge_service: KnowledgeService | None = None
        evolution: EvolutionCalls | None = None
        try:
            cache = Redis.from_url(
                configuration.redis_url.get_secret_value(),
                max_connections=10,
                socket_timeout=configuration.dependency_timeout_seconds,
                socket_connect_timeout=configuration.dependency_timeout_seconds,
                decode_responses=False,
                retry_on_timeout=False,
                retry=Retry(NoBackoff(), 0),
            )
            application.state.database = database
            application.state.redis = cache
            application.state.call_registry = CallRegistry(cache)
            application.state.settings = configuration
            application.state.mailer = SMTPMailer(configuration)
            knowledge_service = KnowledgeService(database)
            application.state.knowledge = knowledge_service
            keys = (
                configuration.evolution_admin_key.get_secret_value(),
                configuration.evolution_stream_key.get_secret_value(),
                configuration.evolution_instance_key.get_secret_value(),
            )
            if all(keys):
                evolution = EvolutionCalls(configuration.evolution_base_url, *keys)
            application.state.evolution = evolution
            yield
        finally:
            try:
                try:
                    if knowledge_service is not None:
                        await knowledge_service.aclose()
                finally:
                    try:
                        if evolution is not None:
                            await evolution.aclose()
                    finally:
                        if cache is not None:
                            await cache.aclose()
            finally:
                await database.aclose()

    app = FastAPI(title="VASA", version="0.1.0", lifespan=lifespan)
    app.add_middleware(ControlBodyLimit)
    app.include_router(control_router)
    app.include_router(product_router)
    app.include_router(dashboard_router)
    app.include_router(identity_router, dependencies=[Depends(no_store)])
    app.include_router(site_router, dependencies=[Depends(no_store)])
    app.include_router(team_router, dependencies=[Depends(no_store)])
    app.include_router(admin_router, dependencies=[Depends(no_store)])

    @app.get("/api/site/capabilities")
    async def site_capabilities() -> dict[str, bool]:
        delivery = bool(configuration.public_origin and SMTPMailer(configuration).configured())
        return {
            "saas_enabled": configuration.saas_enabled,
            "email_delivery_available": delivery,
            "signup_available": configuration.saas_enabled and delivery,
            "contact_available": delivery and bool(configuration.contact_recipient),
        }

    @app.exception_handler(SQLAlchemyError)
    async def database_failure(request: Request, error: SQLAlchemyError) -> JSONResponse:
        # SQLAlchemy exceptions can include parameters: no raw exception logging.
        return JSONResponse(
            status_code=503,
            content={"detail": "unavailable"},
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        # Pydantic's default errors include raw input, which can be a login password.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(item["loc"]), "type": item["type"], "msg": "Invalid request"}
                    for item in error.errors()
                ]
            },
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    async def database_ready() -> str:
        try:
            async with asyncio.timeout(configuration.dependency_timeout_seconds):
                async with app.state.database.session() as session:
                    await session.execute(text("SELECT 1"))
                    # Probe required columns without loading tenant data. Startup never migrates.
                    await session.execute(
                        text(
                            "SELECT tenants.id, tenants.name, agents.id, agents.tenant_id, "
                            "agents.name FROM public.tenants JOIN public.agents "
                            "ON agents.tenant_id = tenants.id WHERE false"
                        )
                    )
                    if configuration.saas_enabled:
                        await session.execute(
                            text(
                                "SELECT user_profiles.user_id, organization_memberships.role, "
                                "organization_profiles.status FROM user_profiles "
                                "JOIN organization_memberships ON "
                                "organization_memberships.user_id = user_profiles.user_id "
                                "JOIN organization_profiles ON "
                                "organization_profiles.tenant_id = "
                                "organization_memberships.tenant_id "
                                "WHERE false"
                            )
                        )
                    vector = await session.execute(
                        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                    )
                    if not vector.scalar_one():
                        return "unavailable"
            return "ok"
        except Exception:
            return "unavailable"

    async def redis_ready() -> str:
        try:
            async with asyncio.timeout(configuration.dependency_timeout_seconds):
                if await app.state.redis.ping():
                    return "ok"
            return "unavailable"
        except Exception:
            return "unavailable"

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        database_status, redis_status = await asyncio.gather(database_ready(), redis_ready())
        healthy = database_status == redis_status == "ok"
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ready" if healthy else "unavailable",
                "components": {"database": database_status, "redis": redis_status},
            },
        )

    return app


app = create_app()
