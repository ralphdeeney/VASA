# VASA

VASA is a self-hosted WhatsApp AI voice-agent runtime that allows businesses to connect a WhatsApp account and have an AI agent answer inbound WhatsApp voice calls, hold natural conversations, access business knowledge, and execute approved business actions.

## Core Flow

```text
Customer
   ↕
WhatsApp
   ↕
Evolution Go Calls
   ↕
VASA Voice Gateway
   ↓
VAD
   ↓
Streaming STT
   ↓
OpenAI / Claude
   ↓
Tool Calls when required
   ↓
Local CPU TTS
   ↕
Evolution
   ↕
Customer
```

## V1 Features

- Connect client WhatsApp accounts through QR codes
- Support multiple client WhatsApp instances
- Answer inbound WhatsApp voice calls
- Bidirectional real-time audio
- Voice activity and turn detection
- Streaming speech-to-text
- OpenAI/Claude reasoning and tool calling
- Local CPU-based text-to-speech
- Caller interruption / barge-in
- Basic business knowledge base
- n8n webhook/tool integrations
- Conversation transcripts
- Call summaries and outcomes
- Tenant-isolated storage
- Minimal client dashboard

## V1 Dashboard

Clients can:

- Connect/disconnect WhatsApp
- Scan their WhatsApp QR code
- Configure agent name, greeting and instructions
- Add business information and FAQs
- Upload basic knowledge documents
- View recent calls and transcripts

## Main Stack

```text
Python 3.12+
FastAPI
asyncio
WebSockets

Evolution Go Calls
sherpa-onnx
OpenAI API
Anthropic API

PostgreSQL
pgvector
Redis
n8n

Cloudflare
Docker / Docker Compose
```

VASA is CPU-first. No GPU is required.

OpenAI or Claude provides the reasoning layer, while speech processing and infrastructure are designed to run locally using open-source components.

## Architecture Principles

- Keep the real-time audio path independent from n8n.
- Use n8n only for external business actions and integrations.
- Keep every client isolated using `tenant_id`.
- Never expose provider or Evolution admin credentials to clients.
- Build each component as a replaceable interface.
- Measure latency instead of assuming performance.
- Keep V1 focused on reliable inbound WhatsApp AI calls.

## Development Strategy

VASA is built using dependency-aware slices and verification loops:

```text
Implement
   ↓
Test
   ↓
Eval
   ↓
Measure
   ↓
Fix if needed
   ↓
Commit
   ↓
Next slice
```

Independent modules may be developed by parallel agents, while critical voice/media dependencies are built sequentially.

## V1 Success Criteria

VASA V1 is complete when a client can:

1. Log in.
2. Connect WhatsApp using a QR code.
3. Configure an AI agent.
4. Add business knowledge.
5. Receive an inbound WhatsApp call.
6. Talk naturally with the AI.
7. Interrupt the AI while it speaks.
8. Trigger an approved business tool.
9. End the call normally.
10. View the transcript, summary and outcome.

## Scope

VASA V1 focuses on one thing:

> **Reliable AI-powered inbound WhatsApp voice conversations with business tool execution.**

Advanced billing, outbound calling, regional infrastructure, enterprise analytics and other communication channels are intentionally left for later versions.


## Development status

VASA is under construction. The authoritative build instructions are in
[docs/BUILD_HARNESS.md](docs/BUILD_HARNESS.md), with progress in
[CURRENT_STATE.md](CURRENT_STATE.md) and the wave sequence in
[BUILD_PLAN.md](BUILD_PLAN.md). The AI voice pipeline must wait for a proven
bidirectional WhatsApp media transport. No real call or concurrency target has
been validated yet.

### Local development

Requirements: Python 3.12+, uv 0.12.19+, and access to a Docker/Compose runtime
permitted to manage only the dedicated `vasa-dev` project. Ports bind to loopback.
The Compose database password is a local-only example, never a deployment secret.

```bash
bash scripts/setup.sh
bash scripts/check.sh
uv run --frozen uvicorn vasa.app:app --host 127.0.0.1 --port 8080
```

`GET /health/live` checks the API process. `GET /health/ready` executes database
and Redis checks and returns 503 if either fails. Migrations run explicitly;
the application does not create or alter tables on startup.

Optional overrides can be placed in an ignored `.env` using `.env.example` as a
starting point. Never commit credentials. Tests require real local PostgreSQL and
Redis; they do not silently skip when dependencies are missing.

To stop only these development services, run `docker compose down`. Omitting
`--volumes` preserves the dedicated database data. Application processes must be
restarted after a cloud environment restore. VPS deployment is deferred.


### WhatsApp transport preparation

The Calls integration pins the reviewed PR #1 commit rather than the fork's
main branch. See [the verified contracts and blockers](docs/EVOLUTION_TRANSPORT.md).
After network settings permit the required downloads:

```bash
bash scripts/evolution-setup.sh
uv run --frozen python scripts/evolution_status.py
```

Evolution vendor license activation precedes pairing. Generated service keys live
in ignored `.local/` files with restrictive permissions; they are not printed or
committed. Once services are available, create a client login without putting its
password on the command line:

```bash
uv run --frozen python -m vasa.control.bootstrap --email owner@example.com --tenant "My business"
```

The command prompts securely. The API serves a login page and an authenticated
WhatsApp connection dashboard; provider credentials never reach the browser.

VASA uses Evolution Go Calls, an Evolution Foundation-based fork, for WhatsApp
transport. The dependency source, notices and manager branding are retained;
its license/activation conditions apply. Speech reasoning, tools and knowledge
remain future build waves, blocked by the real media acceptance gate.

### VPS deployment preparation

The isolated rootless deployment package and activation tunnel commands are in
[docs/VPS_DEPLOYMENT.md](docs/VPS_DEPLOYMENT.md). It generates private credentials,
builds the pinned source automatically and preserves project database/license
state. Evolution and VASA bind to localhost ports 18080 and 18081 by default;
occupied ports are refused. No successful VPS connection or deployment has been
performed yet.
