# Deepgram Aura 2 TTS integration

Code/configuration and key-free verification are complete. **Live Deepgram
validation, measured latency and listening WAVs are pending a securely supplied
`DEEPGRAM_API_KEY`.** No real key or live request is used by tests, and no
production provider/default has been changed. This covers Aura TTS only;
existing local speech recognition and WhatsApp transport remain unchanged.

## Provider and configuration

Trusted `VASA_TTS_PROVIDER=deepgram` selects a worker-shared `DeepgramTTS`;
`VASA_DEEPGRAM_MODEL` defaults to `aura-2-thalia-en`. The key is read from the
exact `DEEPGRAM_API_KEY` environment name, stored as a secret, and required
before remote worker activity. Private Compose keys can use the existing ignored
`.local/llm.env` provider-key file. Missing credentials prevent admission.
Kokoro INT8 stays default; Speechify, Kitten and Piper remain selectable.

The adapter posts JSON text to `https://api.deepgram.com/v1/speak` with Token
authentication and explicit `model`, `encoding=linear16`, `sample_rate=16000`,
`container=none` parameters. It consumes streamed audio without waiting for
the full body. Native mono signed PCM16 little-endian output is framed at
16kHz/60ms/1920bytes without resampling. Container/format/rate errors and odd
completed PCM are rejected; partial even PCM is padded to a final frame.
See the official [REST endpoint](https://developers.deepgram.com/reference/text-to-speech/speak-request),
[encoding](https://developers.deepgram.com/docs/tts-encoding),
[container](https://developers.deepgram.com/docs/tts-container) and
[streamed REST output](https://developers.deepgram.com/docs/streaming-the-audio-output) contracts.
This implements streaming REST audio, not the separate text-input WebSocket API.

Narrow protocol hooks reuse the existing tested pooled HTTP/PCM implementation.
One client/connection pool is shared across requests; admission, audio size,
deadlines and cleanup remain bounded. Barge-in closes/cancels the active stream,
and repeated cancellation/shutdown drains cleanup while discarding obsolete
audio. Completed requests reuse connections; aborted streams or server closures
can require reconnects, which TCP/TLS tracing records. No generated/customer/
tenant speech is retained in a shared cache.

Only bounded safe model/request metadata is retained. Requested model and
optional server model/UUID/request-id fields are distinct; absent server metadata
stays null and a reported model mismatch is rejected. The model alias is not a
locally pinned immutable weight artifact. Auth headers, error bodies, trace
details and real credentials are not printed or serialized.

## Tooling and verification

`scripts/benchmark_deepgram_vps.py` reuses the sequential direct/runtime-buffered
benchmark harness through a trusted provider profile. Defaults are two excluded
whole-text warmup requests and 30 varied logical responses per mode (minimum20).
Short acknowledgements, business sentences and four-sentence responses/clauses
vary. Requests remain sequential; no hidden retries or speech cache is used.

Direct mode measures prompt streaming delivery; buffered mode uses the actual
call runtime's natural chunking, bounded producer/player and60ms pacing. Optional
`--with-stt` runs real existing one-thread Sherpa STT with an idle-HTTP fixture
baseline and contender, not a Deepgram STT provider. It records completed fixture
WER/deadlines separately from truncated cleanup runs.

Records include body-first-byte and complete playable-frame latency, global/
category p50/p90/p95, HTTP completion, received/audio duration, RTF, bytes/status,
optional numeric Server-Timing/TTFB residuals, TCP/TLS starts, stalls/starvation,
framing/conversion cost, CPU/RSS and cancellation/cleanup. Real runs save speech
WAVs and buffered playback WAVs with measured gaps. Only actual-VPS native
baseline records are accepted; historical fixed versus varied texts remain
contextual comparisons rather than identical-text trials.

First playable includes leading silence and is not phone playback acknowledgement.
Buffered HTTP time includes backpressure; direct HTTP RTF is not isolated native
inference RTF. CPU includes benchmark capture/WAV writes and optional STT; process
RSS excludes other containers. Missing server TTFB stays null; any subtraction
is a network/client/framing estimate, not isolated RTT. Thirty responses give
ten samples/category, so tail estimates remain small-sample observations.

Mocks/stubs and real loopback TCP checks cover credentials/query/model handling,
frame delivery before EOF, persistent connection reuse, format validation,
secret-safe metadata/errors, cancellation/cleanup and worker sharing. Full
verification is recorded in `verification.json`; mocks are not live API evidence.
Root measurements/summary/environment receipts explicitly remain pending.

## Live gate

Set **`DEEPGRAM_API_KEY`** in secure cloud environment secret settings and
save/publish it; never paste it into chat or put it in a tracked file. Work stops
at this gate as requested. After the key is available, authentication/model/
stream validation and live measurements can run. Actual VPS measurements still
require its operator-owned execution; previously refused SSH is not treated as
successful access. No listening preference or production readiness is inferred.

[REPRODUCE.md](REPRODUCE.md) supplies exact private-key/VPS/STT/native comparison
commands. A cloud validation run must use `--scope component-smoke` and a
`component-smoke/` output folder, never claim actual VPS results. A new output
directory preserves each run. No benchmark promotes a default automatically.
