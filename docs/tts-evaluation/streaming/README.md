# Kokoro conversational latency on a two-CPU budget

**Kokoro is not yet a suitable default for the current VASA worker budget.**
In the isolated two-CPU evaluation, official CPU inference improved some
generation throughput but did not meet the proposed one-second conversational
first-playable target for complete sentences. Sentence chunking greatly reduces
the wait for long responses, but all Kokoro variants showed playback starvation
between sentences. Official Torch inference also needs more memory than the
current 1 GiB deployment-worker limit.

This is an actual cloud measurement with two-core affinity and a two-core
cgroup quota, not a measurement on the VPS itself. No model was deployed,
production provider was changed, or WhatsApp media code was modified.

## Measured conversational timing

Three repeats per text, policy and mode. Tables below use sentence-boundary
chunking, two native threads per model and a preloaded model/voice. P95 uses
linear interpolation; three repeats give only a coarse percentile estimate.
RTF is generation wall time divided by emitted audio duration.

| Candidate, TTS alone | Short phrase P95 | Complete sentence P95 | Long response first chunk P95 | Long-response median RTF | Worst long-response starvation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Official v1.0 Heart | 0.833 s | 1.703 s | 1.168 s | 0.393 | 0.228 s |
| Official v1.1 Maple | 0.852 s | 1.824 s | 1.414 s | 0.451 | 0.182 s |
| Sherpa v1.1 FP32 Maple | 0.933 s | 1.729 s | 1.097 s | 0.527 | 0.499 s |
| Piper LibriTTS-R speaker 0 | 0.071 s | 0.187 s | 0.132 s | 0.071 | 0.000 s |

| Candidate with concurrent paced STT | Short phrase P95 | Complete sentence P95 | Long response first chunk P95 | Long-response median RTF | Worst long-response starvation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Official v1.0 Heart | 1.041 s | 2.074 s | 1.703 s | 0.531 | 1.045 s |
| Official v1.1 Maple | 1.138 s | 2.313 s | 1.948 s | 0.506 | 0.625 s |
| Sherpa v1.1 FP32 Maple | 1.119 s | 2.321 s | 1.291 s | 0.618 | 0.796 s |
| Piper LibriTTS-R speaker 0 | 0.156 s | 0.228 s | 0.173 s | 0.087 | 0.000 s |

For official v1.0, a whole long response took a median 9.146 seconds to first
playable audio when running alone. Sentence segmentation reduced this to a
median 1.045 seconds. That improvement does not eliminate the later gap before
a longer following sentence. Average RTF below one is insufficient to guarantee
continuous playback: a short first sentence can end before the next sentence
finishes generating.

The official generator emits audio after complete segment synthesis, not while
the vocoder is generating its samples. First playable here means a valid 60 ms
PCM16 frame is available to VASA's async speech contract, including resampling
and frame padding. It can contain leading silence. It excludes LLM token
arrival, VAD endpointing, network transport and caller playback.

## Resources and thread experiment

The same legacy benchmark text was also rerun on two CPUs: "Hello. Your
appointment is confirmed for tomorrow morning." Sherpa whole-buffer first
playable P95 was **2.231 seconds**, close to the earlier **2.225 seconds**.
Splitting after "Hello." reduced first playable P95 to **0.652 seconds**, but
created **0.589–0.827 seconds** of simulated starvation before the appointment
sentence. The fast first greeting therefore does not establish smooth response
delivery. These six reruns and WAVs are in `legacy-comparison/`; they reuse the
same v1.1 Maple model. Earlier measurements allowed a different CPU affinity
and did not report 16 kHz frame availability or starvation.

| Candidate | Peak RSS, solo | Peak RSS, STT + TTS |
| --- | ---: | ---: |
| Official v1.0 | 1,979.8 MiB | 2,149.6 MiB |
| Official v1.1 | 1,884.4 MiB | 1,850.9 MiB |
| Sherpa v1.1 FP32 | 773.8 MiB | 841.4 MiB |
| Piper | 367.3 MiB | 433.1 MiB |

