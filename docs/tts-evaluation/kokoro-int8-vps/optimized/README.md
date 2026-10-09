# Kokoro-first implementation and measured optimizations

The operator explicitly chose Kokoro and retired LJSpeech after the original
comparison. Kokoro INT8 is now the code/deployment **default**; Piper remains
selectable. No live VPS deployment is claimed: SSH remains unavailable and the
operator will run the server benchmark manually. Historical WAVs/results are
retained unchanged; earlier recommendations/defaults describe their own revision.

## Six priorities implemented

| Priority | Implementation | Practical limit |
|---|---|---|
| INT8 | Pinned Sherpa Kokoro v1.1 INT8, speaker 0 Maple | Quantization has not made unseen speech faster than real time in this cloud test |
| Callback audio | Actual native callback PCM, converted to mono PCM16/16 kHz, 60 ms frames, bounded eight-frame queue | Upstream Kokoro emits a complete acoustic segment, not decoder-time fragments |
| Intelligent chunks | Sentence/clause boundaries with meaningful phrases, maximum 120 characters | Avoid tiny prefixes that improve timing figures by damaging prosody |
| CPU tuning | Independent STT/TTS flags; both default to one thread, one Kokoro native lane | Two TTS threads shortened latency slightly but consumed more CPU here |
| Model reuse | One preloaded, shared worker model; fixed generic phrases warmed before admission | Startup includes model verification and one-time acknowledgement synthesis |
| Buffer/cache | Two pending text chunks, 16 playback frames ahead, bounded 2 MiB/32-entry generic-only LRU | Buffering cannot eliminate sustained starvation when synthesis RTF exceeds one |

Cache entries are restricted to `Certainly, I can help.`, `One moment, please.`
and `Thank you.`. Arbitrary business, tenant, caller or generated text is never
stored in the shared cache. Cached output must not be represented as unseen
speech synthesis performance. The model/voice fixes the cache identity; entries
are cleared on provider shutdown.

Callback backpressure remains bounded. Consumer close/barge-in stops forwarding
and unblocks canceled queue producers, while native ownership is retained until
inference finishes. Complete-segment inference cannot be forcibly interrupted.
The existing transport, framing and generation guards remain intact. Tool
actions wait for earlier speech; speculative business actions are not introduced.

## Actual cloud observations

All three configurations use two-core affinity/quota, one native STT thread,
actual runtime buffering and local 60 ms playback. Each text has **one** sample;
these are preliminary observations, not reliable tail percentiles or VPS results.
Kokoro's three generic phrases were warmed once before measuring responses.

| Configuration | Acknowledgement first audio | Uncached business sentence first audio | Sentence RTF | Sentence CPU seconds, including STT | Long maximum gap |
|---|---:|---:|---:|---:|---:|
| Kokoro TTS1/STT1 | 0.6 ms | 4.071 s | 1.257 | 4.475 | 4.127 s |
| Kokoro TTS2/STT1 | 0.8 ms | 3.800 s | 1.173 | 7.034 | 3.453 s |
| Piper TTS1/STT1 | 101 ms (uncached) | 0.217 s | 0.090 | 0.331 | <1 ms |

One-time Kokoro generic warmup took 5.642 s with one TTS thread and 5.097 s
with two. Model loading was 1.239/1.183 s, separately recorded. Peak process RSS
by the long response was 508.8/511.3 MiB including STT. The business sentence
still misses the preferred <900 ms target. A cache hit does not change that.

The two-thread result saves about 0.27 s on the sentence but uses roughly 57%
more combined process CPU seconds in this single observation. Keep one thread
as the starting configuration on the two-vCPU server; repeat the tuning on the
actual VPS before selecting a different count. These samples do not establish
memory stability, voice quality or phone capacity.

The earlier sequential one-thread Kokoro + two-thread STT result had a 5.857 s
long-response gap. The current one-thread configuration measured 4.127 s, but
chunking, thread configuration, buffering and cache warmup changed together:
the difference cannot be attributed to buffering alone. Multi-second gaps
remain unresolved for uncached speech.

`provider_wait_seconds` includes native inference and provider callback queue
backpressure. Its ratio to generated audio is the reported RTF; runtime queue
waits and playback sleeps are excluded. This is a conservative provider wait
metric, not an isolated decoder throughput measurement. First playable timing
uses actual runtime media sends to the local recorder. Playback WAVs include
measured gaps, not the initial first-audio wait. No real LLM latency is simulated.

The native model/hash/version pins are unchanged from `../artifacts.json`;
individual reports record the full model trees, system information, thread
settings, warmup, cache-hit status and raw response/cancellation/STT records.

## Manual reproduction on the VPS

Run as the existing project owner under `/opt/vasa`. Preserve local changes
when updating to the Kokoro-first commit, then prepare assets and apply the
voice-default migration in your normal deployment procedure:

```bash
uv sync --frozen
uv run --frozen python scripts/prepare_speech.py
uv run --frozen alembic upgrade head
```

Preparation downloads verified Kokoro and Piper assets into the existing
speech volume; it no longer downloads or verifies LJSpeech. Migration `0006`
converts only the retired `ljspeech_en` voice to `kokoro_af_maple`, preserving
tenant/agent identifiers and other voice values. The API/dashboard default also
uses Maple. Unrelated services and the Evolution transport are unchanged.

For each condition/candidate, use the commands in `../REPRODUCE.md`, adding
`--buffered --tts-threads 1 --stt-threads 1`. Add `--warmup-generic` only for
Kokoro, matching worker startup. Keep new results under `optimized/vps/`.
For example, with isolated normal workload and real STT:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
uv run --frozen python -m scripts.benchmark_kokoro_int8_vps \
  --scope vps --candidate kokoro-int8 --condition B --isolated-workload \
  --buffered --tts-threads 1 --stt-threads 1 --warmup-generic \
  --cpus 0 1 --iterations 3 \
  --output docs/tts-evaluation/kokoro-int8-vps/optimized/vps/kokoro-t1-stt1-B
```

Repeat sequentially for A and C, following their documented workload setup.
Then repeat Kokoro with `--tts-threads 2`, and Piper without generic warmup.
No benchmark command stops services, switches providers or deploys a model.

Trusted worker settings are `VASA_TTS_PROVIDER=kokoro-int8`,
`VASA_KOKORO_NUM_THREADS=1`, `VASA_STT_NUM_THREADS=1`. Piper can be selected
with `VASA_TTS_PROVIDER=piper`; `ljspeech` is rejected. The default Kokoro model
directory is `.local/speech/kokoro-int8`. Prepared Compose uses a two-CPU voice
limit and the existing read-only speech volume. Actual VPS activation remains
the operator's step.
