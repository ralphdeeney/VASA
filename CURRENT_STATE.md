# Current state

Current wave: 2
Current slice: verified Evolution Calls source and transport integration
Completed slices: Wave 0 governance/tooling/contracts; Wave 1 PostgreSQL/pgvector/Redis, explicit tenant repositories, expiring registry, real readiness, verification/evals
Active agents: orchestrator; Voice/Media source research (next: transport adapter)
Blockers: real Evolution license activation; WhatsApp pairing and real-call acceptance pending
Failed checks: none outstanding; prior Alembic FK drift was corrected with migration 0002; stale test revision expectation corrected to script head
Next action: pin PR #1 source, build Docker runtime, implement authenticated control/transport contracts and independent tests/UI

Wave 1 combined checks: 31 passed (8 unit, 21 integration, 2 tenant-isolation evals), zero skipped. Ruff and strict mypy pass. API live and ready return HTTP200 against real local services. No real WhatsApp call, voice AI or concurrency benchmark has run.
VPS remains deferred. GitHub push dry-run verified; upload after next verified slice. GitHub API is currently denied by the network proxy.
