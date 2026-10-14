# Wave contracts

## Speechify Simba 3.2 benchmark freeze — 2026-10-12

Keep TTSProvider/AudioFrame/Evolution contracts and Kokoro default unchanged.
Optional SpeechifyTTS(api_key: str, *, voice_id="geffen_32", client=None,
observer=None) owns one persistent pooled HTTP client per worker; synthesize
uses POST https://api.speechify.ai/v1/audio/stream, model simba-3.2,
output_format pcm_16000, Accept audio/pcm, Speechify-Version 2026-09-30.
Validate delivered mono16k signed little-endian PCM; emit1920-byte/60ms frames.
No full-response wait, shared speech cache or per-request client creation.
Bound admission/body/deadlines; cancellation closes the active stream; shutdown
drains cleanup. Observer receives one bounded, sanitized dict per HTTP request
with first-byte/first-frame/completion/audio duration/bytes/status/Server-Timing,
connection trace counts/read waits/framing overhead/cancellation information.
Observer is absent in production; never include key or request headers/bodies.
Provider specialist owns speechify.py and provider/component tests. Benchmark
specialist owns benchmark_speechify_vps.py and its tests/docs REPRODUCE.md;
reuse actual runtime buffering, two excluded warmups, >=20 sequential varied
responses per mode, real TCP reuse evidence and raw versus playback timing.
Root owns trusted settings/worker/deployment/export integration and final checks.
Actual VPS/API/listening remain pending when inaccessible; no fabricated WAVs or
performance, vendor latency claims, or cloud figures relabeled as server results.

## Kitten Micro candidate freeze — 2026-10-09

Add optional `KittenMicroTTS(model_dir: Path, *, num_threads=1,
max_streams=10, queue_frames=8)` with the existing synthesize/aclose contract.
Keep mono PCM16/16 kHz/60 ms framing, bounded native ownership and cancellation.
Reuse natural chunking and bounded playback; upstream acoustic segment callbacks
must not be described as incremental decoder streaming. No arbitrary speech cache.
Keep Kokoro INT8 the default until actual VPS evidence and human listening pass.
Root owns configuration, model preparation, dependencies, deployment and shared
integration. Provider specialist owns kitten.py, any explicitly agreed Kokoro
initialization hooks, and Kitten tests. Benchmark specialist owns benchmark harness
extension, benchmark tests and reproduction instructions. Research specialist owns
model/license provenance only. All three providers are compared sequentially with
identical texts, buffering, thread counts, affinity and iteration counts.

## Kokoro-first optimization freeze — 2026-10-09

User explicitly supersedes the LJSpeech default: Kokoro INT8 becomes the worker
default, Piper remains selectable. TTSProvider, AudioFrame and Evolution wire
contracts stay unchanged. Model initialization remains worker-owned and shared;
TTS/STT thread counts default to one and are independently configurable.
Kokoro provider may deliver real callback PCM through bounded 60 ms framing,
with cancellation-safe tracked native ownership. Callbacks remain limited by
upstream segment inference: no invented sub-segment streaming claim. A bounded
LRU stores only predefined server-owned reusable phrases; arbitrary generated
or customer/tenant text must not enter a shared cross-tenant cache.
Runtime adds bounded ahead-of-playback audio production and intelligent text
boundaries without losing generation guards, tool ordering, transcript limits,
or cancellation cleanup. Voice specialist owns kokoro.py/provider tests; runtime
specialist owns conversation.py/runtime tests. Root owns retirement of LJSpeech,
config/assets/deployment/migration integration and final checks.

## Kokoro INT8 candidate freeze — 2026-10-09

TTSProvider, AudioFrame and Evolution transport are unchanged. A separate
`KokoroInt8TTS(model_dir: Path, num_threads=1, max_streams=10)` exposes
`synthesize(text)` and `aclose()`, preloads one verified sherpa CPU model, and
emits mono PCM16/16000Hz/1920-byte frames. Admission, generated PCM and
playback queues remain bounded; cancellation discards old output immediately
while native cleanup retains its worker until inference stops. Defaults remain
LJSpeech. The orchestrator owns config/worker selection and the VPS harness;
the voice specialist owns only `src/vasa/speech/kokoro.py` and its provider
tests. No production switch or unrelated VPS changes are authorized.

