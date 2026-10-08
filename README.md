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
