# Test results

2026-10-08, Wave 0: `bash scripts/check.sh tests/unit -q` passed: Ruff lint/format, strict mypy and 8 unit tests.

Wave 1: `bash scripts/check.sh --junitxml=reports/foundation.xml -q` passed: 31 total checks (8 unit, 21 real-service integration, 2 tenant-isolation evals), zero failures/errors/skips. Ruff lint/format and strict mypy (12 source files) passed. Current-run JUnit inspected. Tests include real pgvector distance, committed migration head/schema, transaction rollback, FK ownership, cache expiry/corruption/bounds, healthy and failed dependency readiness, and a dedicated empty database proving missing migrations produce 503. Temporary test databases and exact Redis test keys are cleaned up.

`uv run --frozen alembic check`: no schema drift after migration 0002. `bash scripts/setup.sh` repeated successfully. Live Uvicorn `/health/live` and `/health/ready` returned 200 with expected bodies using real PostgreSQL/Redis.

Diagnosed initial failures: migration/model CASCADE mismatch resolved with explicit migration 0002; test initially expected 0001 and now compares committed script head. Non-failing dependency deprecation warnings remain; no checks disabled to pass.

GitHub push dry-run confirmed ability to upload branch. Remote CI has not run. No real Evolution call/WhatsApp media acceptance test has run.
