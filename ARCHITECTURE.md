# Architecture

Deepgram Aura2 TTS is optional and shares pooled HTTP PCM framing/cancellation
with Speechify through protocol-specific request/metadata hooks. One client is
created per worker, Token-authenticated REST response audio streams into existing
mono PCM16/16kHz/60ms frames and bounded playback. Local STT and the current
Kokoro default remain intact. Benchmark provider profiles select protocols
without mutating production settings or sharing arbitrary speech caches.

Speechify Simba3.2 is optional behind trusted environment settings. A worker
shares one pooled HTTP client for streaming native PCM16/16kHz through the
existing60ms framing and bounded playback pipeline. Barge-in closes active HTTP
streams and retains bounded cleanup ownership; native models/transport/defaults
are preserved. No shared customer/generated speech cache is added.

Kitten Micro 0.8 is an optional trusted environment TTS candidate alongside
Kokoro INT8 and Piper. It shares the existing bounded segment callback,
framing and native cancellation ownership implementation with model-specific
initialization; one CPU-thread model is preloaded/shared per worker. Mono PCM16,
16kHz, 60ms frames and Evolution transport remain unchanged. Micro caching is
disabled by default; no arbitrary tenant/generated shared speech cache is added.
Kokoro remains the default pending actual VPS and human listening validation.

Kokoro INT8 is the primary CPU TTS provider, with Piper available by trusted
server configuration. LJSpeech is retired from the active deployment. A shared
preloaded model emits native callback PCM into bounded queues; the runtime
reads ahead two text chunks and buffers sixteen frames before paced playback.
Only fixed generic acknowledgements are shared-cache eligible. Native callbacks
deliver complete acoustic segments; cancellation stops forwarding immediately
while tracking non-preemptible inference. STT/TTS each default to one thread.

The CPU-first voice path is WhatsApp → Evolution Go Calls → media gateway → VAD → streaming STT → conversation state → OpenAI/Anthropic → optional generic Tool Gateway → CPU TTS → media gateway → Evolution → WhatsApp.

FastAPI hosts control APIs. PostgreSQL/pgvector owns durable tenant data. Redis holds ephemeral bounded call state. Tenant identity must originate from authenticated server-side sessions. No client can select a tenant by submitting a header or body value. Every tenant repository requires TenantContext.

n8n is only an external business-action integration. No provider/admin secrets reach browser clients. Audio is not recorded by default. Full call states are in src/vasa/contracts/models.py; transitions, per-call context, cancellation and resource cleanup now run through
the trusted voice worker and conversation runtime. Native speech is CPU-only;
models are shared per worker while utterance state remains private. Generation
guards prevent interrupted output from sending future frames. The proven
Evolution transport has no remote queue-clear acknowledgment; accepted output
cannot be claimed withdrawn. Tools and full persistence remain later waves.

Deployment preparation is authorized. Cloud development uses a dedicated compose project; deploy/compose.yaml separately defines the vasa-vps project for /opt/vasa and the existing rootless vasa-builder user. APIs bind to loopback only; database/cache are private network services. Stable credentials and PostgreSQL volumes preserve Evolution session/runtime license data. Direct VPS connection was attempted but port 22 refused it; no VPS changes have been made.

Do not implement a supposed Evolution Go wire protocol until verified. The ordinary Evolution API is not sufficient evidence of bidirectional call audio support.
