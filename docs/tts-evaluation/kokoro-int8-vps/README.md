# Kokoro INT8 candidate: VPS run pending

> Historical baseline at commit `8ca9f9e`. The operator subsequently retired
> LJSpeech and made Kokoro the code default. See [the optimized implementation
> and current measurements](optimized/README.md). The measurements below remain
> their original cloud observations; no live VPS switch is implied.

Kokoro INT8 is integrated as an **optional** provider. Production remains on
LJSpeech Medium; the TTSProvider interface and WhatsApp transport are unchanged.
No production model was switched and no server deployment was performed.

The target `vasa-builder@2.25.172.155:22` returned `Connection refused` before
authentication. The operator confirmed this address and requested manual VPS
execution. Consequently, conditions A/B/C on the **actual VPS are unmeasured**.
Top-level JSON records explicitly retain pending status and null results.
Follow [REPRODUCE.md](REPRODUCE.md) to execute all six candidate/condition runs.

## Integration

- `VASA_TTS_PROVIDER=kokoro-int8` selects the separate provider; the default
  remains `ljspeech`. `VASA_KOKORO_NUM_THREADS` defaults to **1**.
- One checksum-verified native CPU model is initialized during worker setup,
  before calls are admitted. All instances share it. No model loading or
  downloads occur per request/call.
- Sentence-aware synthesis retains short acknowledgements and normal sentences
  intact. Long sentences may split into meaningful clauses, with a hard
  240-character generation limit. The existing runtime already sends completed
  LLM sentences incrementally; it does not require the entire response first.
- Output is mono PCM16 at 16 kHz, converted from Kokoro's native sample rate,
  padded into 60 ms/1920-byte frames. Native inference is off the event loop.
- A single native admission lane prevents executor backlog/shared-model races.
  At most ten admitted streams retain bounded segment audio (<=30 seconds
  each). The existing runtime has bounded capture/playback resources.
- Barge-in cancels the consumer immediately and discards future old output.
  Sherpa Kokoro's callback occurs after complete segment inference; CPU work
  **cannot** be immediately preempted. Its tracked cleanup retains admission
  until inference stops, so a replacement utterance may wait for that segment.
  Consumer cancellation and native drain are measured separately. There is no
  invented remote WhatsApp queue-flush operation.

## Benchmark interpretation

Each candidate/condition runs in a fresh child process. Each response reuses
that model. Cancellation trials close the measured model, then initialize one
separate trial instance at a time. No competing TTS models run simultaneously.

The texts are identical to the previous streaming evaluation: a short
acknowledgement, an appointment sentence, and a four-sentence business response.
All text is available at time zero; no LLM/network latency is simulated.
Playback is actually paced at 60 ms locally. Chunk synthesis is sequential,
matching the current runtime, with no speculative prefetch.

`first_playable_seconds` ends at the first valid local frame, including any
leading acoustic silence. `synthesis_compute_seconds` sums awaited provider
work and excludes consumer playback sleeps. `paced_response_wall_seconds`
includes playback. RTF is compute/audio duration, not wall/playback duration.
Chunk-ready timing and frame/chunk starvation are recorded; playback WAVs
include measured post-start gaps, with no initial-wait silence.

CPU utilization is process CPU seconds divided by response wall time, with
100% representing one CPU. B/C CPU and RSS include STT in the same process;
they must not be described as isolated TTS consumption. Peak RSS is a lifetime
high-water mark. Sampled RSS gives a process timeline; additional before/after
RSS fields are emitted by the finalized harness. The first response is cold;
subsequent responses reuse warmed caches. OS file caches are not flushed.

B/C use actual paced native STT with its existing **two-thread** configuration.
An idle-TTS STT baseline and contended STT runs record complete-fixture WER,
consumer deadlines and wall times. Truncated cleanup records are excluded from
quality comparisons. One independent recording is limited evidence and cannot
certify general STT quality. C requires running normal containers and records
read-only snapshots; the operator must document the active application load.

Cloud smoke outputs live exclusively under `cloud-smoke/`. These use two-core
affinity and the cloud's quota, not the actual VPS. A single response per text
is a functional/performance warning, not a reliable P95 estimate. JSON percentile
fields collapse to that observation when there is only one sample.

## Observed cloud smoke results (not VPS)

One measurement per text, one TTS thread, affinity to two cores. The business
sentence results are:

| Candidate / condition | First playable | RTF | Response CPU seconds | Peak RSS at sentence |
|---|---:|---:|---:|---:|
| Kokoro INT8 alone | 4.181 s | 1.291 | 4.196 | 408.2 MiB |
| Kokoro INT8 + STT | 4.637 s | 1.432 | 7.484 | 488.6 MiB |
| Piper alone | 0.219 s | 0.091 | 0.233 | 237.9 MiB |
| Piper + STT | 0.270 s | 0.113 | 1.435 | 317.1 MiB |

Under STT, Kokoro acknowledgement/long-response first audio was 2.272/2.545 s,
versus Piper's 0.102/0.194 s. Long-response maximum chunk gaps were **5.857 s**
for Kokoro and **0.409 s** for Piper. The sequential paced policy causes gaps
even for Piper; it should not be described as gap-free in this test. Earlier
streaming measurements simulated generation ahead of playback and used two
native threads, so their numbers are not directly interchangeable.

Model initialization was 1.133–1.188 s for Kokoro versus 0.592–0.607 s for
Piper. Peak RSS reached 519.7 MiB for Kokoro + STT and 357.5 MiB for Piper + STT
by the long response. Three unique texts and a single pass do not establish
long-run memory stability. CPU values in the STT rows include background STT
throughout the different response durations; use the solo rows when assessing
TTS-only process CPU cost.

Kokoro consumer cancellation returned in **0.07–0.10 ms**, with zero later
frames. Before-first-audio native cleanup still took **2.577–3.011 s**. Piper
before-first-audio cancellation took **0.114–0.219 s** because the comparison
wrapper retains native work until completion; playback cancellation was about
0.09 ms. These are local coroutine timings, not audible phone barge-in timing.

Completed STT records retained the baseline **1/18 word errors** for both
candidates. Maximum frame deadline overrun rose from zero in each idle-TTS
baseline to **108 ms** with Kokoro, versus **11 ms** with Piper. This is a timing
warning despite unchanged fixture transcription, not a general accuracy claim.

Kokoro failed both the preferred <900 ms first-audio target and RTF <1 in these
cloud checks. The multi-second starvation and non-preemptible native cleanup
also argue against selecting it now. Actual VPS confirmation and human
naturalness review remain required.

Sentence samples:
[Kokoro + STT](cloud-smoke/kokoro-int8-B/kokoro-int8-B-sentence-0.wav) and
[Piper + STT](cloud-smoke/piper-B/piper-B-sentence-0.wav).
Long-response playback samples include the actual measured gaps:
[Kokoro](cloud-smoke/kokoro-int8-B/kokoro-int8-B-long-0-playback.wav) and
[Piper](cloud-smoke/piper-B/piper-B-long-0-playback.wav).

## Model and licenses

Sherpa-ONNX/core **1.13.8**; Kokoro **v1.1-zh INT8**, speaker 0 **af_maple**,
US English. The pinned archive SHA256 is
`a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6`.
`model.int8.onnx` SHA256 is
`bda15858163726a492d02a9a727bc263551b86ac77f90812c4b30ff41d380e26`.
See `artifacts.json` for exact source URLs and auxiliary hashes. Individual
reports record every loaded model-tree file and installed dependency versions.

The Kokoro model/source and Sherpa runtime use Apache-2.0; bundled eSpeak
phonemizer components carry GPL obligations. Piper comparison uses the existing
LibriTTS-R Medium model, speaker 0, with stochastic noise disabled. Its model
and dataset attribution/license records remain in the parent evaluation.
See [the verified license review](../streaming/LICENSES.md) and retained model
cards before distributing model/dependency bundles.

Sherpa emitted existing unknown-phoneme warnings for U+0329 and U+025A during
Kokoro synthesis. They warrant pronunciation listening checks rather than
being silently treated as proof of intelligibility.

## Production recommendation

1. **Suitability on this VPS:** unknown until the operator runs A/B/C. Evaluate
   the preferred <900 ms first-audio target under B/C, RTF <1, starvation,
   stable memory, STT degradation and cancellation together.
2. **Latency, memory and CPU versus Piper:** use matched VPS runs. Cloud smoke
   and earlier Piper measurements are supporting evidence only.
3. **Voice-quality tradeoff:** no human listening score is recorded. Compare
   identical WAVs for naturalness, pronunciation, pacing and audible gaps;
   higher quality must demonstrably justify any added delay.
4. **Recommended production provider now:** keep the working LJSpeech default.
   Piper remains the strongest previously measured low-latency candidate for
   a listening trial. Do not select Kokoro merely because an aggregate RTF
   passes, or because consumer cancellation returns quickly.