Wave 0 freezes TenantContext, AudioFrame, CallSession, CallState and semantic provider Protocols in src/vasa/contracts/. No wire-format claim is made. AudioFrame is normalized mono PCM16; wire adapters must decode/encode the upstream codec before supplying frames.

Wave 1 contract (orchestrator approval required to change):
- src/vasa/storage/models.py exports Base, Tenant(id: UUID, name: str), Agent(id: UUID, tenant_id: UUID, name: str).
- src/vasa/storage/database.py exports Database(url: str), session() -> AsyncSession, aclose().
- src/vasa/storage/repositories.py exports TenantRepository(session).create(name) -> Tenant; AgentRepository(session, context).create(name) -> Agent, get(id) -> Agent | None, list() -> list[Agent]. All agent methods filter by context.tenant_id. Repository methods flush but do not commit; callers own transactions.
- src/vasa/storage/cache.py exports CallRegistry(client: redis.asyncio.Redis, ttl_seconds: int = 3600).put(CallSession), get(context: TenantContext, call_id: UUID) -> CallSession | None, delete(context, call_id). Key includes tenant id; entries expire. Reject overwriting another tenant's logical namespace. Redis/SQL failures must propagate or become readiness failure, not synthetic success.
- src/vasa/app.py create_app(settings: Settings | None = None) initializes bounded dependency clients in lifespan, closes them on shutdown; /health/live is independent of dependencies, /health/ready returns 503 with component statuses on dependency failure and 200 only when DB/schema/pgvector and Redis operations succeed. Health output never includes URLs or exception strings.
- Tests require real project-scoped PostgreSQL and Redis for integration/evals. Apply Alembic migrations explicitly before checks; no schema creation on application startup.

Test Agent owns tests/integration/, evals/tenant_isolation/ and their fixtures; Backend Agent owns src/vasa/storage/ and src/vasa/app.py. The orchestrator owns migrations/configuration/shared contracts and tests/unit/. Agents may add no public tenant-controlled endpoint.


## Wave 2 freeze — verified Calls transport and authenticated control

