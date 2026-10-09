# Reproduce the Kitten Micro comparison

The benchmark selects a model inside its own process. It does not change
`VASA_TTS_PROVIDER`, deploy a worker, stop services, or select a production default.
Kitten Micro remains a candidate until actual VPS measurements and human listening
review satisfy the decision criteria. Run every cohort sequentially; do not run
other TTS benchmarks or live voice synthesis concurrently.

## Prepare pinned assets

From the existing checkout as its owner, using Python 3.12 and the committed lock:

```bash
uv sync --frozen
uv run --frozen python scripts/prepare_speech.py --kitten-micro
```

This verifies/prepares ASR, fixtures, Kokoro INT8 and Piper, and adds the optional
Kitten Micro assets under `.local/speech/kitten-micro`. Existing providers retain
their paths and production configuration. Preparation rejects mismatched cached
artifacts instead of silently overwriting them. No model download occurs during
benchmark inference or a call.

## Cloud/local matched A/B comparison

Run on a host restricted to a **two-CPU quota**, with CPUs 0 and 1 available.
`--cpus` sets affinity, not a quota. Record the actual quota in `environment.json`;
the benchmark also captures `/sys/fs/cgroup/cpu.max` in every measurement file.
The project cloud environment uses `200000 100000` (two CPUs).

```bash
for candidate in kitten-micro kokoro-int8 piper; do
  for condition in A B; do
    uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
      --scope cloud-smoke --candidate "$candidate" --condition "$condition" \
      --iterations 3 --buffered --disable-cache \
      --tts-threads 1 --stt-threads 1 --cpus 0 1 \
      --output "docs/tts-evaluation/kitten-micro/cloud-smoke/$candidate-$condition" \
      || exit 1
  done
done
```

This produces six sequential cohorts with three runs of each identical short,
sentence and long response. Condition B runs real native paced STT, including an
idle-TTS STT baseline. All providers and the real runtime reuse their normal
bounded buffering and mono PCM16/16 kHz/60 ms framing. Kokoro shared caching is
disabled; Kitten and Piper do not retain synthesized speech in this evaluation.
Generic startup warmup is omitted for every candidate. The first response uses
the freshly loaded model; subsequent responses reuse it. OS caches are not flushed.

Condition C is not invented with a dummy CPU loop. It requires actual running
normal-workload Docker containers and readable `docker ps`/`docker stats`.
Cloud measurements do not substitute for VPS results.

## Actual VPS: A and B

Log in as the existing non-root `vasa-builder` account and use its owned checkout
under `/opt/vasa`. Keep production configuration unchanged. The harness rejects
root and other checkout locations. Prepare the pinned assets with the commands
above. CPUs 0 and 1 must be available; record target CPU/quota and idle workload.

For A/B, first arrange an isolated operator-controlled benchmark window. The
flag below is an attestation, not a command that isolates or stops services.
Do not run it while normal VPS work is contending and then label results isolated.
Do not stop or modify unrelated containers or services.

```bash
cd /opt/vasa
for candidate in kitten-micro kokoro-int8 piper; do
  for condition in A B; do
    uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
      --scope vps --candidate "$candidate" --condition "$condition" \
      --isolated-workload --iterations 3 --buffered --disable-cache \
      --tts-threads 1 --stt-threads 1 --cpus 0 1 \
      --output "docs/tts-evaluation/kitten-micro/vps/$candidate-$condition" \
      || exit 1
  done
done
```

If the checkout is in an owned subdirectory of `/opt/vasa`, change into that
checkout instead. The same guard permits it. Use a fresh output directory for a
rerun to preserve previous evidence.

## Actual VPS: C with normal services/workload

Leave the normal VPS containers/workload active and document their load in a
run note. Make sure no live call or other job is synthesizing with a competing
TTS model during the benchmark. Keep services and production flags unchanged.
Container names/images/status and utilization snapshots are captured read-only;
container commands and environment variables are not recorded.

```bash
for candidate in kitten-micro kokoro-int8 piper; do
  uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
    --scope vps --candidate "$candidate" --condition C \
    --iterations 3 --buffered --disable-cache \
    --tts-threads 1 --stt-threads 1 --cpus 0 1 \
    --output "docs/tts-evaluation/kitten-micro/vps/$candidate-C" \
    || exit 1
done
```

The script fails if C cannot read normal running containers. It does not start
placeholder containers. Native STT runs in the benchmark process while the
normal external workload remains active. For every cohort, model loading occurs
once before measured responses; cancellation trials close that instance and
create separate trial instances sequentially.

## Evidence and interpretation

Each cohort writes `measurements.json`, `summary.json`, generated WAVs and WAVs
containing the measured post-start playback gaps. Naming is:
`<candidate>-<condition>-<short|sentence|long>-<0|1|2>.wav` and the same name
with `-playback.wav`. All candidates' corresponding cases contain exactly the
same input text. Native duration and pronunciation may differ.

- First playable latency ends at the first valid local media frame, including
  leading acoustic silence; it does not measure WhatsApp network/phone playback.
- Per-chunk `complete_seconds` and response
  `full_response_provider_completion_seconds` mark provider exhaustion under
  actual buffering/backpressure. They are not isolated native decoder timings.
- `provider_wait_seconds`/`synthesis_compute_seconds` sum awaited provider work,
  including provider-side backpressure, excluding runtime queue waits. RTF uses
  that sum divided by generated audio duration. Paced response wall time is
  reported separately. A good RTF alone does not establish good first audio.
- CPU is process CPU seconds and utilization (100% is one CPU). B/C include STT
  in the same process. Normal external containers are measured in separate
  snapshots, so do not call B/C figures isolated TTS consumption.
- RSS is process high-water memory plus a sampled timeline and per-response
  before/after RSS. Compare similar conditions and inspect stability.
- STT comparison excludes incomplete shutdown fixtures and reports WER, paced
  wall time and processing deadline overruns. One repeated fixture is limited
  evidence, not a general STT quality test.
- Cancellation reports consumer stop and native cleanup separately. Immediate
  consumer stop cannot prove native inference is preemptible. Complete acoustic
  segments split into 60 ms frames are not incremental decoder streaming.
- P50/P95 are interpolated from three samples per case; this is a small sample
  and does not establish a reliable production tail.

Listen to matched sentence/long WAVs with the same audio setup and record whether
Kitten is noticeably more natural than Piper, with acceptable pronunciation and
continuity. Record the human reviewer/date/decision instead of inventing a quality
score. Promote only after actual VPS A/B/C and listening are complete. Retain Piper
as the fastest fallback even if Kitten meets the promotion criteria.
