# Kitten Micro 0.8 evaluation

Kitten Micro improves materially on Kokoro INT8 in this matched cloud study,
but remains much slower than Piper and misses the preferred conversational
latency/gap targets. **Do not promote it yet.** Kokoro remains the code/config
default; Kitten is the next candidate for VPS and listening validation. Piper
remains the fastest fallback. Actual VPS A/B/C and human naturalness review are
pending, so production readiness is not established.

## Measured comparison

Two-CPU affinity/quota; one TTS and one STT native thread; identical short,
business sentence and four-sentence response; three iterations per text;
uncached speech; common natural chunking and actual bounded VASA buffering.
Candidates ran sequentially. A is TTS alone; B adds real paced native STT.
There are 54 measured responses and 108 playable mono PCM16/16 kHz WAVs.

| Condition / candidate | Sentence first P50 / P95 (s) | Sentence RTF max | Sentence CPU (s) | CPU utilization (%) | Peak RSS (MiB) | Long max gap (s) |
|---|---:|---:|---:|---:|---:|---:|
| A / Kitten Micro | 2.099 / 2.112 | 0.284 | 2.156 | 22.4 | 400.1 | 1.693 |
| A / Kokoro INT8 | 4.060 / 4.157 | 1.287 | 4.127 | 56.1 | 534.5 | 4.139 |
| A / Piper | 0.216 / 0.266 | 0.113 | 0.250 | 9.5 | 302.0 | <0.001 |
| B / Kitten Micro | 2.136 / 2.309 | 0.313 | 2.746 | 28.3 | 489.5 | 1.764 |
| B / Kokoro INT8 | 4.132 / 4.149 | 1.282 | 4.481 | 60.9 | 617.4 | 4.099 |
| B / Piper | 0.219 / 0.224 | 0.093 | 0.348 | 13.3 | 376.2 | 0.001 |

CPU is mean per-response process CPU time/utilization; B includes STT. 100%
utilization is one CPU, measured over paced response wall time. RSS is the
maximum process high-water measurement during long-response trials; B includes
STT. A's CPU/RSS measurements are the useful isolated TTS comparison.

Under B, Kitten reduces sentence first audio about 48% and long maximum gap
about 57% against Kokoro, with about 128 MiB less peak memory. Its sentence
latency is still about 9.8 times Piper's. Solo sentence CPU is about 48% lower
than Kokoro and 8.6 times Piper's. These are cloud comparisons on this host.

| Candidate | Load A / B (s) | B short first P50 (s) | B long first P50 (s) | B sentence audio duration (s) |
|---|---:|---:|---:|---:|
| Kitten Micro | 0.523 / 0.530 | 0.850 | 1.279 | 7.48 |
| Kokoro INT8 | 1.103 / 1.184 | 2.090 | 2.495 | 3.24 |
| Piper | 0.639 / 0.622 | 0.101 | 0.121 | 2.40 |

Kitten speaks these samples more slowly. That helps its RTF denominator, so
absolute latency and CPU seconds must accompany RTF. Human review must assess
whether that pacing is acceptable. No naturalness score is inferred.

RTF sums awaited provider work, including native inference and provider callback
backpressure, divided by generated audio duration; runtime queue waits are
excluded. Full provider completion and paced response wall time are separate
measurements. Each chunk has start/first-frame/completion/playback timestamps.
These are not isolated decoder throughput timings. Model load includes artifact
verification/construction with OS caches unflushed. P95 is interpolated from
only three samples per case and is not a reliable production tail estimate.

## Cancellation, STT and memory

| Candidate under B | Maximum consumer stop (ms) | Native cleanup before first audio (s) | Native cleanup during playback (s) | Frames after cancellation |
|---|---:|---:|---:|---:|
| Kitten Micro | 0.145 | 1.258 | 0.012 | 0 |
| Kokoro INT8 | 0.123 | 2.594 | 0.097 | 0 |
| Piper | 111.313 | 0.008 | 0.007 | 0 |

Consumer stop and native cleanup are distinct. Kitten/Kokoro native inference
cannot be interrupted mid-acoustic-segment; native admission remains held until
drain completes. Piper's consumer cancellation includes draining its in-flight
native operation, explaining its different timing distribution. These probes
measure local consumers, not a phone playback acknowledgement.

Real STT fixture WER stayed at 1/18 (5.56%) for all candidates and their idle-TTS
baselines. Maximum processing deadline overrun under B was 0 ms for Kitten,
44.7 ms for Kokoro and 0 ms for Piper. Kitten's paced fixture wall-time change
was +0.008%; Kokoro +0.094%; Piper +0.015%. Only one repeated independent
fixture is used, with 21/19/7 complete contender runs respectively. This is
limited evidence and does not establish general STT non-degradation.

