# Repository structure

```text
VASA/
├── AGENTS.md, ARCHITECTURE.md, BUILD_PLAN.md, CURRENT_STATE.md
├── DECISIONS.md, TEST_RESULTS.md, EVAL_RESULTS.md, PERFORMANCE.md
├── pyproject.toml, uv.lock, compose.yaml, alembic.ini
├── docs/                    # Full harness, contracts, transport evidence
├── docker/                  # Pinned-source build recipe and logging-only patch
├── deploy/                  # Rootless VPS Compose, private-env template and startup
├── migrations/              # Tenant foundation, ownership FK, users/instances
├── scripts/                 # Setup, verification, source preparation and status
├── src/vasa/
│   ├── app.py, config.py, logging.py, request_limits.py
│   ├── contracts/           # Shared typed transport/speech/tool boundaries
│   ├── storage/             # Async SQL, tenant repositories, expiring Redis state
│   ├── control/             # Login/session/CSRF, instance APIs, secure bootstrap
│   ├── dashboard/           # Local login/pairing HTML, CSS and JavaScript
│   ├── evolution/           # Verified HTTP/events/media adapter
│   └── media_proof.py       # Manual real inbound-call diagnostic gate
├── tests/                   # Unit, component, and real-service checks
├── evals/                   # Actual isolation cases and explicitly planned cases
└── .github/workflows/       # Foundation/control verification CI recipe
```

Ignored .local/ holds dependency source archives (not additional project checkouts),
service secrets, source fingerprints, diagnostic WAV/reports. The virtual environment,
caches and JUnit reports are ignored. No provider credentials or generated dependencies
are uploaded to GitHub. Later speech/tools/knowledge modules are not created yet.
