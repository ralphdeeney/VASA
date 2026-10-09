# Current state

2026-10-09 isolated TTS study: official Kokoro v1.0/v1.1, matching sherpa
v1.1 FP32 and Piper were measured with two-CPU affinity/quota, sentence and
whole-response policies, and actual paced STT contention. Official sentence
P95 under STT was 2.074–2.313s; memory exceeded the current 1 GiB worker
budget. Single-thread tuning was slower. Piper had no simulated starvation
and sentence P95 0.228s under STT. Human naturalness review and actual VPS
performance remain unverified. Production provider and transport are unchanged.
Results, hashes and WAVs: docs/tts-evaluation/streaming/. Full checks: 487 pass.

Current wave: 10 (integration and stabilization)
Current slice: Tenant knowledge, durable runtime evidence, dashboard and deployment package integrated; live OpenAI acceptance deferred by user
Completed slices: Wave 0 governance/tooling/contracts; Wave 1 tenant PostgreSQL/pgvector/Redis and isolation; Wave 2 verified pinned-source Evolution adapter, authenticated instance mapping/control and QR dashboard; Wave 3 real-call media acceptance; Wave 4 CPU VAD/STT/TTS, bounded native cancellation and streamed LLM adapters; Wave 5 conversation runtime, trusted inbound worker and native local-WebSocket integration
Active agents: none; integrated implementation is complete and locally verified
Blockers:
- OpenAI is selected primary, but no secure usable binding is injected. The credential pasted in chat must be revoked/replaced through VASA_OPENAI_API_KEY in environment settings, saved/published. Do not store or use the exposed credential. Anthropic is optional. Live LLM acceptance awaits this prerequisite; independent checks continue.
- Historical cloud SSH to vasa-builder@2.25.172.155:22 was refused before authentication; proxy CONNECT closed without SSH banner. No successful VPS connection or remote changes are claimed. This does not block independent development or negate the user's accepted real call.
Failed checks: none outstanding. Native TTS callback polarity, repeated-cancel cache cleanup, delayed state callbacks and clipped initial speech regressions fixed and verified; no tests disabled or acceptance thresholds weakened.
Next action: configure the deferred provider key when the operator is ready, then perform live dialogue, real tool, VPS and phone-capacity gates. No need to repeat the passed diagnostic media call.

2026-10-09 whole-project continuation: tenant-isolated knowledge ingestion now supports
bounded TXT/PDF/DOCX extraction, pinned CPU MiniLM embeddings and pgvector search;
the dashboard exposes agent, knowledge and call history controls; runtime tool calls,
durable transcript chunks, summaries and dynamic worker supervision are integrated.
The full verification run passed 476 checks with zero failures, errors or skips;
Ruff, formatting and strict mypy passed. A production image built successfully as
UID 1000 with a read-only root. The controlled native load report records P95 TTS
first audio 10.555s -> 1.083s and no residual tasks; this is not a phone-capacity
claim. The replacement OpenAI key remains intentionally unconfigured by user choice.

2026-10-09 continuation: prepared tenant-bound custom_webhook with approved
HTTPS actions and strict business schemas, call-bound end_call with current
registry checks/acknowledgment, and knowledge_search's tenant-tagged retriever
contract (no retrieval backend). Migration 0004 adds calls/messages/tool metadata;
every repository query is tenant-filtered, ownership is enforced by composite
FKs, concurrent messages use locked unique sequencing, and writes never commit
the caller transaction. No arguments/results/secrets or audio are stored in tool
metadata. See docs/TOOL_PREPARATION.md for configuration and integration limits.
Full verification: 384 checks pass, zero failures/errors/skips; Ruff/format and
strict mypy pass. Current JUnit inspected at reports/concrete-tools-storage.xml.
Fresh isolated DB upgrade/downgrade/re-upgrade and Alembic schema check passed.
Eight real concurrent SQL writers preserved all messages and unique sequences.
No live provider/n8n action/call, runtime transcript capture, model tool selection,
summary accuracy or concurrency capacity is claimed. No key was used.
Source c4c2c193440d37a9fe733bd15300f79a3625b1c9 is uploaded and passed both
remote Verify runs: push 37863783680, PR 37863788777. The subsequent evidence-only
documentation commit changes no implementation; its own CI is not inferred.

