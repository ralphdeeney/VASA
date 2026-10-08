# Voice intelligence and conversation worker

Gate 3 passed on the user's real-call report: 98 inbound frames, 20 diagnostic
frames and three tones heard. The pinned Evolution transport is unchanged.

CPU speech uses native WebRTC VAD, streaming Zipformer ONNX recognition and
LJSpeech/Piper ONNX synthesis. Speech models are initialized once per worker;
utterance state is isolated. Inference runs off the event loop, with bounded
admission and cancellation ownership. TTS produces mono PCM16 16 kHz, 60 ms
frames. Model preparation verifies pinned hashes and retains source/model cards.
The bundled espeak-ng phonemizer data retains its upstream license; review the
retained notices when distributing the dependency package.

```bash
bash scripts/setup.sh
uv run --frozen python scripts/prepare_speech.py --verify-only
bash scripts/check.sh
uv run --frozen python scripts/benchmark_speech.py
```

Configure `VASA_OPENAI_API_KEY` securely through cloud environment settings.
OpenAI is the selected primary provider; `VASA_LLM_PRIMARY=openai` is the default.
Never paste credentials in chat, CLI arguments or versioned files. A credential
shared in chat should be revoked and replaced. Optional Anthropic failover occurs
only before any provider output; responses never mix providers after output.

For the already paired instance, use its VASA UUID and trusted user's email:

```bash
uv run --frozen python -m vasa.voice_worker \
  --email owner@example.com --instance INSTANCE_UUID
```

The worker resolves tenant ownership in PostgreSQL before any call operation,
requires verified models and a provider key, checks actual pairing, and answers
incoming events through the existing adapter. It runs at most two active calls
per worker, with shared models. This admission limit is not a measured concurrency
claim. `--once` handles one call. `--greeting` and `--instructions PATH` load
trusted operator configuration until the planned agent configuration wave.
Instructions must be a bounded UTF-8 file; never load caller-controlled prompts.

The runtime retains 480 ms of rolling capture before voiced onset, preserving
quiet initial words; classifier segment pre-roll remains 120 ms. A concurrent
reader feeds streaming STT while response generation and paced
speech run independently. VAD endpointing finalizes the transcript, followed by
LLM text, local TTS and media output. New speech invalidates the previous response
generation and cancels pending LLM/TTS work. No late generation may send frames.
Local queued output is discarded. Evolution exposes no remote queue-clear or
playback acknowledgment: audio already accepted upstream cannot be withdrawn,
and frame transmission does not prove the caller heard that response.

Worker output includes only session UUID, counts, local timing and fixed error
codes. Caller identifiers, transcript, instructions and keys are excluded; no
caller audio is stored. Hangup and Redis cleanup are attempted independently and
cleanup failures are reported. Full transcript persistence and tools remain their
planned later waves; unexpected tool output fails closed.

## Persistent rootless deployment

`deploy/up.sh` prepares verified speech models automatically inside the VASA
private volume. Weights are not embedded in the application image. The database,
Evolution activation and speech cache volumes must be preserved.

Place production provider bindings in `/opt/vasa/.local/llm.env` using a private
editor, owned by `vasa-builder` and mode 0600. Use actual deployment credentials,
not proxy placeholders copied from the cloud. Compose reads this optional file
without overwriting stable service credentials in `.local/vps.env`:

```text
VASA_OPENAI_API_KEY=<private replacement value>
VASA_LLM_PRIMARY=openai
```

After adding the file, recreate only the dedicated VASA service, then run the
worker inside that service. The trusted client and mapping must exist in this
persistent database; cloud database UUIDs are not automatically transferred.

```bash
cd /opt/vasa
chmod 600 .local/llm.env
docker compose --env-file .local/vps.env -f deploy/compose.yaml up -d --no-deps vasa
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec vasa \
  python -m vasa.voice_worker --email owner@example.com --instance INSTANCE_UUID
```

This foreground command can be supervised by the existing rootless operator;
closing it ends worker activity and cleans up active calls. It does not change
unrelated host services. Follow VPS_DEPLOYMENT.md for deployment and activation.

Native accuracy/component evals establish local speech and orchestration
behavior. They do not establish live OpenAI instruction following, real AI-call
naturalness, audible barge-in recovery, end-to-end latency or ten-call capacity.
