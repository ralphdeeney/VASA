# Decisions

- 2026-10-08: Follow the user's full harness in docs/BUILD_HARNESS.md. Work in the current cloud environment, not a VPS.
- Wave 0 uses FastAPI, SQLAlchemy async/asyncpg, Redis asyncio, Alembic, pytest, Ruff, strict mypy and a committed uv lockfile.
- Shared contracts specify semantic boundaries only. Evolution wire details require upstream source verification; do not substitute ordinary messaging APIs for voice-call support.
- Development infrastructure is a dedicated compose project with loopback-bound ports and its own data volume; no Docker socket mount or unrelated service changes. Static database credentials in compose are local-only examples, never deployment credentials.
- Internal tenant context is not authentication. No public tenant CRUD APIs until trusted login/session enforcement is present.
