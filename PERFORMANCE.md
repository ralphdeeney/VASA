# Performance

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