Sampled RSS timelines, per-response before/after RSS and three post-long-response
RSS readings are retained. Inspect `summary.json` memory reuse observations;
Kitten post-long RSS rises 287.6 ->398.5 ->400.4 MiB solo and
377.5 ->488.6 ->489.9 MiB with STT. This shows substantial early reuse growth,
followed by a smaller third-trial change; a longer soak is needed before claiming
stable memory. Inter-frame and
inter-chunk starvation are recorded separately; no remote WhatsApp timing or
playback continuity is inferred from local measurements.

## Listening samples

All corresponding sentence files were generated from the exact input:
`Your appointment is confirmed for tomorrow morning at ten o'clock.`
Corresponding short and long files also share identical input text across all
three models. `wav-manifest.json` maps every filename to exact text, WAV format
and SHA256. Playback WAVs include measured post-start playback gaps.

| Candidate | Same sentence | Same long response | Long response with measured gaps |
|---|---|---|---|
| Kitten Micro | [sentence](cloud-smoke/kitten-micro-B/kitten-micro-B-sentence-0.wav) | [long](cloud-smoke/kitten-micro-B/kitten-micro-B-long-0.wav) | [playback](cloud-smoke/kitten-micro-B/kitten-micro-B-long-0-playback.wav) |
| Kokoro INT8 | [sentence](cloud-smoke/kokoro-int8-B/kokoro-int8-B-sentence-0.wav) | [long](cloud-smoke/kokoro-int8-B/kokoro-int8-B-long-0.wav) | [playback](cloud-smoke/kokoro-int8-B/kokoro-int8-B-long-0-playback.wav) |
| Piper | [sentence](cloud-smoke/piper-B/piper-B-sentence-0.wav) | [long](cloud-smoke/piper-B/piper-B-long-0.wav) | [playback](cloud-smoke/piper-B/piper-B-long-0-playback.wav) |

Human review is pending in `listening-review.json`: assess naturalness relative
to Piper, pronunciation, pacing and chunk continuity. Kokoro logged skipped
unknown phonemes U+025A/U+0329; include pronunciation in this review. Voice
quality has not been judged to justify Kitten's additional latency over Piper.

## Integration and decision

Trusted settings select `kitten-micro`, `kokoro-int8` or `piper`. Kitten assets
are under `.local/speech/kitten-micro`; one model is preloaded/shared per worker
with `VASA_KITTEN_NUM_THREADS=1`. Bella is speaker 1, speed/length scale 1.
Kitten reuses bounded native ownership, natural chunking, resampling/framing
and cancellation, with no speech caching by default. No arbitrary tenant,
customer or generated speech enters shared caches. TTSProvider, current default,
existing providers, bounded playback and Evolution media transport are preserved.
Completed acoustic segment callbacks are not incremental decoder streaming.

Do not change the default: preferred sentence first audio <=1 s and long gap
<=300 ms are unmet despite RTF <=0.7. Actual VPS contention and human voice
quality remain unverified. Validate Kitten next because its cloud balance is
better than Kokoro's; retain Piper as the fastest fallback. Further controlled
experiments could test a natural shorter first clause and bounded prefetch
tuning, using identical buffering across providers and rechecking cancellation.

## VPS, pins and verification

Actual VPS A/B/C remain pending manual execution. Earlier SSH to the confirmed
`vasa-builder@2.25.172.155:22` was refused; the user instructed us to skip remote
access. No new attempt or deployment is claimed. Condition C requires actual
normal VPS containers/workload with no competing TTS inference.
[REPRODUCE.md](REPRODUCE.md) gives exact preparation and A/B/C commands.

User-reported approximate VPS Kokoro figures (4.2 s sentence, RTF 1.32,
long first 2.55 s/gap 4.28 s/RSS 638 MiB) are recorded separately, without mixing
them into matched cloud comparisons or claiming raw VPS evidence was verified.

`measurements.json`, `summary.json`, `environment.json` and `verification.json`
record measurements, decisions, system information and automated verification.
`model-provenance.json`, `dependency-versions.json`, `LICENSES.md`, `licenses/`
and `SHA256SUMS` retain exact artifact/dependency pins and notices. The selected
official Micro 0.8 archive is mixed/dynamically quantized ONNX, not Nano or the
newer KittenTTS 2. Micro weights/Sherpa are Apache-2.0; eSpeak GPL-3.0 and other
bundled notices remain applicable. No new inference dependency is added;
the existing committed `uv.lock` fixes exact dependency versions/artifact hashes.
