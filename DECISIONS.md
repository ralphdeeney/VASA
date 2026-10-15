# Decisions

2026-10-15 VPS origin is intentionally git@github-vasa:ralphdeeney/VASA.git.
Accept that exact SSH alias/repository string in addition to the four canonical
origins; retain exact allowlist matching and the existing vasa-builder SSH
configuration. Do not rewrite the remote, request GitHub credentials, or permit
arbitrary aliases/repositories. GitHub Actions remains the only VPS SSH path.

2026-10-15 user mandates GitHub Actions as staging SSH/deployment bridge; no
further direct VPS SSH from Codex Cloud. Default manual mode is read-only check;
deploy is separately dispatched. Reuse existing rootless Compose project and
target only app/worker. Require a trusted host fingerprint rather than trusting
ssh-keyscan alone. Refuse dirty trees, schema/dependency topology changes and
missing healthy baseline. Preserve runtime secrets; rollback only known prior
app revision/image and health-check again. Register the manual workflow on main
through a separate small reviewable PR; keep implementation on requested branch.

2026-10-14 user explicitly changes the interim TTS default to Deepgram Aura2
(aura-2-thalia-en), superseding the earlier Kokoro default. Preserve all provider
options and fail-fast missing-key behavior; no silent fallback or claimed live
validation. Keep the chat-pasted exposed credential out of configuration and Git;
request a securely configured replacement DEEPGRAM_API_KEY.

2026-10-14 user confirmed Deepgram Aura TTS only and required an explicit secure
key gate before live validation. Implement optional English Aura2 REST audio
streaming, default model aura-2-thalia-en, native linear16/16000/container none.
Reuse bounded pooled PCM/cancellation machinery through narrow protocol hooks,
preserving Speechify behavior. Read DEEPGRAM_API_KEY only through trusted env
secrets; tests use mocks/local TCP, not live credentials. Reuse benchmark through
trusted provider profile; keep Kokoro/local STT/otherproviders intact. Complete
and verify all key-free work, then ask for secure configuration before live API.

2026-10-12 add optional Speechify streaming adapter and manual VPS benchmark;
keep Kokoro default/Piper/Kitten intact. Pin simba-3.2 and Speechify-Version
2026-09-30 with pcm_16000 to avoid documented legacy rate mislabeling. Use one
pooled client, actual byte/frame timing and bounded cancellation cleanup, with
no generated-speech cache. Only actual-VPS baseline records are accepted, and
different text/STT/workload conditions remain explicit. No promotion without
server measurements, listening and acceptance of external dependency. Fresh
SSH refuses connection; absent cloud key prevents live vendor measurements.

2026-10-09 add optional Kitten Micro 0.8 behind trusted environment selection;
reuse bounded native callback/framing/cancellation behavior, retaining Kokoro
default and Piper fallback. Official Micro/HF provenance and Apache model
license are verified separately from newer KittenTTS2; no inference dependency
is added. Cloud latency/CPU/RAM improve over Kokoro, but preferred first/gap
targets and actual VPS/human gates remain unmet. Do not promote from cloud or
RTF alone. Kitten caching defaults disabled. Prepare assets with
scripts/prepare_speech.py --kitten-micro. Manual VPS execution follows the
user's instruction to skip refused SSH; no remote deployment is performed.

2026-10-09 explicit user instruction supersedes the earlier LJSpeech-default
decision: Kokoro INT8 becomes primary and LJSpeech is retired from active
configuration, preparation, worker and agent voice settings. Retain Piper as
a selectable alternative and keep historical artifacts. Use actual native
callbacks through bounded queues, acknowledging complete-segment callback
granularity. Bound text/playback prefetch and cache only three static generic
phrases to avoid tenant/customer data in shared memory caches. One native
thread per STT/TTS remains the starting profile: two TTS threads improve the
cloud sentence slightly at greater CPU cost. The provider choice is the user's
explicit preference, not a claim that the <900ms unseen-speech target passes.

2026-10-09 add Kokoro INT8 as an opt-in provider only, preserving contracts,
production default and transport. Preload once, default one native thread,
retain single-worker ownership while canceled inference finishes. Barge-in
stops the consumer immediately but cannot preempt a Kokoro acoustic segment.
The user accepted skipping refused VPS SSH and will benchmark manually.
Cloud smoke misses latency/RTF goals and exhibits major starvation; keep
LJSpeech until actual VPS evidence and audible acceptance justify a switch.

- 2026-10-09: Keep production LJSpeech unchanged during the requested isolated
  Kokoro research. Study pinned official hexgrad/kokoro (the named Kokoro-TTS
  repository returns 404), compare official v1.1 Maple with the matching sherpa
  model, and distinguish official v1.0 Heart as a separate voice/model pair.
  Treat generator output as whole-segment availability; record buffering gaps,
  not merely average RTF. Do not select a production voice from CPU throughput
  alone: human listening, actual VPS budget and real-call validation remain.

