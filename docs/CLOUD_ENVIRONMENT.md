# Cloud setup and restart

Use the existing `/workspace/VASA` checkout. Cloud tasks are isolated; no worktree
or VPS is required for development. Python 3.12, uv 0.12.19 and Docker/Compose are
prerequisites.

```bash
cd /workspace/VASA
bash scripts/setup.sh
bash scripts/check.sh
uv run --frozen alembic check
```

Setup installs the frozen lock, downloads/verifies pinned CPU speech assets into
ignored `.local/speech`, starts only dedicated PostgreSQL/Redis and applies
migrations. It was repeated successfully; cached artifacts are verified and
reused. Native speech tests execute in CI, with actionable missing-model failures.
Preserve database volumes and private `.local/` service keys; never dump secrets.

Start the API in a managed foreground process:

```bash
uv run --frozen uvicorn vasa.app:app --host 127.0.0.1 --port 8080
```

Internal requests to `/health/live`, `/health/ready` and `/login` returned 200;
readiness reported healthy database/Redis. API readiness does not prove calling
or provider activation. Processes, services and connections must restart after
restoration even when files/dependencies persist. Stop only processes started
for this task. Separate fresh-task restoration remains unverified.

## Proven transport and voice worker

`bash scripts/evolution-setup.sh` builds the pinned Calls PR1 commit automatically
with source package tests/vet/compilation, TLS and checksum verification, and
retained upstream notices. `uv run --frozen python scripts/evolution_status.py`
checks actual local provider process/license separately. After user publication,
official Go downloads, image startup and expected vendor licensing enforcement
were verified. The published unrestricted network policy is retained.

The user subsequently confirmed a successful real inbound WhatsApp call with
98 incoming frames, 20 diagnostic frames and three tones heard. Gate 3 PASSED.
Do not repeat the diagnostic gate or infer live AI acceptance from it. The
historical inactive cloud-local license is distinct from that accepted external
deployment. Follow EVOLUTION_TRANSPORT.md for verified interfaces; do not invent
or redesign transport endpoints.

CPU VAD, streaming STT and local CPU TTS now feed the conversation worker over
that unchanged adapter. See VOICE_RUNTIME.md for commands and measured limits.
OpenAI is the selected primary. Enter a replacement `VASA_OPENAI_API_KEY` securely
in environment settings and save/publish; never reuse or store a chat-exposed
key. Anthropic remains optional. Proxy-bound cloud credentials must use their
supported HTTPS route and must not be copied into VPS files.

Provider requirements and revised startup instructions are saved in the draft.
Saving persists instructions; it does not publish or inject credentials. The
existing Ponytail preference is preserved. No key binding was injected at final
local verification, so live reasoning is still unrun.

## Deployment scope

The rootless package in VPS_DEPLOYMENT.md uses only `/opt/vasa`, existing
`vasa-builder`, project `vasa-vps`, stable private service credentials and
persistent database/license/speech volumes. Historical SSH from cloud failed
before authentication; no successful remote deployment or host changes are
claimed. Independent development and the accepted transport gate remain valid.
