# Current state

2026-10-15 automatic staging phase: merged remote 79b5457 (push trigger was
already added, but its first run failed with empty dispatch-only mode). Fixed
push resolution to deploy/smoke=false and added allowlisted five-field summary.
Added read-only host/container web, Evolution license/instance and sanitizer
validation with unchanged dependency/restart checks. Push uses the same safe
update-only controller; public ingress remains externally blocked/unverified.
The implementation push is authorized to deploy this branch including e5431b4;
its live receipt is recorded in the Actions run and ignored VPS deployment journal.
No direct Codex SSH, bootstrap, migrations or account changes are authorized.

2026-10-15 live WhatsApp partial integration VERIFIED by operator: inbound
answer, caller frames and audible opening greeting; calls then reconnect/end
after roughly 10–30 seconds, with no container restart and no completed turn.
Disconnection root cause remains unconfirmed. docs/CALL_TRANSPORT_ANALYSIS.md
traces the pinned sources: CallTransport is handled independently by meowcaller;
Evolution's separate warning does not prove an ignored reconnect. Subtype 3 has
no documented reconnect semantics in the pin. No speculative relay change made.
Confirmed redundant hangup cleanup corrected: authenticated remote terminate or
upstream stop prevents duplicate REST hangup and misleading hangup_failed.
Socket shutdown after verified termination is normal; other read failures and
genuine local hangup failures remain errors. Added bounded safe log filter and
fixed media continuity/lifecycle markers. Providers/schema/topology/security
configuration unchanged. No deployment or live call performed by Codex.

2026-10-15 exact 9Router mismatch confirmed by operator: valid terminal stop
choice then clean EOF, no DONE sentinel. OpenAIProvider now shares terminal
finalization between DONE and clean SSE exhaustion; EOF requires prior valid
stop/tool_calls finish and all accumulated tool calls validate before emission.
Strict SSE framing, indices, limits and post-finish content checks remain intact.
Regression fixture uses synthetic text matching observed content/content/stop+
usage shape. No direct VPS SSH, API request or deployment dispatched here.

2026-10-15 operator confirms gateway auth/model/chat/streaming HTTP 200 and SSE,
but VASA LLM smoke still reports provider_error. Added one-request structural
SSE diagnostic, packaged in the app image; see docs/LLM_SSE_DIAGNOSTICS.md.
Exact mismatch remains pending operator structural output. No captured 9Router
fixture exists yet and no production parser compatibility change was guessed.
Existing strict text/tool parsing is preserved. Deploy tooling with smoke off,
then run the explicit diagnostic on the VPS. No direct SSH or live request here.

2026-10-15 operator reports normal deploy reached healthy API/voice and failed
only at optional provider_smoke. Fix diagnostic capture: a nonzero smoke exit now
preserves stdout/stderr in memory, prints only exact approved provider status/error
markers and numeric timings, then still fails deployment and invokes rollback.
Stderr and arbitrary stdout remain withheld. Default deploy remains unchanged;
no workflow dispatch, direct VPS SSH or live provider call made for this fix.

2026-10-15 normal development phase:

- GitHub Actions → VPS deployment bridge: VERIFIED (operator-confirmed).
- Voice bootstrap: VERIFIED (operator-confirmed `VASA_BOOTSTRAP_OK`, readiness OK).
- Normal deploy: pending live verification; five-service update path covered locally.
- Live 9Router provider test: pending.
- Live Deepgram provider test: pending.
- Full AI WhatsApp call: pending.

Normal updates use manual Actions `mode=deploy`, never bootstrap. Bootstrap remains
a special one-time/recovery operation. Optional `provider_smoke=true` enables two
bounded sequential paid requests after API/voice health passes; default false.
The standalone container command is `python scripts/live_provider_smoke.py`.
It uses trusted runtime configuration, prints fixed status/numeric timing markers,
and never participates in the WhatsApp path. No live API calls or deployment
dispatch were performed for this change. See docs/DEPLOYMENT_ACTIONS.md.

Earlier bootstrap instructions below are historical; use normal deploy now.

