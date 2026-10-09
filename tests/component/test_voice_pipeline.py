"""Actual CPU VAD/STT/TTS over the verified local WS adapter; LLM is scripted."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from websockets.asyncio.server import ServerConnection, serve

from vasa.contracts.models import AudioFrame, CallState, TenantContext
from vasa.evolution import EvolutionCalls
from vasa.runtime import ConversationRuntime, RuntimeConfig
from vasa.speech import KokoroInt8TTS, SherpaSTT, SpeechModels
from vasa.speech.models import FIXTURE_FILES
from vasa.speech.vad import StreamingVAD


class ScriptedAcknowledgement:
    def __init__(self) -> None:
        self.calls: list[tuple[TenantContext, list[dict[str, str]]]] = []

    async def respond(
        self, context: TenantContext, messages: list[dict[str, str]]
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append((context, [dict(message) for message in messages]))
        yield {"type": "text", "text": "I heard you."}


def first_real_utterance(models: SpeechModels) -> list[bytes]:
    path = models.fixture_dir / "0.wav"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_FILES["0.wav"]
    with wave.open(str(path), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        pcm = audio.readframes(audio.getnframes())
    pcm += b"\0" * (-len(pcm) % 1920)
    frames: list[bytes] = []
    detector = StreamingVAD()
    # Select one actual native-ended utterance, not unrelated later speech/noise in the clip.
    for sequence, offset in enumerate(range(0, len(pcm), 1920)):
        chunk = pcm[offset : offset + 1920]
        frames.append(chunk)
        if detector.process(AudioFrame(chunk, 16000, sequence, 0)).ended:
            return frames + [b"\0" * 1920] * 20
    pytest.fail("Pinned native speech fixture did not contain a completed utterance", pytrace=False)


def word_error_rate(reference: str, recognized: str) -> float:
    expected, actual = reference.lower().split(), recognized.lower().split()
    row = list(range(len(actual) + 1))
    for index, word in enumerate(expected, 1):
        updated = [index]
        for position, candidate in enumerate(actual, 1):
            updated.append(
                min(row[position] + 1, updated[-1] + 1, row[position - 1] + (word != candidate))
            )
        row = updated
    return row[-1] / len(expected)


@pytest.mark.speech_native
async def test_actual_native_speech_pipeline_returns_generated_audio_through_local_ws() -> None:
    models = SpeechModels(Path(os.environ.get("VASA_SPEECH_MODEL_ROOT", ".local/speech")))
    await asyncio.to_thread(models.verify)
    inbound = first_real_utterance(models)
    stt = await asyncio.to_thread(SherpaSTT, models.stt_dir, num_threads=1)
    tts = await asyncio.to_thread(KokoroInt8TTS, models.kokoro_dir, num_threads=1)
    llm = ScriptedAcknowledgement()
    context = TenantContext(uuid4(), uuid4())
    completed = asyncio.Event()
    speaking = False
    outbound: list[bytes] = []

    async def state(value: CallState) -> None:
        nonlocal speaking
        if value == CallState.SPEAKING:
            speaking = True
        elif value == CallState.LISTENING and speaking:
            completed.set()

    async def upstream(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"event": "start", "callId": "native-call", "sampleRate": 16000}))

        async def collect() -> None:
            async for raw in ws:
                message = json.loads(raw)
                assert message["event"] == "media" and message["track"] == "outbound"
                outbound.append(base64.b64decode(message["payload"], validate=True))

        collector = asyncio.create_task(collect())
        try:
            for pcm in inbound:
                await ws.send(
                    json.dumps(
                        {
                            "event": "media",
                            "track": "inbound",
                            "payload": base64.b64encode(pcm).decode(),
                        }
                    )
                )
                await asyncio.sleep(0.06)
            await asyncio.wait_for(completed.wait(), 15)
            await ws.send(json.dumps({"event": "stop", "reason": "component_complete"}))
            await ws.wait_closed()
        finally:
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)

    silent_logger = logging.Logger("test.native-pipeline-no-auth-logging")
    silent_logger.disabled = True
    try:
        runtime = ConversationRuntime(
            stt,
            tts,
            llm,
            config=RuntimeConfig(greeting="", max_call_seconds=30, max_turns=2),
        )
        async with serve(upstream, "127.0.0.1", 0, logger=silent_logger) as server:
            port = server.sockets[0].getsockname()[1]
            client = EvolutionCalls(f"http://127.0.0.1:{port}", "a" * 32, "s" * 32, "i" * 32)
            try:
                async with client.open_media("native-instance", "native-call") as media:
                    async with asyncio.timeout(35):
                        result = await runtime.run(context, media, on_state=state)
            finally:
                await client.aclose()
        assert result.error is None
        assert result.received_frames == len(inbound)
        assert result.completed_turns == 1 and result.sent_frames == len(outbound) > 1
        assert all(len(pcm) == 1920 for pcm in outbound)
        assert any(pcm != b"\0" * 1920 for pcm in outbound)
        assert len(llm.calls) == 1 and llm.calls[0][0] == context
        recognized = llm.calls[0][1][-1]
        assert recognized["role"] == "user"
        assert {"after", "nightfall", "lamps"} <= set(recognized["content"].lower().split())
        reference = (models.fixture_dir / "trans.txt").read_text().splitlines()[0].split(" ", 1)[1]
        wer = word_error_rate(reference, recognized["content"])
        assert wer <= 0.15, "native segmented pipeline must preserve the published accuracy bound"
        assert result.messages[-1] == {"role": "assistant", "content": "I heard you."}
        assert result.state_transitions[-1] == "ENDED"
        # This proves generated transport frames, not phone playback or live model reasoning.
        assert result.latencies_ms["stt_finalization"]
        assert result.latencies_ms["tts_time_to_first_audio"]
        print(
            json.dumps(
                {
                    "evidence": "actual_native_local_ws_scripted_llm",
                    "fixture_wer": wer,
                    "received_frames": result.received_frames,
                    "sent_frames": result.sent_frames,
                    "local_latencies_ms": result.latencies_ms,
                },
                sort_keys=True,
            )
        )
    finally:
        await stt.aclose()
        await tts.aclose()