- 2026-10-09 continuation: user authorized concrete tools followed by call and
  transcript storage while OpenAI stays deferred. Implement as independent
  components without enabling live worker tool output. Approved webhook actions
  require exact server destinations and strict business schemas; call ending
  captures current trusted identity; knowledge retrieval remains a contract.
  Durable histories enforce tenant ownership in PostgreSQL, sequence under row
  lock and store tool metadata without argument/result bodies. Keep acceptance
  gates pending and record uncertainty after external dispatch honestly.

- 2026-10-09: User explicitly defers configuring the replacement OpenAI key and
  requests other work. Prepare the generic tool validation gateway independently,
  without voice/runtime linking or advancing acceptance gates. Reuse the existing
  Tool protocol and Pydantic dependency; no provider credentials are required.

- 2026-10-08: Follow the user's full harness in docs/BUILD_HARNESS.md. Work in the current cloud environment, not a VPS.
- Wave 0 uses FastAPI, SQLAlchemy async/asyncpg, Redis asyncio, Alembic, pytest, Ruff, strict mypy and a committed uv lockfile.
- Shared contracts specify semantic boundaries only. Evolution wire details require upstream source verification; do not substitute ordinary messaging APIs for voice-call support.
- Development infrastructure is a dedicated compose project with loopback-bound ports and its own data volume; no Docker socket mount or unrelated service changes. Static database credentials in compose are local-only examples, never deployment credentials.
- Internal tenant context is not authentication. No public tenant CRUD APIs until trusted login/session enforcement is present.

- User-selected Calls fork: luis-kovi/evolution-go-calls; pin PR #1 head e21ce0dd7634f3047410c893b5e4d1c082034b84. Main/develop do not implement answering/streaming. No fabricated endpoints or substitution with voice messages.
- Wave 2 adds only required authenticated control/pairing screens. Passwords use bounded native scrypt off-thread; sessions are hash-keyed Redis with TTL/CSRF. Upstream instance tokens derive from a stable local master key and are never exposed/stored in mappings. Cross-service provisioning uses bounded deletion compensation; persistent compensation failure needs operator remediation, not a false success claim.
- Docker recipe builds source as non-root, retains Go verification and authoritative cloud CA trust, applies a logging-only patch to avoid credential leakage, and preserves notices/branding. Third-party license activation is retained; no bypass is attempted.
- Manual gate returns a known diagnostic three-tone recording after receiving real caller audio; no AI or caller audio recording. Frame transmission alone cannot prove audibility; caller confirmation remains required.
- Saved exact network additions are storage.googleapis.com (Go artifact ZIPs), license.evolutionfoundation.com.br (required vendor service), api.github.com (PR API). Draft persistence does not mean runtime policy changed or the environment was published.
- Reusable cloud setup uses the tested VASA script instead of the unrelated clone/placeholder script. Preserve the existing Ponytail startup preference and append concrete VASA service/readiness instructions. Publication and fresh-task restoration remain unverified.
- After user publication, official dependency verification, source tests/vet/compilation, Docker build and provider startup succeeded. The user-published unrestricted policy is preserved. Actual HTTP checks establish that vendor activation, not dependency access, now blocks pairing/calls. Attached-environment service restart is verified; separate fresh-task restoration is not.
- User now authorizes /opt/vasa deployment preparation and direct VPS connection, superseding the earlier deferral. Use only the existing rootless builder/context and dedicated vasa-vps project, preserving unrelated services. Keep all credentials in a generated private env file, reuse stable keys, reject occupied ports/foreign project ownership and preserve PostgreSQL/session/license volumes. Activate on the persistent VPS, not the temporary cloud.
- Both uppercase and lowercase NO_PROXY are required for private Docker hosts because cloud-injected lowercase variables take precedence. Retain external proxy routing and TLS verification. The read-only application uses only a dedicated diagnostics volume for the manual probe's outbound recording/report.
- Actual VPS SSH on the supplied port 22 is refused before authentication. Request correct host/port rather than guessing ports, modifying firewall/services or asking for secrets. Complete and upload independent deployment preparation while access is pending.
- The user confirmed that host/port and external SSH availability. Direct retry and a configured-proxy SSH probe still fail before handshake/authentication. Do not confuse a transport failure with a missing password/key; preserve host services and finish independent upload. No supported route has yet been demonstrated.

- User-reported real inbound call and confirmed tones satisfy Gate 3 (98 inbound/20 outbound frames). Preserve transport and enable CPU speech/runtime. Recognition threshold fixed before eval at aggregate WER <=15% over at least three independent pinned recordings. CPU native WebRTC/Zipformer/LJSpeech models, per-utterance isolation and bounded off-loop inference; models shared per worker. OpenAI is user-selected primary, Anthropic optional. Replace chat-exposed credentials securely.
- Barge-in invalidates output generations and cancels local pending work. No remote queue-clear/playback acknowledgment exists upstream; never claim already accepted frames were flushed or heard. Single selected-instance trusted worker resolves SQL ownership and logs only non-content metadata; persistence/tools remain later waves.

- Native VITS defaults randomize articulation and made appointment intermittently sound unclear to STT. Disable noise_scale/noise_scale_w for consistent business speech; repeated actual output must match. Independent recording WER acceptance remains unchanged. TTS batch completion is verified directly from native progress and resampled frame counts, including a real incorrect-polarity negative control.
