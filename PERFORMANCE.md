## 2026-10-17 — Automated maintenance attempt and verified rollback

See [autonomous delivery](docs/DEPLOYMENT_ORCHESTRATOR.md). A newly pushed
request-only commit automatically starts the shared, serialized Actions bridge,
requires exact source/envelope CI and trusted actor authorization, then dispatches
only an allowlisted controller operation. No manual Actions selection is needed.
Actions39006681009 proved read-only delivery and durable GitHub/VPS journals.

Guarded rollout39006923768 built a fallback old image and candidate, verified
three-database restore checks, confirmed no calls, preserved paired identity and
sampled candidate Evolution connections2/2/2,total4 (before1,total3). Final public
health failed; verified rollback restored the old image. This was not a final
successful pool deployment and does not prove a live reconnect fix. No decrease
from the historical95 connections is claimed against today's smaller baseline.
WhatsApp remains disconnected/logged-out independently of five-service health.
The one-shot maintenance grant is consumed; no blind replacement retry is allowed.

Routine app deployment still refuses preserved operator files in canonical
/opt/vasa. The active app/voice release remains858b5f853957d719a34ea96f28b5ea726100d402.
No database migration, SMTP/provider change, pairing change, direct Codex SSH,
unrelated infrastructure or public networking change was performed.

## 2026-10-17 — Evolution fix tested; live rollout blocked by VPS access

Implementation: f7016fbe005c409cb01a73b11fbd8a913646683a (pushed).
Full automated suite: 1,223 passed, one upstream deprecation warning, 74.89s;
Ruff, formatting, strict mypy, actionlint and Bash validation pass. Native Go
lifecycle, race detector, real PostgreSQL 120-cycle reuse/shutdown, vet and
existing call/media tests passed separately. No speech/provider changes.

Last successful read-only Actions preflight: 38988440298. All five VASA
containers passed existing-state health checks; durable calls=0, Redis calls=0,
non-DNS media sockets=0. Exact registered/upstream instance count=1/1 and its
paired device exists. Its live status was disconnected/logged-out, so container
health must not be confused with WhatsApp readiness. PostgreSQL max=100;
Evolution sockets=95, API=1, voice=1, other=0, total=97.

Maintenance run 38988550199 stopped at rollback_image before target build,
voice pause or Evolution replacement. Raw Docker errors were withheld, so this
stage alone does not prove which image operation failed. The controller now
supports building a verified rollback from the pinned pre-fix public source plus
the existing logging patch, with dedicated lifecycle/failure tests. That fallback
has NOT yet been exercised on the VPS.

Subsequent Actions check 38988774741, including a fresh-runner retry, failed
SSH host-key scanning before login. Public /login and /health/ready both return
HTTP 530 with a Cloudflare Tunnel error. Current live container health cannot
be established. No direct Codex SSH, Cloudflare change, daemon restart, migration
or Evolution replacement was performed. There is no measured post-fix VPS
connection count because the fixed image has not been deployed.

Last verified active app/voice SHA remains
858b5f853957d719a34ea96f28b5ea726100d402; Evolution remains the previous pinned
build of upstream e21ce0dd7634f3047410c893b5e4d1c082034b84, not this fix.
Canonical /opt/vasa/operator files remain preserved; release preparation uses
an isolated .local/evolution-releases directory. SMTP remains explicitly deferred.

Required external action: restore VPS SSH availability to the existing Actions
bridge and the separately managed tunnel; do not weaken pinned SSH host trust.
Then run VASA staging VPS, mode=check/recovery=evolution_check, followed by
mode=check/recovery=evolution_deploy if preflight passes. Backups, repeated
no-call checks, paired-device checks, targeted replacement and rollback remain
mandatory. Require VASA_EVOLUTION_POOL_DEPLOYMENT_OK and record the actual
post-rollout counts/health before a human WhatsApp call. Delivery is NOT complete.

## 2026-10-17 — Authorized Evolution pool lifecycle remediation

Confirmed pinned upstream reconnect path creates an independent PostgreSQL
Whatsmeow store pool on each StartClient without closing the previous pool.
The reviewed patch borrows the existing process-owned bounded auth database
pool via NewWithDB; its owner retains shutdown responsibility. SQLite database
selection, transport, call/media APIs and speech providers are unchanged.

Local Go unit, race, real PostgreSQL 120-cycle reuse/shutdown and existing
call/media tests passed. The isolated source manifest pins both reviewed patches;
existing cached source and runtime secrets are preserved. Live rollout is pending.

