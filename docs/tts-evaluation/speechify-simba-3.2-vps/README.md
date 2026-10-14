# Speechify Simba 3.2 VPS evaluation

Integration is ready; **live VPS measurements and Speechify listening WAVs are
pending**. On 2026-10-12 SSH to `vasa-builder@2.25.172.155:22` returned
`Connection refused`, and `SPEECHIFY_API_KEY` is absent in the cloud process.
No live Speechify call, performance measurement or deployment is claimed.
Kokoro INT8 remains the default; Piper and Kitten remain available.

## Optional streaming provider

Trusted `VASA_TTS_PROVIDER=speechify` selects one worker-owned, shared HTTP
client. The key is read from `SPEECHIFY_API_KEY`; the voice is configured with
`VASA_SPEECHIFY_VOICE_ID` (default `geffen_32`). For Compose, use the existing
ignored `.local/llm.env` provider-key file. The benchmark reads its own exported
key and does not select a production provider.

Requests use `POST https://api.speechify.ai/v1/audio/stream`, model `simba-3.2`,
`output_format=pcm_16000`, `Accept: audio/pcm` and the fixed
`Speechify-Version: 2026-09-30`. The version fixes the documented older-workspace
24-kHz bytes mislabeled as 16-kHz issue. Validate the delivered mono rate and
encoding, then frame raw signed PCM16 little-endian at 16kHz/60ms/1920bytes.
No decoding/resampling or complete-response wait is required. Odd fragments
carry across reads; even final PCM is padded, and empty/odd completed PCM fails.
The official [endpoint](https://docs.speechify.ai/build/api-reference/v1/audio/stream),
[formats](https://docs.speechify.ai/build/guides/concepts/audio-formats) and
[versioning](https://docs.speechify.ai/build/guides/concepts/api-versioning)
define the pinned protocol, including Speechify's little-endian `audio/L16`.

The pool has one active connection, up to ten admitted/waiting streams, finite
request/body limits and five-second cleanup deadlines. Completed streams reuse
connections; aborts and server/proxy closures may require reconnects, which TCP/
TLS tracing records explicitly. Cancellation closes the active stream, rejects
late frames and drains cleanup under repeated cancellation/shutdown. No shared
generated-speech cache is added. TTSProvider, existing providers, bounded runtime
queues, generation guards and WhatsApp media transport are unchanged.

## Benchmark and metrics

`scripts/benchmark_speechify_vps.py` runs exactly two excluded whole-text warmup
requests, then 30 sequential varied logical responses **per mode** by default
(minimum20, maximum100). Categories are short acknowledgement, business sentence
and four-sentence response; every runtime HTTP clause varies. There are no hidden
retries. Direct mode drains streamed frames promptly. Buffered mode uses the
actual ConversationRuntime producer/player and natural chunking; long responses
make multiple sequential HTTP requests and save speech plus playback-gap WAVs.

Optional `--with-stt` runs real one-thread Sherpa STT with an idle-HTTP fixture
baseline before warmups and a contender during both modes/cancellation. Completed
fixture WER/deadlines and truncated cleanup runs are recorded separately. This
matches introduced native B/C contention; it is not simulated CPU work. Normal
container snapshots are read-only. No services or competing TTS are started.

Records include first response **body** byte, first full playable PCM frame,
complete HTTP duration, received/padded audio duration, bytes/status, numeric
Server-Timing/TTFB, connection starts, stalls, framing/conversion cost, CPU/RSS,
runtime completion, frame/chunk starvation and cancellation cleanup. Summaries
include global/category p50/p90/p95, failures and objective target observations.

- First playable includes leading silence; it does not establish speech onset
  or phone audibility. No network or WhatsApp playback acknowledgement is claimed.
- Server-Timing uses milliseconds. Missing TTFB stays null; negative residuals
  are flagged. First-playable minus server TTFB includes network, client and
  framing overhead, not isolated RTT. Descriptions/secrets are not serialized.
- Direct RTF is complete HTTP duration / unpadded received audio duration.
  Buffered HTTP RTF includes consumer backpressure; runtime provider-wait RTF
  and paced wall time are separate. These are not isolated native inference RTF.
- Raw stalls are read-wait/arrival observations. Arrival gaps may include consumer
  backpressure; direct simulated starvation accounts for queued audio, while
  buffered gaps are observed at runtime media sends.
- Native PCM conversion/resampling is zero; framing is measured. CPU includes
  benchmark capture/WAV writes and optional STT. RSS is this process, not the
  whole VPS/live worker; normal container measurements are separate.
- Thirty responses give ten samples/category: p90/p95 remain small-sample
  estimates. Failure stops with sanitized partial evidence and a nonzero exit.
- Cancellation probes are excluded from latency statistics. Valid completion
  requires active streams, correct phases, no late frames and successful cleanup.

## Comparison and decision

User-reported approximate actual VPS Kokoro context: sentence first audio~4.2s,
sentence RTF~1.32 and long starvation~4.28s. This is not independently verified
raw evidence. Actual VPS Piper records have not been supplied; cloud Piper
numbers are not relabeled as VPS. Optional baseline inputs accept only records
explicitly marked actual VPS. Native fixed texts differ from varied Speechify
texts, so category comparisons are contextual, not identical-text trials.
Match CPU affinity, STT contention, buffering and normal workload when comparing.

Prefer sentence first audio<500ms, p90<800ms, no multi-second starvation and
fast cancellation. Naturalness relative to Piper and acceptance of the external
API/network dependency require human/operator review. No default promotion or
production-readiness claim is made automatically.

[REPRODUCE.md](REPRODUCE.md) gives exact private-key, VPS, STT and comparison
commands. Root JSON files record an unrun benchmark with null metrics;
`verification.json` records local automated evidence separately. Real runs write
JSON/WAVs to `vps/` or a fresh output directory. WAV filenames are
`direct-NN-category.wav`, `buffered-NN-category.wav` and
`buffered-NN-category-playback.wav`. No mocked listening samples are shipped.
