# Test results

2026-10-08 final combined command: `bash scripts/check.sh --junitxml=reports/current.xml -q`.

110 passed; zero failures, errors or skips. Current-run JUnit inspected. Ruff lint/format and strict mypy across 27 source files passed. The suite includes 8 foundation unit checks, 21 real-service integration checks, 2 foundation isolation evals, 50 adapter HTTP/local WebSocket checks, 22 authenticated control checks, 1 control isolation eval and 6 manual-probe component checks. One non-failing upstream TestClient deprecation warning remains.

Exercised: real PostgreSQL migrations/schema/pgvector distance, FK ownership, uncommitted writes/rollback, cache expiry/corruption/size/namespace boundaries; dependency/schema readiness failures without leakage; scrypt/session/CSRF/origin/rate limits and session revocation; real tenant-filtered control APIs with upstream stubs and failure compensation; dashboard auth/CSP/local asset responses; cumulative ASGI body limits; adapter local WebSocket signed handshake, bidirectional PCM, bounds and idle cancellation; probe cancellation/failure cleanup and pending human audibility confirmation.

`bash scripts/setup.sh` repeated successfully; `uv run --frozen alembic check` reports no drift. Controlled Uvicorn stop/restart succeeded. HTTP /health/live, /health/ready, /login and login asset returned 200; /dashboard without authentication returned 401. Source preparation repeated with unchanged validated manifest and preserved secrets. Compose config validates.

Evolution Docker build: FAILED initially on absent proxy CA trust; corrected with authoritative host CA bundle without disabling verification. The next build failed with HTTP 403 on an official Go artifact redirect to storage.googleapis.com. No go.mod/go.sum changes, checksum overrides or TLS bypasses. Go package tests/vet, server compilation, provider startup and live license/call requests are therefore UNRUN. No real WhatsApp acceptance is claimed from local mocks.

Remote GitHub CI and fresh-cloud restoration are UNRUN. The initial migration/model CASCADE mismatch was fixed with migration 0002; tests compare the actual DB revision to committed head. No assertions or suites were disabled to pass.