GitHub Actions only: dispatch VASA staging VPS with mode=check,
recovery=evolution_check for read-only health/capacity/call inspection; use
recovery=evolution_deploy for the explicitly authorized Evolution-only rollout.
No bootstrap, application migration or automatic Evolution rollout on push.

The maintenance controller checks durable unfinished calls, bounded Redis call
state and all non-Docker-DNS Evolution UDP sockets, plus the exact registered
instance set and verified paired-device membership. A saved offline instance
is eligible for maintenance; post-rollout must be connected and logged in.
Unknown/nonzero call state defers. After backups, pause voice
and recheck to close the VASA answer-admission race; then replace only Evolution,
restore only existing registered device connections, resume voice and validate
all five services, unchanged other container identities and private files.
The private control endpoint must not have independent external call initiators.
The upstream image has no call-list API; zero UDP alone is never accepted as
proof of no calls. A stale unfinished durable record also blocks maintenance.

Backups cover application, Evolution auth and Evolution users databases, with
private receipts/hashes and restoration into disposable databases before restart.
Schema/device/instance credential fingerprints must remain unchanged; no live
schema upgrade is approved. A verified rollback image is retained and only
Evolution is restored if validation fails. If the old running image is missing
from Docker storage, build the pinned pre-fix vendor source with only the existing
logging patch in a separate verified cache, before any target/runtime change.
Never use docker commit or read container environment values. Capacity is sampled three times after
rollout; total Evolution sockets must remain within the two existing 25-open
process pools, and decrease from an exhausted baseline.

SMTP is explicitly deferred by the operator. No credentials are requested or
invented and live email acceptance is not claimed. Human real-call stability
validation remains separate from pool health evidence.

2026-10-16 staging capacity finding (not an inference benchmark):
Actions 38956286230 read-only inspection confirmed PostgreSQL max_connections=100
and established sockets: Evolution 95, VASA API4, voice 1. New connections fail
SQLSTATE 53300 while existing pooled API connections still serve readiness.
Actions 38957178699 recycled only the web pool to permit exact test-fixture cleanup.
This is bounded operational recovery, not a permanent capacity fix. Evolution
source review found independently allocated reconnect SQL pools without lifecycle
closure; pool remediation and a controlled no-call rollout require authorization.
No STT/LLM/TTS performance measurements or provider configuration changed.

# Performance

2026-10-16 SaaS work adds control-plane identity/admin/database operations only.
No speech models, provider configuration, audio pacing, call quotas or runtime
queue behavior were changed. Auth retains native scrypt with four bounded slots;
SMTP delivery is offloaded with four bounded native slots and a ten-second network
timeout, TLS by default. Sessions remain Redis-backed with version revocation.
Directory pagination is bounded to 100 rows, tenant team/workspace lists to 100,
and pending invitations to 100 per organization. No new VPS latency, CPU, capacity
or SMTP-delivery performance measurements are claimed. Full local suite completed
in 84.93s; responsive browser checks are UI evidence only.

2026-10-15 operator-observed reconnect calls last 30–36 seconds and some gaps
recover. These are call durations, not measured gap lengths. New local monotonic
receive_recovered_ms instrumentation and 24-second maximum active receive grace
provide bounded evidence for tuning; no optimal recovery latency is claimed.
TTS/provider performance, 60 ms pacing and bounded queues are unchanged. Upstream
queue age and RTP progress remain unmeasured, so distortion/reconnect is not fixed
by claim. See docs/MEDIA_RECOVERY_POLICY.md for the source-backed policy rationale.

2026-10-15 automatic staging deployment adds bounded read-only HTTP/database/
instance checks, not paid provider benchmarking or speech model loading. Push
forces provider_smoke=false. Restart stabilization remains mandatory; no live
call latency, capacity or reconnect recovery improvement is claimed by deployment
health checks. Public ingress is unverified and external to the VASA bridge.

2026-10-15 operator reports real WhatsApp calls with heard greeting and nonzero
inbound/outbound frames, ending after roughly 10–30 seconds with zero completed
turns and no container restarts. These are observations, not local benchmarks.
Existing media read deadline remains 10 seconds. New fixed markers expose observed
receive gaps over one second and subsequent frame recovery; they do not claim
successful relay renegotiation. No provider/STT/TTS performance settings changed.

2026-10-15 safe provider smoke tooling: live 9Router and Deepgram timings remain
pending. Explicit operator probes measure LLM first streamed text, Deepgram first
playable 60 ms PCM frame, total stream completion, and framed audio duration
(including final frame padding). One small request per provider runs sequentially,
with a 45-second per-probe deadline and bounded client cleanup. These smoke values
are availability checks, not percentile benchmarks or evidence of call capacity.
No provider latency or quality results are claimed. Requests use the configured
OpenAI-compatible base URL/model and selected Deepgram Aura model without printing
their values. Existing provider adapters enforce SSE and mono PCM16/16 kHz framing.

