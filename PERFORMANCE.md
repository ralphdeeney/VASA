# Performance

No real voice benchmarks or concurrency load tests have run. Approximately 10 CPU-only simultaneous calls remains a target, not a measured capability.

The source adapter bounds HTTP/WS payloads, pre-handshake frames and network deadlines; diagnostics pace 60 ms PCM frames. The probe reports local state, timing and frame observations after a real call. Its component tests do not establish network latency, audibility, dropped upstream frames or performance under load. The source lacks remote timestamps, playback acknowledgment and drop counters, which must not be fabricated.

Future measurements: P50/P95 VAD end-of-turn, STT finalization, LLM first token, TTS first audio and user-speech-end to first response audio; queue sizes and observed frame loss with supported instrumentation.
