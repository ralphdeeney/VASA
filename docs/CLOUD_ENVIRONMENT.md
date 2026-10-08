# Cloud setup and restart

Use the existing `/workspace/VASA` checkout. Cloud tasks are isolated; no worktree
or VPS is required. Python 3.12, uv and Docker/Compose are prerequisites.

The reproducible base installation command is:

```bash
cd /workspace/VASA
bash scripts/setup.sh
```

This installs the frozen dependency lock, starts only the dedicated PostgreSQL
and Redis services, and runs explicit migrations. It has been repeated
successfully in the current environment. Do not remove data volumes on restart.

Run `bash scripts/check.sh` to verify the base/control/adapter development
workflow. Start the API with:

```bash
uv run --frozen uvicorn vasa.app:app --host 127.0.0.1 --port 8080
```

Use local HTTP requests to verify `/health/live`, `/health/ready` and `/login`.
Readiness must return HTTP 200 with database and Redis both healthy; it does not
prove Evolution licensing or real calling. Processes and connections must be
restarted after snapshot restoration even when files and dependencies persist.

## Remaining provider setup

`bash scripts/evolution-setup.sh` prepares and builds the pinned Calls component
automatically. After user publication, official Go downloads/verification,
call-package tests/vet, compilation, Docker build and healthy provider startup
passed. Preserve TLS and Go checksum verification.

The earlier draft proposed the three required domains. The user published an
unrestricted network policy, and Go downloads and GitHub API requests now work.
No additional domain-publication action is needed for those operations. The
agent has not changed the user-published policy. The remaining prerequisite is
vendor activation: the real running service reports inactive and rejects
instance provisioning with 503 LICENSE_REQUIRED.

The saved installation instructions replace an unrelated clone command with an
unresolved `/path/to/your/project/` placeholder. Existing Ponytail startup
instructions are retained with VASA-specific service startup guidance appended.

After the provider builds, check its process and license separately with
`uv run --frozen python scripts/evolution_status.py`. Vendor activation,
WhatsApp QR/passkey pairing and an actual inbound call remain prerequisites.
Follow [the verified transport procedure](EVOLUTION_TRANSPORT.md). Never report
the media gate passed from component tests or begin the AI voice pipeline before
the human confirms the diagnostic response was audible. UDP relay connectivity
also requires real validation. Restart and functional checks in the attached
published environment passed; restoration into a separate fresh task has not
been tested.