Pinned Calls source: luis-kovi/evolution-go-calls at e21ce0dd7634f3047410c893b5e4d1c082034b84 (PR #1 head), not main. Wire details are recorded in docs/EVOLUTION_TRANSPORT.md.

- Voice owns src/vasa/evolution/ and tests/unit/test_evolution.py plus tests/component/test_media.py. EvolutionCalls(base_url: str, admin_key: str, stream_key: str, instance_key: str, *, http_client: httpx.AsyncClient | None = None) owns reusable clients and aclose(); create_instance(instance_id: str, name: str), connect(instance_id), disconnect(instance_id), status(instance_id) -> ConnectionStatus(connected: bool, logged_in: bool, name: str), qr(instance_id) -> PairingQR(qrcode: str, passkey_stage: str), answer(instance_id, call_id, caller_jid), reject(...same), hangup(instance_id, call_id). token_for_instance(id) derives HMAC-SHA256(instance_key UTF8, 'vasa:instance:'+id). Never persist/expose derived tokens.
- open_media(instance_id, call_id) is an async context manager yielding MediaStream with receive() -> AudioFrame | None (None on upstream stop), send(AudioFrame), close(). Media must validate start.callId/sampleRate16000/video false, tolerate at most 4 pre-start media frames before start and require PCM16 mono 1920 bytes (960 samples/60ms). Use signed per-call HMAC query with 60s expiry, bounded WS/network resources; no hypothetical clear/flush event.
- events(instance_id) -> AsyncIterator[IncomingCall(instance_id: str, call_id: str, caller_jid: str)] uses authenticated server-side /ws, validates payload instanceId/token binding and CallOffer schema. Tokens never become browser content or logs. No outbound dial/video integration.
- Backend owns src/vasa/control/ ONLY (models/auth/routes/bootstrap). Use existing Base from storage.models. User(idUUID,tenant_idFK,email unique lowercase, password_hashText), WhatsAppInstance(idUUID,tenant_idFK,external_id unique str,name str). Tenant ids originate only from authenticated Redis session context. Models/queries filter instance ownership explicitly; no token column.
- router in vasa.control.routes exposes POST /api/auth/login JSON{email,password} -> {csrf_token}; POST /api/auth/logout, GET /api/auth/me -> {email,csrf_token}; GET/POST /api/whatsapp/instances -> list/create safe fields{id,name}; GET /api/whatsapp/instances/{id}/status -> {connected,logged_in,name}; GET .../{id}/qr -> {qrcode,passkey_stage}; POST .../{id}/connect and /disconnect -> {status}. Browser input never includes tenant_id/admin/provider token. A foreign/unknown instance id returns 404 with no upstream call.
- Login uses scrypt with random salt, constant-time compare and same-cost missing-user control; passwords bounded. HttpOnly SameSite strict session cookie, Secure in production. Session secrets hash-namespaced in Redis with 8h TTL; store user/tenant/CSRF server-side. All authenticated mutation routes require x-csrf-token matching session, and login rejects cross-origin Origin headers. Rate-limit login by client address in Redis with finite TTL. Return sanitized upstream 503 (license_required or unavailable). No public signup; bootstrap via python -m vasa.control.bootstrap --email EMAIL --tenant NAME obtains password with getpass or VASA_BOOTSTRAP_PASSWORD; never puts password on command line/output. Auth API requires schema0003 and is optional to base health.
- Root integrates app lifespan/router; app.state.settings, database, redis, evolution (None if keys not configured). Root owns migrations/config/deps/compose/scripts/docs and src/vasa/app.py during Wave 2.
- Dashboard Agent owns src/vasa/dashboard/ only; exports router serving /login and authenticated /dashboard (dependency vasa.control.auth.require_context). Use no external CDN/dependencies, no browser secret values, textContent for untrusted fields, no raw HTML injection. Login form, logout, instance list/create/connect/disconnect, QR/status polling with CSRF. Model-provider/knowledge/calls screens wait for future waves.
- Test/Eval owns tests/control/ and evals/tenant_isolation/test_control_access.py; test real auth/CSRF/rate limits/tenant mapping using app.state.evolution stub with positive upstream call controls; mocks are component evidence, never real-call acceptance.

Shared files and contracts change only through the orchestrator. Evolution license activation and WhatsApp/network human prerequisites do not count as passed from mocks. Gate 3 was subsequently satisfied by user-confirmed real-call evidence below.

## Wave 4/5 freeze — CPU speech and conversation

Gate 3 PASSED on the user's actual-call report: 98 live inbound frames, 20
diagnostic outbound frames, caller confirmed tones audible. Keep all verified
Evolution routes/media/authentication unchanged.

- Existing STTProvider and TTSProvider protocols remain unchanged. SherpaSTT
  receives an asynchronous PCM frame stream and yields cumulative partial text;
  the final nonempty update after finite input is the completed utterance.
  Each call owns its native recognizer stream; models are shared with bounded
  offload and cancellation-safe worker capacity.
- SherpaSTT(model_dir: Path, num_threads=2, max_streams=10) and
  SherpaTTS(model_dir: Path, num_threads=2, max_concurrency=2) expose aclose().
  TTS is local ONNX CPU inference and returns PCM16 mono/16000Hz/1920-byte
  frames. Caller audio is not recorded. Models and source licenses/checksums
  are managed by scripts/prepare_speech.py outside Git.
- StreamingVAD.process(AudioFrame) -> VadResult(started, ended, speech,
  segment), finish() -> segment or None. VadConfig: native WebRTC
  aggressiveness 2, 60ms minimum onset, 300ms silence endpoint, 120ms preroll,
  20-second maximum utterance. VAD state is private to a call.
- LLMProvider yields {type: text, text: delta}. Unexpected tool output is
  rejected until Wave 6. OpenAIProvider/AnthropicProvider use reusable bounded
  streaming HTTP clients and aclose(); FallbackProvider changes provider only
  before any visible output. No partial response mixing or unbounded retries.
- ConversationRuntime.run(context, media, on_state=None) receives continuously
  while speech recognition, reasoning or playback runs. STT begins during
  speech, not after endpoint. A bounded 480 ms runtime capture pre-roll preserves
  quiet initial words before native onset (VAD segment pre-roll remains 120 ms).
  Generation checks cancel old greeting/LLM/TTS and
  future output on voiced onset; playback is paced one frame per 60ms. The
  transport has no remote queue-clear primitive and none is invented.
- RuntimeConfig holds trusted server instructions/greeting and finite call,
  turn, history, response, queue and provider limits. Histories and native
  streams never cross tenant/call boundaries. Diagnostic metrics carry counts
  and local times, not caller transcript/audio or secrets.
- The outer voice worker resolves user/tenant/instance ownership from SQL,
  preflights models/provider configuration, answers and opens media using the
  existing EvolutionClient, updates expiring call state and always cleans up.
  No incoming event can choose its own tenant.

Speech accuracy acceptance is an aggregate word error rate <=0.15 over at least
three independent pinned English fixtures; native TTS must produce bounded
nonempty valid speech frames. Native measurements and scripted model component
evals are distinct from live LLM behavior and real-phone dialogue acceptance.

## Independent tool gateway preparation — 2026-10-09

The user deferred provider setup and authorized other development. This freezes
an independent component only; Gate 5 remains unpassed and the voice runtime
continues rejecting tool output. No Wave 6 integration or completion is implied.

- `ToolGateway.register(ToolBinding)` is server-only configuration. Bindings
  contain a trusted tenant UUID, existing `Tool` implementation, strict Pydantic
  `ToolPayload` input/output models and a finite 0–30 second deadline (exclusive
  of zero). Duplicate names per tenant and more than 1024 bindings are rejected.
- `execute(context, name, arguments, allowed_tools=frozenset(...))` requires
  authenticated server-derived TenantContext and server-loaded permission names.
  Never accept registry entries or permission grants from the model or browser.
  Unknown/foreign tools and missing grants share `denied`, before handler work.
- Payloads are JSON snapshots bounded to 32 KiB, 2048 nodes and depth 16;
  nonfinite numbers, coercion and unknown schema fields are rejected. Validate
  both arguments and results. Schema field-specific bounds remain required.
- Global active execution is bounded (default four); saturation fails `busy`
  without a waiting queue. No automatic action retries. Async handlers must
  honor cancellation, bound their own external I/O and avoid blocking work.
  Timeouts/cancellation release capacity after handler cleanup; cancellation
  cannot undo a business action already accepted by an external service.
- Error messages contain fixed codes only. Each attempt logs one controlled
  outcome event without arguments/results/exception messages. Durable tool
  records and execution IDs remain Wave 7, not supplied by these logs.
- `knowledge_search`, `custom_webhook`, `end_call`, provider tool streaming and
  runtime continuation are not implemented by this gateway component. Webhook
  destinations/credentials must come from trusted tenant configuration, with
  explicit destination policy before enabling business actions.

## Concrete tool preparation freeze — 2026-10-09

- `CustomWebhook` is bound to one trusted tenant and a bounded server-owned map
  of action names to exact HTTPS URLs. The model supplies only action and JSON
  payload. Each destination origin must be explicitly approved by server policy;
  URL credentials/query/fragments, IP literals, local/reserved hostnames and
  redirects are rejected. Credentials are server-only bearer tokens. Deployment
  egress must constrain approved DNS hosts and destinations; this component does
  not replace DNS/proxy enforcement or promise DNS rebinding protection.
- A webhook sends one POST without retries, streams at most 32 KiB of JSON and
  rejects error statuses, compression and non-object/malformed output. Cancellation
  releases response/client resources but cannot undo a submitted external action.
  Every approved action also supplies strict input/output ToolPayload models;
  business fields are validated before sending and before returning results.
  Requests wrap validated fields as payload and supply a trusted tenant_id.
  Workflow-specific permissions remain server configuration, not model decisions.
- `EndCall` captures authenticated context, current CallSession, registry and
  Evolution client on the server. It accepts no call/tenant/instance identifier.
  Check current registry identity/state before the existing verified hangup;
  successful acknowledgment sets a local end-request event for future integration.
  One object per call, one successful request, no automatic retries after timeout.
- `KnowledgeSearch` defines query/top_k and bounded tenant-tagged match contracts
  against an injected KnowledgeRetriever. It has no built-in retrieval backend.
  Missing backend fails unavailable; cross-tenant results fail before returning.
  Real embeddings/vector retrieval and knowledge acceptance remain Wave 8.
- All three implement the existing Tool protocol and validate even if called
  directly. Gateway permissions remain mandatory at the integration boundary.
  No tool is enabled in the voice worker by this preparation.

## Call persistence preparation freeze — 2026-10-09

- New `calls`, `call_messages`, `tool_calls` tables store every tenant-owned row
  with tenant_id. Composite ownership FKs prevent attaching messages/tool records
  to foreign calls or calls to foreign WhatsApp instances. No audio blobs.
- `CallRepository(session, trusted_context)` owns tenant-filtered create/get/list,
  append_message/messages, finalize and start_tool/finish_tool/tool_calls. Methods
  flush but never commit. Foreign/unknown parents return None before writes.
- Message sequence is allocated under the call row lock, unique per call and
  bounded to 1000 messages; content <=16384 characters. Roles are customer, agent,
  tool, system. Ended/error calls refuse additional messages/tools. Lists are
  bounded/paginated; every query includes trusted tenant context.
- Calls capture start/end, optional caller identifier, summary/outcome; finalization
  validates time ordering and is immutable/idempotent on matching repeated input.
  Tool rows record an execution UUID, controlled tool name, status/code and times;
  arguments/results/credentials are not persisted by default. Missing response after
  external dispatch must not be represented as confirmed failure of the action.
- Migration and repositories are independent preparation; the live worker does
  not write transcripts until runtime acceptance/integration is completed. No
  knowledge tables, generated summaries or dashboard calls screen are claimed.

## Final implementation freeze — 2026-10-09

The user now authorizes finishing all remaining implementation tasks while the
live provider credential stays deferred. Gates are acceptance records, not a
reason to leave independent implementation unfinished. No scripted result counts
as live acceptance. Parallel ownership follows the harness.

- Root owns dependencies, migrations, storage models/repositories, configuration,
  app router integration and product APIs. Dashboard owns dashboard/ only.
  Knowledge specialist owns knowledge processing/embedding modules and its tests;
  runtime specialist owns llm/, runtime/ and corresponding tests. Worker specialist
  owns voice_worker.py, finalization module and its tests.
- Product APIs: GET/PUT /api/agent fields name,business_name,greeting,
  business_description,instructions,language,voice; GET/POST /api/knowledge
  (POST JSON {name,text}); POST /api/knowledge/upload raw bytes with x-file-name;
  DELETE /api/knowledge/{UUID}; GET /api/calls?limit=50&offset=0 and
  GET /api/calls/{UUID} with messages/tool_calls. All mutations require CSRF;
  all reads require authenticated trusted tenant context. No provider secrets.
- Root supplies KnowledgeService(database) add_text(context,name,text),
  add_document(context,name,bytes), list_sources(context), delete_source(context,id),
  search(context,query,top_k)->list[KnowledgeMatch]. Root owns source/chunk schema.
  Knowledge processor exports process_text(text)->list[str],
  extract_document(name,bytes)->str, CPUEmbedder.embed(list[str])->list[list[float]],
  dimension=384 and a versioned embedding identity. Bounded off-loop use required.
- Agent defaults: English CPU voice ljspeech_en; trusted persisted instructions
  and greeting load per tenant (first configured agent). No unsupported language
  or customer-selectable model/provider controls.
- Runtime adds optional on_message async callback for individual completed
  user/assistant/tool events, separate from bounded model context. Optional
  ToolExecutor.execute(context,name,arguments)->dict and finite max-tool rounds.
  Text-only calls retain current behavior. Provider tool events have type tool_call,
  id/name/arguments; advertise strict server-approved specs. Tool continuation must
  preserve protocol validity and cancellation/tenant isolation. No tools by default.
- Worker persists each transcript message via separate short DB transactions,
  creates/finalizes durable calls and tool audit IDs, supplies KnowledgeService and
  per-call EndCall. Existing answer/media transport remains unchanged. Summary
  processing is bounded and separate from live audio; failure cannot strand calls.
