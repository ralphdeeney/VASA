# Reproduction and artifacts

Run from the VASA checkout in a development environment. Do not run this
evaluation on a production VPS or alongside an active voice worker. A suitable
Linux host must permit CPU affinity on two cores. Native model preparation
and existing STT fixtures must already be available under `.local/speech/`.

Use a separate Python environment, not the production `.venv`:

```bash
uv venv .local/kokoro-streaming-venv --python 3.12
uv pip install --python .local/kokoro-streaming-venv/bin/python \
  torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .local/kokoro-streaming-venv/bin/python --no-deps \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match \
  -r docs/tts-evaluation/streaming/requirements.lock.txt
uv run --frozen python scripts/prepare_kokoro_streaming.py
```

The official code dependency is pinned to an immutable source archive in the
lock file. The English spaCy model is also pinned to an explicit wheel URL.
Neither dependency is added to VASA's production dependency declarations.
The `prepare_kokoro_streaming.py` script validates all official model, config
and voice SHA256 hashes and uses immutable Hugging Face revisions. It refuses
changed cached files rather than replacing them. Sherpa artifacts reuse the
archives and hashes recorded in the parent TTS evaluation report.

Run the primary experiment with network access disabled for model loading:

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 \
.local/kokoro-streaming-venv/bin/python scripts/evaluate_tts_streaming.py \
  --cpus 0 1 --iterations 3
```

Select two available cores if they differ from 0 and 1. The experiment runs
four candidates, first alone and then with one STT stream. Only the explicitly
requested STT contender runs alongside each TTS model. The parent starts each
candidate/mode as a fresh process, waits for its exit, and never loads another
TTS model concurrently. Each child has a finite parent timeout.

For the supplementary single-thread contention experiment, run the following
once per official model, sequentially:

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 \
.local/kokoro-streaming-venv/bin/python scripts/evaluate_tts_streaming.py \
  --candidate official-v10 --contention --threads 1 --policies sentence \
  --output docs/tts-evaluation/streaming/one-thread
```

Repeat with `official-v11` after the first process exits. This experiment
changes both STT and TTS native thread counts, so it tests an alternative
shared-CPU scheduling configuration.

WAV naming: `{candidate}-{solo|stt}-{short|sentence|long}-{whole|sentence}.wav`.
These contain concatenated generated PCM. Files ending in `-playback.wav`
include the scheduling simulation's post-start starvation silence. They do
not include the initial first-audio wait. Every sample is mono PCM16, 16 kHz;
native sample-rate conversion and final 60 ms frame padding are included in
measured first-playable timing. The previous evaluation's WAVs are unchanged.

`measurements.json` retains individual responses and per-chunk start, ready,
generation duration, process CPU seconds and audio duration. First playable
means the first contract-valid 60 ms frame was available to an async consumer;
the frame may include leading acoustic silence. This is more specific than
the previous benchmark's complete-buffer latency, but still excludes an
actual sound device, LLM streaming and WhatsApp delivery.

After completing the experiments, export individual chunks and summaries:

```bash
.local/kokoro-streaming-venv/bin/python scripts/summarize_tts_streaming.py
```

This copies original measured PCM into `-chunk-01.wav`, `-chunk-02.wav` and
subsequent files without synthesizing again. `chunk-samples.json` records each
chunk's text, timing and hash. `summary.json` aggregates measurements, and
`SHA256SUMS` covers the saved study files.