2026-10-14 Deepgram Aura2 integration/tooling is verified without a live key.
No vendor/VPS latency, RTF, CPU/RSS or voice-quality figures exist; pending
receipts use null metrics. Prepared tool measures native streamed16k PCM with
first-body-byte/full60ms-frame timing, two excluded warmups, varied sequential
direct/buffered trials, connections/stalls/cancellation and optional realSTT1.
Actual runtime buffer is reused. Model/request UUIDs remain unknown until
provided by a live response; no immutable model version is invented.

2026-10-12 Speechify Simba3.2 benchmark integration: no live vendor/VPS timing,
RTF, CPU, RSS or voice quality measurements are available. Do not substitute
vendor marketing latency or cloud/native benchmarks. The prepared sequential
harness measures raw PCM first byte versus first full60ms frame, numeric server
TTFB residual, direct/network versus buffered playback timing, CPU/RSS, actual
TCP/TLS starts and cancellation. Two warmups are excluded; default30 varied
responses per mode yield10/category. Optional real STT1 permits B/C comparison.
User-reported Kokoro VPS4.2s/RTF1.32/longgap4.28s remains approximate context.
Speechify root JSON receipts retain null measurements until manual execution.

2026-10-09 Kitten Micro 0.8 matched cloud A/B: three samples/text, affinity0/1,
two-CPU quota, TTS1/STT1, uncached, actual buffered runtime. STT-contention
sentence P50/P95: Kitten2.136/2.309s, Kokoro4.132/4.149s, Piper0.219/0.224s.
Sentence RTF maxima0.313/1.282/0.093; combined CPU2.746/4.481/0.348s; long
peak RSS489.5/617.4/376.2MiB; long max gaps1.764/4.099/0.001s. Kitten solo
sentence CPU2.156s versus Kokoro4.127/Piper0.250. Kitten's sentence audio7.48s
versus3.24/2.40s contributes to its favorable RTF. Consumer cancellation<0.15ms
but before-first native cleanup1.258s; no late frames. Early reuse RSS grows,
then changes about1.3MiB between B trials2/3; long soak is unrun. Preferred
1s first/300ms gap targets are unmet. Cloud evidence is not VPS/phone evidence;
keep the default unchanged pending server and listening results. All records,
WAVs and manual commands: docs/tts-evaluation/kitten-micro/.

2026-10-09 Kokoro-first buffered cloud measurements (one sample/text/profile):
TTS1/STT1 generic prewarmed ack0.6ms, unseen business sentence4.071s/RTF1.257,
four-sentence maximum gap4.127s, combined peakRSS508.8MiB. TTS2/STT1 sentence
3.800s/RTF1.173, gap3.453s, peakRSS511.3MiB; combined sentenceCPU7.034s versus
4.475s with one TTS thread. Generic warmup5.642/5.097s, separately measured.
Piper TTS1/STT1 buffered sentence0.217s, long gap<1ms. New RTF includes provider
callback backpressure; latency/gaps use actual runtime local pacing. Cached
generic performance is not unseen synthesis performance. These are cloud,
not VPS, measurements; keep one thread initially and repeat server tuning.
See docs/tts-evaluation/kokoro-int8-vps/optimized/ for all records/WAVs.

2026-10-09 Kokoro INT8 opt-in integration/cloud smoke: one native thread,
two-core affinity, short/sentence/four-sentence texts, sequential paced chunks,
alone and with actual two-thread STT. Sentence first audio/RTF with STT:
Kokoro 4.637s/1.432, Piper 0.270s/0.113; peak sentence RSS 488.6/317.1 MiB.
Solo sentence CPU seconds 4.196/0.233. Long max gaps 5.857/0.409s. Kokoro
consumer cancellation <0.1ms but native drain up to 3.011s; STT fixture WER
unchanged while max deadline overrun rose to 108ms (Piper 11ms). These are
single-observation cloud smoke figures, not percentiles, actual VPS, or phone
capacity. VPS A/B/C remain pending manual execution due refused SSH. See
docs/tts-evaluation/kokoro-int8-vps/ for evidence, samples and commands.

