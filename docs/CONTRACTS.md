# Wave contracts

Wave 0 freezes TenantContext, AudioFrame, CallSession, CallState and semantic provider Protocols in src/vasa/contracts/. No wire-format claim is made. AudioFrame is normalized mono PCM16; wire adapters must decode/encode the upstream codec before supplying frames.

Wave 1 contract (orchestrator approval required to change):
- src/vasa/storage/models.py exports Base, Tenant(id: UUID, name: str), Agent(id: UUID, tenant_id: UUID, name: str).
- src/vasa/storage/database.py exports Database(url: str), session() -> AsyncSession, aclose().
- src/vasa/storage/repositories.py exports TenantRepository(session).create(name) -> Tenant; AgentRepository(session, context).create(name) -> Agent, get(id) -> Agent | None, list() -> list[Agent]. All agent methods filter by context.tenant_id. Repository methods flush but do not commit; callers own transactions.
- src/vasa/storage/cache.py exports CallRegistry(client: redis.asyncio.Redis, ttl_seconds: int = 3600).put(CallSession), get(context: TenantContext, call_id: UUID) -> CallSession | None, delete(context, call_id). Key includes tenant id; entries expire. Reject overwriting another tenant's logical namespace. Redis/SQL failures must propagate or become readiness failure, not synthetic success.
- src/vasa/app.py create_app(settings: Settings | None = None) initializes bounded dependency clients in lifespan, closes them on shutdown; /health/live is independent of dependencies, /health/ready returns 503 with component statuses on dependency failure and 200 only when DB/schema/pgvector and Redis operations succeed. Health output never includes URLs or exception strings.
- Tests require real project-scoped PostgreSQL and Redis for integration/evals. Apply Alembic migrations explicitly before checks; no schema creation on application startup.

Test Agent owns tests/integration/, evals/tenant_isolation/ and their fixtures; Backend Agent owns src/vasa/storage/ and src/vasa/app.py. The orchestrator owns migrations/configuration/shared contracts and tests/unit/. Agents may add no public tenant-controlled endpoint.
