# Performance

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
| STT full fixture processing | 482.17 ms | 1090.56 ms | 15 |
| STT processing/audio duration | 0.06513 | 0.09930 | 15 |
| TTS full phrase processing | 815.26 ms | 842.74 ms | 5 |
| TTS first local audio | 158.02 ms | 189.38 ms | 5 |
| TTS processing/audio duration | 0.26130 | 0.28008 | 5 |

First constructors in benchmark process: STT 316.98 ms, TTS 2316.11 ms; OS file
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