2026-10-09 isolated conversational TTS study is recorded in
[docs/tts-evaluation/streaming/README.md](docs/tts-evaluation/streaming/README.md).
Four candidates, three texts, two chunk policies and solo/real STT contention
were measured as 144 responses on two-core affinity and quota. Official Kokoro
full-sentence P95 under STT was 2.074–2.313s, with sentence-boundary starvation
and approximately 1.8–2.1 GiB peak RSS. Piper's corresponding P95 was 0.228s,
with no simulated starvation and 433 MiB combined peak. Eighteen one-thread
responses were slower; six legacy-text repeats confirm earlier sherpa timings.
These are cloud component measurements, not actual VPS or phone measurements.
No production provider changes or human naturalness score are claimed.

2026-10-09 concrete tools/storage: finite webhook/call-ending/retrieval deadlines,
bounded response bodies, per-call message/tool limits and bounded pagination are
verified. Eight concurrent SQL transcript writers preserve unique sequencing.
This is a correctness check, not a throughput or ten-active-voice-call benchmark.

2026-10-09 independent tool gateway: active execution has a configurable global
limit (default four), saturation fails immediately, and payloads/registry entries
are bounded. These are verified resource controls, not throughput or ten-call
capacity measurements. No new performance benchmark is claimed.

The user's real-media acceptance reports 98 live inbound frames and 20 diagnostic outbound frames with confirmed audibility. This establishes transport operation, not latency or concurrency. No real voice benchmarks or concurrency load tests have run. Approximately 10 CPU-only simultaneous calls remains a target, not a measured capability.

The source adapter bounds HTTP/WS payloads, pre-handshake frames and network deadlines; diagnostics pace 60 ms PCM frames. The probe reports local state, timing and frame observations after a real call. Its component tests do not establish network latency, audibility, dropped upstream frames or performance under load. The source lacks remote timestamps, playback acknowledgment and drop counters, which must not be fabricated.

Future measurements: P50/P95 VAD end-of-turn, STT finalization, LLM first token, TTS first audio and user-speech-end to first response audio; queue sizes and observed frame loss with supported instrumentation.

## Wave 4 measured native CPU components

Actual five-iteration benchmark stored in docs/evidence/speech-benchmark.json,
reproducible with `uv run --frozen python scripts/benchmark_speech.py`. Linux
x86_64, Python 3.12.14, five logical/affinity CPUs, two native threads/model,
one worker/model; sherpa-onnx/core 1.13.8. Sequential processing, no network LLM,
no paced playback and no live WhatsApp latency in these numbers.

| Measurement | P50 | P95 | Samples |
|---|---:|---:|---:|
| STT full fixture processing | 300.39 ms | 823.58 ms | 15 |
| STT processing/audio duration | 0.04615  | 0.05385  | 15 |
| TTS full phrase processing | 782.62 ms | 812.77 ms | 5 |
| TTS first local audio | 193.31 ms | 202.08 ms | 5 |
| TTS processing/audio duration | 0.26620  | 0.27645  | 5 |

First constructors in benchmark process: STT 403.72 ms, TTS 1900.09 ms; OS file
cache was not flushed, so these are not uncached-disk startup measurements.
STT includes encoder zero-context warmup/final tail, excludes WAV conversion;
TTS includes synthesis/resampling/framing. Three unique fixtures have aggregate
WER 7.79%; five repetitions do not broaden the dataset.

VAD endpoint policy is 300 ms classified silence plus native hangover; wall
latency must be measured separately. Runtime metrics record local STT finalize,
LLM first token, TTS first frame and speech-end to output times; scripted metrics
must not be presented as real provider/phone timings. Remote queued output,
dropped frames and playback cannot be observed with the current source API.
Ten simultaneous CPU calls remain unmeasured; worker admission is bounded to two.

## Integrated native load guard — 2026-10-09

The controlled synthetic load harness ran three rounds of ten utterances with
mixed STT/TTS cancellation. Native generation admission is bounded while paced
playback streams remain independently bounded. Across 30 utterances, P95 TTS
first audio improved from 10.555s before the scheduling fix to 1.083s after it;
synthetic fixture-end to first audio improved from 11.476s to 1.798s. Peak RSS
was 294840 KiB, cancellation completed within 588 ms and cleanup within 31 ms,
with no residual tasks or native worker threads. This is a local synthetic
component measurement: it does not establish live provider, WhatsApp delivery,
audibility or ten-call phone capacity.

Production single-process native smoke with Docker limits 512 MiB/one CPU:
STT/TTS initialization and short TTS speech succeeded as UID 1000/read-only root;
maximum observed process RSS 269164 KiB. This excludes simultaneous calls and
additional API process memory; do not infer deployment capacity from it.

Final benchmark refreshed after disabling stochastic VITS noise; model hashes
and independent recognition acceptance unchanged. Native TTS repeated output
is byte-identical; the report records both noise scales as zero. Measurements
remain sequential CPU components, not phone/LLM latency or concurrency.
