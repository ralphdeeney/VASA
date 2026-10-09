# CPU TTS evaluation

This directory contains an isolated comparison of the existing LJSpeech Medium
baseline with Kokoro 82M FP32, Kokoro 82M INT8, Piper LibriTTS-R Medium and the
sherpa-onnx MeloTTS conversion. The production `SherpaTTS` provider and the
WhatsApp media path were not changed.

The harness is [benchmark_tts_evaluation.py](../../scripts/benchmark_tts_evaluation.py).
It prepares official sherpa-onnx release archives, records their SHA256 hashes,
and runs one candidate per fresh subprocess. Candidates are never loaded or
measured concurrently. Each run uses the identical text:

> Hello. Your appointment is confirmed for tomorrow morning.

The WAV files are playable samples from the first iteration. The JSON report
contains every iteration, first-audio/generation latency, real-time factor,
process CPU time, peak RSS, output sample rate and model hash.

## Results

Five iterations per candidate, two native threads, Linux x86_64. `first audio`
is the time until sherpa-onnx's offline generation returns its first complete
audio buffer; this is an offline lower-level proxy, not streamed phone latency.
RSS is the process maximum in KiB.

| Candidate | P50 first audio (s) | P95 first audio (s) | P50 RTF | Peak RSS (KiB) | Sample rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| LJSpeech Medium baseline | 0.589 | 0.601 | 0.206 | 173,324 | 22,050 |
| Kokoro 82M FP32 | 2.222 | 2.225 | 0.653 | 580,984 | 24,000 |
| Kokoro 82M INT8 | 4.472 | 4.573 | 1.334 | 427,176 | 24,000 |
| Piper LibriTTS-R Medium | **0.153** | **0.162** | **0.067** | **198,776** | 22,050 |
| MeloTTS sherpa-onnx conversion | 1.566 | 1.590 | 0.441 | 384,612 | 44,100 |

The measured CPU-efficiency recommendation is Piper LibriTTS-R Medium for a
separate quality/listening trial: it had the lowest latency, real-time factor
and memory among the alternatives. This is not a production replacement
decision. The samples and benchmark do not measure pronunciation quality,
prosody, streamed playback, interruption behavior, WhatsApp delivery or
licensing suitability for a particular distribution. Production remains on the
existing LJSpeech provider until those gates are reviewed.

Reproduce after preparing the pinned artifacts:

```bash
uv run --frozen python scripts/benchmark_tts_evaluation.py --prepare
uv run --frozen python scripts/benchmark_tts_evaluation.py --all \
  --iterations 5 --threads 2 --output docs/tts-evaluation/report.json
```

The evaluation artifact cache is intentionally under ignored `.local/`; only
the measured report and small WAV samples belong in this directory.