2026-10-15 target voice startup diagnostics are complete and verified. Each
worker run emits fixed startup stages; exceptions emit only allowlisted failed
stage/error codes, never exception strings, provider bodies or environment.
CLI also sanitizes unexpected exceptions. Readiness is sticky: later failures
use VOICE_RUNTIME_FAILED/ERROR even during reconciliation. Actions capture a
bounded target voice log tail across restarts before rollback/removal, print
only exact allowlisted markers, and suppress restored-image lifecycle markers
after rollback. Health rejects lifecycle failure codes despite an earlier ready
marker. All791 checks pass, including120 focused deployment/diagnostic checks;
static/type, Actionlint and shell validation pass. b1cac8 provider-aware asset
checks and provider settings/topology remain unchanged. No direct VPS SSH,
deployment dispatch or live diagnosis was attempted. Next operator bootstrap
can now report the target worker's sanitized failing stage before rollback.

2026-10-15 provider-aware speech startup fix is complete and verified. Worker
calls SpeechModels.verify_runtime, always checking ASR and only the configured
local TTS provider's assets; Deepgram/Speechify need no local TTS or fixtures.
Full verify()/provisioning still checks ASR/Piper/Kokoro/fixtures, with Kitten
optional as before. Read-only CLI: scripts/prepare_speech.py --verify-runtime
--tts-provider deepgram (supports trusted local-model directory overrides).
Cloud persisted voice strings are ignored and cannot select provider/model;
English and the existing fixed local voice allowlist remain enforced. All754
full checks pass, including87 focused asset/worker/persistence checks; static,
type, Actionlint and shell checks pass. No downloads at worker startup, no real
key/configuration edits, no direct VPS SSH and no deployment. Operator next:
VASA staging VPS, branch build/vasa-foundation, mode=bootstrap.

2026-10-15 custom OpenAI-compatible gateway support is wired end to end:
Settings.openai_base_url reads VASA_OPENAI_BASE_URL with official default
https://api.openai.com/v1; voice_worker passes it to the existing provider.
Provider URL construction remains base.rstrip('/') + '/chat/completions',
retaining model names, bearer auth, SSE and tools. The example uses only a
commented gateway placeholder. Real gateway keys/runtime files, Deepgram and
deployment configuration are untouched. All692 checks pass, plus static/type,
Actionlint and shell checks. JUnit: reports/openai-base-url.xml. No live gateway
call, direct VPS SSH or deployment. Operator next: VASA staging VPS, branch
build/vasa-foundation, mode=bootstrap.

2026-10-15 rollback-image recovery fix: user reports the healthy VPS API image
ID is unavailable in the local rootless Docker image store, causing bootstrap
backup tagging to fail. Shared bootstrap/deploy helper now inspects/tags when
possible, otherwise builds clean PREVIOUS_SHA source directly to the rollback
tag through the existing Compose build with an image-only stdin override. It
verifies the result/source/private hashes before checkout or container updates.
Failed acquisition leaves Git checkout/running containers unchanged. Recovery
uses the verified image ID (not the unavailable original); apps whose update
never started are not recreated. Fixed stage identifiers replace opaque command
errors without raw logs/secrets. No docker commit or container-env inspection.
All682 checks pass, including83 deployment-focused checks; static/type,
Actionlint and shell validation pass. No direct VPS SSH or live bootstrap ran.
Next operator action: rerun VASA staging VPS on build/vasa-foundation with
mode=bootstrap; expected success marker VASA_BOOTSTRAP_OK.

2026-10-15 explicit missing-worker bootstrap is implemented and verified locally.
User confirms the Actions bridge works and VPS postgres/redis/evolution/API are
healthy, with no voice container. Workflow modes are check/bootstrap/deploy,
default check. Bootstrap requires precisely that owned healthy topology, clean
Git, untracked private env files and nonempty resolved DEEPGRAM_API_KEY; missing
key emits DEEPGRAM_VPS_KEY_REQUIRED before fetch. It builds the existing shared
app image, updates API only if necessary, and creates only the missing worker.
Health checks, dependency snapshots and environment hashes gate success. Failure
removes only the new owned worker and restores Git/API image; health-checked
rollback stays nonzero. Normal deploy still requires its existing worker.
All666 full checks pass, including67 deployment-focused checks; static/type,
Actionlint and shell validation pass. No live bootstrap or direct VPS SSH ran.
Next operator action: VASA staging VPS, branch build/vasa-foundation,
mode=bootstrap. Expected success: VASA_BOOTSTRAP_OK. Runbook:
docs/DEPLOYMENT_ACTIONS.md; JUnit: reports/actions-bootstrap.xml.

