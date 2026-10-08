import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from sqlalchemy import text

from vasa.config import Settings
from vasa.logging import configure_logging
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
            yield
        finally:
            try:
                if cache is not None:
                    await cache.aclose()
            finally:
                await database.aclose()

    app = FastAPI(title="VASA", version="0.1.0", lifespan=lifespan)

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
