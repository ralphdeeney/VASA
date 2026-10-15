# Manual Deepgram Aura TTS validation and VPS benchmark

This integration covers Aura text-to-speech only. It does not select Deepgram
STT or change VASA's production provider. No live measurements or listening
results are supplied by mocked tests. Wait until `DEEPGRAM_API_KEY` has been
privately configured before live validation; never paste it into chat, put it
on a command line, or save it in a tracked file.

Run as the existing non-root `vasa-builder` owner in `/opt/vasa`. Keep normal
containers active for the normal-workload comparison. Run one benchmark at a
time; the harness never stops containers or changes production settings.

```bash
cd /opt/vasa
git switch build/vasa-foundation
git pull --ff-only origin build/vasa-foundation
uv sync --frozen
read -r -s -p 'Deepgram API key: ' DEEPGRAM_API_KEY
printf '\n'
export DEEPGRAM_API_KEY
```

If a protected runtime environment already supplies `DEEPGRAM_API_KEY`, omit
the hidden prompt. Do not enable shell tracing. Requests incur the account's
normal charges. The benchmark does not accept an API-key CLI argument.

Run both modes with exactly two excluded warmup requests total, followed by
30 measured sequential logical responses per mode:

```bash
uv run --frozen python -m scripts.benchmark_deepgram_vps \
  --scope vps --model aura-2-thalia-en --mode both --requests 30 \
  --cpus 0 1 \
  --output docs/tts-evaluation/deepgram-aura-2-vps/vps
unset DEEPGRAM_API_KEY
```

The endpoint is `POST https://api.deepgram.com/v1/speak`, with `model`,
`encoding=linear16`, `container=none`, and `sample_rate=16000`. One persistent
pooled HTTP client serves warmups, measurements and cancellation probes.
Output is mono PCM16 at 16 kHz framed in 60 ms units. There is no resampling
for this requested native format. The requested Aura model is recorded;
response model/request metadata is nullable when the server does not supply it.

Use `--scope component-smoke` only for explicit non-VPS development validation;
its results are labelled `actual_vps=false`. A minimum of 20 measured requests
per mode is enforced even for this scope. The VPS scope requires an owned
checkout beneath `/opt/vasa`, non-root UID and two available CPU indices.
Affinity is not a claim that a CPU quota exists; inspect `environment.json`.
Use a fresh output directory on reruns; existing measurements are not replaced.

Direct mode drains actual streamed frames without playback pacing. Buffered
mode uses the existing call runtime's sentence/clause splitting and bounded
playback buffer. One long logical response can produce multiple sequential
HTTP requests. Numbered synthetic texts and clauses vary across requests and
modes; warmups and cancellation probes are excluded from percentile statistics.
Thirty responses yield ten samples per category, so P90/P95 remain descriptive
small-sample estimates. Failures are counted and stop the run with sanitized
partial evidence, rather than being silently retried or counted as fast speech.

Measurements separate response-body first byte, first complete playable frame,
HTTP completion, audio duration, effective RTF, bytes/status, stream stalls,
CPU/RSS, TCP/TLS connection starts, cancellation and cleanup. Server-Timing is
recorded only when valid; absent server TTFB leaves network-overhead estimates
null. First playable minus reported server TTFB is an estimate rather than
isolated network RTT. Direct simulated starvation and actual buffered playback
starvation are labelled separately. Buffered HTTP RTF includes backpressure.
Process CPU/RSS excludes other containers; optional real STT is included when
enabled. WAV files contain synthetic test speech, with extra buffered playback
WAVs retaining measured gaps after first audio.

For matching real one-thread STT contention, prepare the pinned local assets and
add `--with-stt`. This runs a completed standalone STT fixture baseline before
the two API warmups, then repeats the same paced fixture during measurements.
Completed WER/deadline metrics are separate from truncated cleanup fixtures.
This evaluates existing Sherpa STT contention, not a Deepgram STT integration.

Run matched native references sequentially, with normal VPS containers active:

```bash
uv run --frozen python scripts/prepare_speech.py
for model in piper kokoro-int8; do
  uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
    --scope vps --candidate "$model" --condition C --iterations 3 \
    --buffered --disable-cache --tts-threads 1 --stt-threads 1 --cpus 0 1 \
    --output "docs/tts-evaluation/deepgram-aura-2-vps/baselines/$model-C" \
    || exit 1
done
```

Privately reconfigure the key, then include those actual-VPS measurements:

```bash
read -r -s -p 'Deepgram API key: ' DEEPGRAM_API_KEY
printf '\n'
export DEEPGRAM_API_KEY
uv run --frozen python -m scripts.benchmark_deepgram_vps \
  --scope vps --model aura-2-thalia-en --mode both --requests 30 \
  --cpus 0 1 --with-stt \
  --piper-results docs/tts-evaluation/deepgram-aura-2-vps/baselines/piper-C/measurements.json \
  --kokoro-results docs/tts-evaluation/deepgram-aura-2-vps/baselines/kokoro-int8-C/measurements.json \
  --output docs/tts-evaluation/deepgram-aura-2-vps/vps-comparison
unset DEEPGRAM_API_KEY
```

Only `scope=vps`, `actual_vps=true` native baseline records are accepted. Native
fixed texts differ from the API's varied texts, so comparisons are contextual
category comparisons rather than identical-text paired measurements. Align
normal container load and STT conditions across runs. User-reported Kokoro VPS
sentence first audio around 4.2 s, RTF 1.32 and long starvation 4.28 s remain
explicitly approximate; no unmeasured actual VPS Piper value is invented.

Review `measurements.json`, `summary.json`, `environment.json`, cancellation
probes and listening WAVs. Prefer unseen sentence first audio below 500 ms,
P90 below 800 ms, no multi-second starvation and quick cancellation without
late frames. Human naturalness review, account cost/quotas, external network
reliability and speech-data handling remain separate production decision gates.
No benchmark automatically promotes Aura or changes the configured TTS default.