2026-10-15 origin compatibility fix: exact git@github-vasa:ralphdeeney/VASA.git
is accepted alongside the four canonical origins. No wildcard matching, remote
rewrite, credential change or direct VPS SSH. All630 checks pass, including31
deployment checks exercising canonical/alias acceptance and malicious remote
rejection. Next operator action: VASA staging VPS -> mode=check.

2026-10-15 staging deployment bridge: manual Actions workflow supports default
read-only check and explicit deploy. Codex Cloud must never SSH to the VPS;
this supersedes earlier direct-SSH authorization. Existing rootless Compose
project vasa-vps/app services vasa+voice are reused with targeted updates,
secret preservation, health checks and controlled app-only rollback. Full615
checks pass; workflow Actionlint1.7.7 and shell syntax pass. No VPS deployment
or connectivity success is claimed. Registration on default branch main and
trusted repository variable VASA_VPS_HOST_KEY_SHA256 are prerequisites.
API access to repository Actions variables is denied to the connected GitHub
integration (403); no secret values were requested or exposed. Manual runbook:
docs/DEPLOYMENT_ACTIONS.md. Deepgram test configuration remains local/ignored;
the workflow does not transfer provider credentials to the VPS.
Registration PR: https://github.com/ralphdeeney/VASA/pull/2 (workflow only).
Initial mode=check dispatch returned HTTP404 because registration is pending;
no Actions SSH or deploy ran. Implementation is committed as ab64274.

2026-10-14 user explicitly selected Deepgram Aura as the interim default.
Settings, deployment Compose fallback and example environment now select deepgram
with aura-2-thalia-en. Kokoro INT8, Piper, Kitten and Speechify remain selectable.
This is a user preference, not a measured production-readiness recommendation.
The chat-pasted credential is exposed and is not stored or used. Configure a
replacement DEEPGRAM_API_KEY securely before live validation or worker startup.
Existing explicit VASA_TTS_PROVIDER overrides must be changed by the operator.
No live deployment or vendor benchmark has been performed for this change.

2026-10-14 current wave: stabilization / optional Deepgram Aura TTS.
Current slice: code/config/tests/benchmark complete; stopped at live-key gate.
User confirmed Aura TTS only. Deepgram is optional, uses one shared pooled
HTTP PCM streamer with Token auth/linear16/16kHz/no container, defaults to
aura-2-thalia-en and preserves Kokoro default/local STT/other providers/media.
DEEPGRAM_API_KEY is read through an exact secret environment alias, never
hardcoded/logged. Benchmark shares verified sequential direct/runtime buffering,
two excluded warmups, >=20 varied responses per mode, optional real STT and
safe partial failures/metadata. Full599 checks passed,0 failures/errors/skips;
Ruff/format/mypy57 sources pass; Compose configuration validates.
Active specialists:none. Automated failures:none outstanding. Blockers:real
Deepgram key is not configured; actual VPS access previously refused. Next
action:ask user to set DEEPGRAM_API_KEY securely, then validate live API/PCM and
run separate correctly labeled cloud/VPS evidence. No live Deepgram request,
vendor latency or listening WAV is claimed. Evidence and manual commands:
docs/tts-evaluation/deepgram-aura-2-vps/.