Each process is fresh, so the solo and contention peaks may vary with allocator
behavior; subtracting them does not estimate STT memory. Peak includes model
loading and inference. Every response and chunk records process CPU seconds;
CPU time in contention includes both STT and TTS. Low Piper response duration
means much less total CPU work despite its brief native inference burst using
nearly both cores.

Measured median process CPU seconds per response under the two-thread STT load:

| Candidate | Short phrase | Complete sentence | Long, sentence-chunked response |
| --- | ---: | ---: | ---: |
| Official v1.0 | 1.806 | 3.612 | 16.826 |
| Official v1.1 | 1.955 | 3.964 | 15.906 |
| Sherpa v1.1 FP32 | 1.961 | 4.325 | 15.830 |
| Piper | 0.151 | 0.414 | 1.882 |

Reducing both STT and TTS to one native thread made official Kokoro slower:

| One thread per model, STT active | Short P95 | Sentence P95 | Long first-chunk P95 | Long median RTF | Worst long starvation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Official v1.0 | 1.412 s | 3.399 s | 1.962 s | 0.712 | 2.033 s |
| Official v1.1 | 1.677 s | 3.059 s | 2.013 s | 0.681 | 1.434 s |

The tested one-thread configuration therefore does not solve responsiveness or
continuity. Official memory peaks remain above the current worker budget.

## Continuity, pronunciation and naturalness

The harness preserves sentence punctuation and does not add crossfades or
silence trimming to improve results artificially. It reports each chunk's
completion time, generation time and duration. Boundary sample-step and RMS
measurements are in the raw reports. Padding means a zero sample step does not
prove fluent prosody; the separate scheduling-gap measurement catches the
observed starvation. Files ending in `-playback.wav` include those gaps so they
can be heard in a local listening comparison.

Sherpa Kokoro logged skipped-phoneme warnings for Unicode U+0329 and U+025A;
the exact distinct warnings are preserved in `runtime-warnings.txt`. These
require pronunciation review before any release. The official v1.1 card says
its English voices used synthetic training data and it is not a strict upgrade
over v1.0. Official v1.0 Heart and v1.1 Maple are different model/voice pairs;
only v1.1 Maple versus sherpa Maple is a matching implementation comparison.

No human naturalness scores have been recorded. Use `listen.html` locally to
compare the acknowledgment, appointment sentence and longer response, with
and without STT. Rate intelligibility, naturalness, pace, sentence endings and
audible pauses. A faster voice is not automatically a more natural voice.

## Implementation recommendation

1. Keep production on the existing provider. Piper is the strongest measured
   candidate for a conversational listening trial on the current CPU budget;
   selection still depends on naturalness, pronunciation and voice licensing.
2. Do not switch to official Kokoro in the current 1 GiB worker. It has a
   substantial Torch/Misaki/spaCy dependency and memory footprint, plus roughly
   two-second full-sentence first audio under the measured STT contention.
3. If a Kokoro voice is preferred after listening, evaluate it on a separately
   budgeted worker with sufficient RAM and measure the actual VPS. Preload the
   model and voice, use explicit CPU selection and reuse one model. No
   per-call model load or network download belongs in the call path.
4. Build complete short clauses from arriving LLM text rather than sending a
   whole paragraph. Preserve punctuation and a minimum meaningful phrase;
   arbitrary tiny fragments can damage prosody. Generate the following chunk
   ahead of playback with a bounded queue. Test buffering against each chunk's
   deadline, not only aggregate RTF, and include the extra buffer delay in first
   playable latency.
5. Only pursue a production integration after audible review, cancellation
   checks, actual VPS measurements and real-call acceptance. This study does
   not promise ten-call capacity or end-to-end phone latency.

See `measurements.json` and individual candidate/mode JSON files for all 144
primary responses, the `one-thread/` directory for 18 supplementary responses,
and `legacy-comparison/` for six responses using the previous benchmark text.
Individual `-chunk-*.wav` files and `chunk-samples.json` preserve chunk audio
and timing; `summary.json` provides aggregates. See
`artifacts.json` for hashes, `RESEARCH.md` for pinned source findings and
`REPRODUCE.md` for commands. The earlier evaluation remains intact in the
parent directory.
