# Manual VPS benchmark

No live API benchmark has been run from the cloud checkout. Run these commands
as the existing non-root `vasa-builder` owner in `/opt/vasa`, with normal VASA
containers active. Do not run another benchmark or competing TTS workload at
the same time. This harness does not stop containers, alter provider settings,
or deploy anything. API requests incur the account's normal charges.

Prepare the existing checkout and privately read the key into the process
environment. The key is not accepted on the command line, written to evidence,
or printed. The hidden prompt also keeps it out of shell history:

```bash
cd /opt/vasa
git switch build/vasa-foundation
git pull --ff-only origin build/vasa-foundation
uv sync --frozen
read -r -s -p 'Speechify API key: ' SPEECHIFY_API_KEY
printf '\n'
export SPEECHIFY_API_KEY
```

Run both sequential modes, 30 distinct logical responses per mode, with exactly
two excluded HTTP warmup requests total. Use a new output directory on reruns:

```bash
uv run --frozen python -m scripts.benchmark_speechify_vps \
  --scope vps --mode both --requests 30 --voice-id geffen_32 \
  --cpus 0 1 \
  --output docs/tts-evaluation/speechify-simba-3.2-vps/vps
unset SPEECHIFY_API_KEY
```

The VPS preflight requires an owned checkout beneath `/opt/vasa`, non-root UID,
two available CPU affinity indices, and the private environment key. CPU affinity
limits the benchmark process to those CPUs; record `environment.json` to check
the target's actual quota. `--scope component-smoke` explicitly labels any
non-VPS development exercise. Never relabel cloud data as actual VPS evidence.

The fixed trusted voice defaults to `geffen_32`; select another authorized voice
with `--voice-id` and record it. Every request uses `simba-3.2`, streaming
`pcm_16000`, and the same persistent pooled HTTP client. Aborting a stream may
retire its connection; server/proxy idle closures can also require reconnects.
The trace records actual TCP/TLS starts instead of merely asserting reuse.
First-byte latency means the first response body byte, rather than the header
arrival time. Server-Timing TTFB is in milliseconds and is converted to seconds;
first-playable minus server TTFB is only a network/adapter overhead estimate.
Negative estimates are retained and flagged, rather than silently clamped.

Direct mode drains streamed 60 ms frames without real-time pacing, making its
HTTP duration/received audio duration the primary streaming RTF. Buffered mode
uses the actual call runtime's natural chunking and bounded producer/player;
one long logical response can cause several sequential HTTP requests. It writes
both concatenated PCM WAVs and playback WAVs containing measured inter-frame
silence, excluding initial response delay. Its HTTP duration includes consumer
backpressure, so use playback starvation alongside that RTF.

The initial command is TTS-only. For matching native B/C STT contention, add
`--with-stt`: the harness preloads real one-thread Sherpa STT, completes a
standalone fixture baseline while HTTP is idle, then runs the same paced fixture
continuously during both API modes and cancellation probes. Completed fixture
WER and frame-processing deadline misses/overruns are recorded separately from
truncated cleanup fixtures. CPU/RSS then include the real STT worker. Default
model/fixture paths are `.local/speech/asr` and `.local/speech/fixtures`; prepare
them with the existing speech preparation command below.

Each mode reports global and short/sentence/long P50/P90/P95. Thirty responses
mean ten samples per category, so tails remain a small-sample estimate. Failures
are counted and excluded from latency percentiles, never silently retried. A
failed request stops the run with partial evidence and a nonzero exit status.
Before-first-audio and during-playback cancellation probes are excluded from
statistics. Examine `frames_after_cancel`, stream activity and HTTP cleanup
timings; already accepted remote media cannot be retroactively withdrawn.

Optional matched on-device Piper/Kokoro comparisons use the existing harness.
Run these separately from Speechify, sequentially. Condition C records real
normal containers; it does not introduce artificial STT. Actual STT-contention
conditions B/C use real one-thread STT. A/B require the existing operator-isolated
workflow instead. The Speechify comparison command below enables the same STT
fixture workload; normal containers must remain comparable across runs.

```bash
uv run --frozen python scripts/prepare_speech.py
for model in piper kokoro-int8; do
  uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
    --scope vps --candidate "$model" --condition C --iterations 3 \
    --buffered --disable-cache --tts-threads 1 --stt-threads 1 --cpus 0 1 \
    --output "docs/tts-evaluation/speechify-simba-3.2-vps/baselines/$model-C" \
    || exit 1
done
```

Supply actual-VPS `measurements.json` files to a new Speechify run to include
the source records in its comparison. Cloud files are rejected. These local
baseline runs use the historical fixed texts rather than Speechify's varied
texts; category comparisons are contextual rather than identical-text trials.

```bash
read -r -s -p 'Speechify API key: ' SPEECHIFY_API_KEY
printf '\n'
export SPEECHIFY_API_KEY
uv run --frozen python -m scripts.benchmark_speechify_vps \
  --scope vps --mode both --requests 30 --cpus 0 1 --with-stt \
  --piper-results docs/tts-evaluation/speechify-simba-3.2-vps/baselines/piper-C/measurements.json \
  --kokoro-results docs/tts-evaluation/speechify-simba-3.2-vps/baselines/kokoro-int8-C/measurements.json \
  --output docs/tts-evaluation/speechify-simba-3.2-vps/vps-comparison
unset SPEECHIFY_API_KEY
```

Inspect `measurements.json`, `summary.json`, `environment.json` and WAVs. The
user-reported Kokoro reference (sentence first audio about 4.2 s, RTF 1.32,
long starvation 4.28 s) is explicitly approximate and not an independently
verified machine-readable baseline. No actual VPS Piper latency is assumed.

Listen to the WAVs alongside Piper and Kokoro using comparable volume and the
same listening setup. Record human preference separately. Prefer unseen
sentence first audio below 500 ms, P90 below 800 ms, no multi-second playback
starvation and fast cancellation. A production decision additionally needs
voice-quality review and acceptance of external API/network reliability,
account quotas, cost and speech-data handling. This benchmark never changes
the production default.
