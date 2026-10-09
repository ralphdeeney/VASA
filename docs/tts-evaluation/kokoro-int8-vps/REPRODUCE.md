# Manual VPS benchmark

> These are the original condition setup instructions. Kokoro is now the code
> default and LJSpeech is retired. For current buffered settings, output paths,
> migration and cache warmup, follow [optimized reproduction](optimized/README.md).
> The older optional-provider section below documents commit `8ca9f9e`.

SSH from this cloud was refused before authentication. The operator confirmed
the address and requested manual execution. These commands benchmark an
isolated candidate; they do not deploy it or change production configuration.

Run as the existing non-root `vasa-builder` owner of `/opt/vasa`. Preserve any
local changes when updating the checkout to the recorded evaluation commit.
Do not run multiple benchmark commands concurrently, or run other TTS inference
alongside this evaluation. Keep calls drained during the measurements.

```bash
cd /opt/vasa
uv sync --frozen
uv run --frozen python scripts/prepare_speech.py
uv run --frozen python -m scripts.prepare_kokoro_int8
```

The preparation downloads only checksum-pinned model archives into `.local/`.
No model download occurs on the synthesis path. `uv.lock` pins dependencies;
the report also captures installed versions and every model-file SHA256.
Review the existing model/license records before redistributing assets.

Select the VPS's two permitted CPU IDs (normally `0 1`):

```bash
uv run --frozen python -c 'import os; print(sorted(os.sched_getaffinity(0)))'
```

Arrange A/B during a maintenance window where normal application workload is
isolated. The harness never stops services; `--isolated-workload` is your
attestation that you arranged this condition. Leave unrelated services alone.
Run each command to completion before starting the next:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate kokoro-int8 --condition A --isolated-workload \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/vps/kokoro-int8-A

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate piper --condition A --isolated-workload \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/vps/piper-A

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate kokoro-int8 --condition B --isolated-workload \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/vps/kokoro-int8-B

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate piper --condition B --isolated-workload \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/vps/piper-B
```

Restore your normal containers/workload using your existing operational
procedure, then run C. Docker access must use the existing rootless context.
The harness records read-only `docker ps` and `docker stats` snapshots and
refuses C if there are no running containers or they cannot be inspected.
Record what normal workload was active; container presence alone does not
prove that a busy application workload was reproduced.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate kokoro-int8 --condition C \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/vps/kokoro-int8-C

OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate piper --condition C \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/vps/piper-C
```

Each directory contains `measurements.json`, `summary.json`, and both clean
and playback WAV samples for every measured response. Do not overwrite the
top-level pending-VPS records with cloud results. Keep those results in
`cloud-smoke/`; actual server results belong in `vps/`.

After integration, run the complete existing check/eval suite with the
project's development DB/cache and knowledge models prepared:

```bash
uv run --frozen python scripts/prepare_knowledge.py
bash scripts/check.sh --junitxml=reports/kokoro-int8.xml
```

This is a verification command, not a request to start development database
containers on the production VPS. Use a suitable isolated test environment.

## Optional worker selection (do not apply during this benchmark)

The trusted environment settings now support:

```text
VASA_TTS_PROVIDER=kokoro-int8
VASA_KOKORO_MODEL_DIR=/absolute/path/to/verified/kokoro-int8
VASA_KOKORO_NUM_THREADS=1
```

The default remains `ljspeech`. The model is initialized once before calls are
admitted and shared across instances, not once per call. Container execution
would require a read-only candidate-model mount; no deployment manifest or
production environment has been changed. Existing Piper evaluation remains.