2026-10-09 independent slice: tenant-bound ToolGateway with server permissions,
strict input/output models, bounded JSON snapshots, fail-fast capacity,
timeouts/cancellation cleanup and sanitized per-attempt outcome logging.
24 new component checks; full verification passed 342 checks with no failures,
errors or skips. Ruff/format/strict mypy pass; current JUnit inspected at
reports/tool-gateway.xml. Restored native assets and dedicated vasa-dev DB/cache
were used. No provider key or live API was used. Tool handlers, durable audits,
provider tool streaming and voice runtime integration remain pending.

Real-call Gate 3: PASSED on the user's explicit report on 2026-10-08. Evolution
answered an actual inbound WhatsApp call; VASA received 98 live caller frames,
sent 20 diagnostic frames and the human caller heard three rising tones. This
is user-supplied real-world evidence, not a new cloud call. No dropped-frame,
latency trace, activated-license persistence or concurrency result is inferred.
The proven Evolution transport remains unchanged.

Wave 4 initial native accuracy: 6 errors / 77 reference words across three
independent pinned recordings, aggregate WER 7.79%, within the predefined 15%
threshold. Native CPU speech and scripted OpenAI/Anthropic SSE component checks
pass. Wave 5 reader, turn detection, per-call context, response chunking, pacing,
interruption generation guards and bounded cleanup are implemented. Tools fail
closed until Wave 6. Full persistence remains Wave 7; worker logs omit caller
identifiers, audio and transcripts. Live AI-call naturalness is unverified.

Earlier foundation/deployment evidence: 158 checks passed without skips; pinned
Evolution source tests/vet/build and healthy cloud startup passed. A separate
cloud deployment project passed migrations, HTTP readiness/Manager and database
identity persistence with volumes retained. Cloud-local vendor license was
inactive; this is distinct from the externally passed real call. Rootless VPS
runtime and active-license survival remain unrun. See TEST_RESULTS.md.

Final combined verification: 318 passed, zero failures/errors/skips; current JUnit inspected at reports/voice-wave-final.xml. Ruff lint/format and strict mypy pass. Actual WebRTC -> streaming Sherpa STT -> scripted LLM -> local Sherpa TTS -> unchanged Evolution WebSocket adapter passed with first-word accuracy retained. OpenAI/Anthropic loopback SSE components and two scripted dialogue evals passed. Worker preflight/ownership/admission/cleanup checks passed. Live OpenAI remains unrun.

Reusable setup was repeated twice with verified speech assets and dedicated
healthy PostgreSQL/Redis; migrations report no drift. Production voice image
built and native CPU TTS generated 29 frames as UID 1000 with read-only root.
Final image rebuilt after all fixes; packaged worker help and imports verified. Startup instructions and secure
provider requirements are saved in the environment draft; saving does not
publish or inject a key. Existing Ponytail preference and unrestricted network
are retained. Separate fresh-task restoration is not verified.

Work continues on build/vasa-foundation and draft PR #1:
https://github.com/ralphdeeney/VASA/pull/1. No browser/WhatsApp E2E framework is
built. All live-provider, real-call and component evidence remain distinct.

Remote verification note: initial PR CI for 757e1be passed; its parallel push CI
exposed a TTS completeness test coupled to stochastic supplemental STT spelling.
The corrected native regression directly measures both synthesized batches and
resampled frame completeness; no recognition acceptance threshold changed.
Final local verification passed all 318 checks; rebuilt read-only UID 1000
image verifies deterministic speech. Updated benchmarks are recorded; both remote
CI runs passed for code 61b57d9 (push 37858367544, PR 37858371785).

Final source and evidence uploaded to build/vasa-foundation. Code commit
61b57d9e3d85a70ae6d49075a87ee1fa19e17e79 passed both GitHub Verify workflows
with 318 checks. The subsequent CI-recording documentation commit changes no
implementation; do not infer its own workflow status from the source runs.
No secure provider binding is configured, no exposed key was stored or used,
and no live AI-call or ten-call capacity claim is made. Remaining graph gate:
live OpenAI behavior/real dialogue acceptance before dependent wave completion.
