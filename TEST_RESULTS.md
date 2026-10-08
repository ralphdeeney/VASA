# Test results

Wave 0, 2026-10-08: `bash scripts/check.sh tests/unit -q` passed: Ruff lint/format, strict mypy (7 source files), 8 unit tests. A dependency TestClient deprecation warning is non-failing. Liveness, connection-string redaction, log secrecy and normalized audio validation were exercised. No voice transport test or AI behavioral eval has run.
