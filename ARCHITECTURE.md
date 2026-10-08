# Architecture

The CPU-first voice path is WhatsApp → Evolution Go Calls → media gateway → VAD → streaming STT → conversation state → OpenAI/Anthropic → optional generic Tool Gateway → CPU TTS → media gateway → Evolution → WhatsApp.

FastAPI hosts control APIs. PostgreSQL/pgvector owns durable tenant data. Redis holds ephemeral bounded call state. Tenant identity must originate from authenticated server-side sessions. No client can select a tenant by submitting a header or body value. Every tenant repository requires TenantContext.

n8n is only an external business-action integration. No provider/admin secrets reach browser clients. Audio is not recorded by default. Full call states are in src/vasa/contracts/models.py; transitions, cancellation and resource cleanup are implemented in later transport/runtime waves.

Deployment is deferred. Current work uses the isolated cloud checkout as non-root agent, with a dedicated compose project binding services to loopback only. No VPS changes are authorized for this phase.

Do not implement a supposed Evolution Go wire protocol until verified. The ordinary Evolution API is not sufficient evidence of bidirectional call audio support.