2026-10-12 current wave: stabilization / optional Speechify streaming benchmark.
Current slice: integration complete; actual VPS/API/listening pending.
Speechify Simba3.2 is selectable by trusted environment configuration; Kokoro
remains default and all existing providers/transport are preserved. One pooled
client, pinned API version2026-09-30, native PCM16/16kHz/60ms frames and bounded
cancellation cleanup are verified locally. Benchmark supports two excluded
warmups, >=20 sequential varied responses per direct/runtime-buffered mode,
first-byte/frame/percentiles/RTF/CPU/RSS/stalls/Server-Timing/connection evidence
and optional real one-thread STT contention with standalone fixture baseline.
Full checks:571 pass,zero failures/errors/skips; Ruff/format/mypy56 sources pass.
Real loopback TCP proves completed-request reuse and interrupted-stream closure.
Active specialists:none. Automated failures:none outstanding. Blockers:fresh
SSH to confirmed VPS returns Connection refused; cloud Speechify key absent.
No live vendor metrics or listening WAVs are claimed. Next action:run manual
VPS commands and listen before any production selection. Evidence/commands:
docs/tts-evaluation/speechify-simba-3.2-vps/.

2026-10-09 current wave: stabilization / optional Kitten Micro evaluation.
Current slice: complete locally; actual VPS A/B/C and human listening pending.
Kitten Micro 0.8 is selectable alongside Kokoro INT8/Piper, with one shared
preloaded model, one native thread, bounded PCM16/16kHz/60ms delivery and
existing cancellation. Kokoro remains the default. Exact model/dependency/
license pins and optional asset preparation are integrated. Six sequential
uncached A/B cloud cohorts measured 54 responses and 108 WAVs. STT1 sentence
P50: Kitten 2.136s / Kokoro 4.132s / Piper 0.219s; RTF maxima 0.313/1.282/0.093;
long gaps 1.764/4.099/0.001s. Kitten misses preferred 1s first/300ms gap targets.
Full checks: 539 pass, zero failures/errors/skips; Ruff/format/strict mypy pass
(55 sources). Native Micro reuse/framing and three-provider worker sharing are
covered. Compose configuration and deployment script syntax pass.
Active specialists: none. Failed checks: none outstanding. Blockers: manual
VPS workload validation and human listening. Prior refused SSH is skipped per
user instruction. Next action: run server commands and review matched WAVs
before promotion. Evidence: docs/tts-evaluation/kitten-micro/.
Earlier entries below are historical.

2026-10-09 user explicitly selected Kokoro and retired LJSpeech. Kokoro INT8
is now the code/Compose default; Piper remains selectable. Active source/API/
dashboard/model preparation no longer select or download LJSpeech. Migration
0006 moves legacy default voices to Maple while preserving tenant identities.
Worker preloads once and warms three generic-only cache phrases; STT/TTS
default to one thread. Callback queue8, playback queue16, pending text2,
120-character meaningful chunks and a bounded generic-only cache are integrated.
Full checks: 521 pass, static/type checks pass; native Kokoro local-WebSocket
pipeline passed. Cloud buffered STT1: cached ack0.6ms, uncached sentence4.071s,
long gap4.127s. TTS2 sentence3.800s costs ~57% more combined CPU seconds.
Actual VPS activation/benchmark and audible quality review remain pending;
user requested manual server execution after SSH refusal. New evidence:
docs/tts-evaluation/kokoro-int8-vps/optimized/. Earlier records below are historical.

2026-10-09 Kokoro INT8 candidate: optional environment selection is integrated,
default LJSpeech and WhatsApp transport unchanged. One verified model is shared
at worker setup, num_threads=1, bounded native admission/PCM and immediate
consumer cancellation with separately tracked non-preemptible native cleanup.
Full checks: 512 pass. SSH to the confirmed VPS was refused; user requested
skip and manual execution. Actual VPS A/B/C and voice-quality review remain
pending. Cloud single-pass STT contention: Kokoro sentence 4.637s/RTF1.432,
Piper 0.270s/RTF0.113; Kokoro long gap 5.857s and native cancel drain 3.011s.
Manual commands/results: docs/tts-evaluation/kokoro-int8-vps/.

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
Next action: operator runs the prepared Kokoro INT8/Piper VPS A/B/C commands;
use the Kokoro-first prepared code/settings and migration 0006. Configure the deferred provider key when
ready, then perform live dialogue, real tool and phone-capacity gates. No need
to repeat the passed diagnostic media call.

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
