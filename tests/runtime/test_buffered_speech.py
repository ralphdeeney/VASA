"""Bounded synthesis/playback overlap checks, without claiming live transport latency."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from vasa.contracts.models import AudioFrame, TenantContext
from vasa.runtime import ConversationRuntime, RuntimeConfig
from vasa.runtime.conversation import _chunks, _Session


class IdleSTT:
    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        async for _ in frames:
            pass
        yield "A request"


class TextLLM:
    def __init__(self) -> None:
        self.completed = asyncio.Event()

    async def respond(
        self, context: TenantContext, messages: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "text", "text": "Your appointment is confirmed. "}
        yield {"type": "text", "text": "Please arrive ten minutes early."}
        self.completed.set()


class TimedTTS:
    def __init__(self, frames: int = 8) -> None:
        self.frames = frames
        self.started: list[float] = []
        self.generated = 0
        self.stopped = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        self.started.append(time.monotonic())
        try:
            if len(self.started) > 1:
                await asyncio.sleep(0.12)
            for index in range(self.frames):
                self.generated += 1
                yield AudioFrame(b"\x01\x00" * 960, 16000, index, 0)
        finally:
            self.stopped.set()


class RecordingMedia:
    def __init__(self, *, block: bool = False) -> None:
        self.times: list[float] = []
        self.frames: list[AudioFrame] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def receive(self) -> AudioFrame | None:
        return None

    async def send(self, frame: AudioFrame) -> None:
        self.entered.set()
        await self.release.wait()
        self.times.append(time.monotonic())
        self.frames.append(frame)

    async def close(self) -> None:
        pass


def session(tts: TimedTTS, media: RecordingMedia, llm: TextLLM | None = None) -> _Session:
    runtime = ConversationRuntime(
        IdleSTT(), tts, llm or TextLLM(), config=RuntimeConfig(greeting="")
    )
    return _Session(runtime, TenantContext(uuid4(), uuid4()), media, None)


async def test_next_chunk_synthesis_overlaps_prior_playback_and_llm_reads_ahead() -> None:
    tts, media, llm = TimedTTS(), RecordingMedia(), TextLLM()
    call = session(tts, media, llm)

    async def transcribed() -> str:
        return "Please confirm my appointment"

    task = asyncio.create_task(call.respond(0, asyncio.create_task(transcribed())))
    await asyncio.wait_for(llm.completed.wait(), 1)
    # Receiving the following LLM delta no longer waits for eight paced audio frames.
    assert len(media.frames) < 8
    await asyncio.wait_for(task, 2)
    assert tts.started[1] < media.times[7]
    assert len(media.frames) == 16
    assert media.times[8] - media.times[7] < 0.11
    assert [frame.sequence for frame in media.frames] == list(range(16))
    assert call.result.messages[-1]["content"] == (
        "Your appointment is confirmed. Please arrive ten minutes early."
    )


async def test_slow_transport_backpressures_synthesis_and_cancel_discards_future_audio() -> None:
    tts, media = TimedTTS(1000), RecordingMedia(block=True)
    call = session(tts, media)
    task = asyncio.create_task(call.speak("A bounded response.", 0, None))
    await asyncio.wait_for(media.entered.wait(), 1)
    await asyncio.sleep(0.02)
    # At most 16 queued frames, one held by playback and one waiting in the producer.
    assert 1 < tts.generated <= 18
    call.generation += 1
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert time.monotonic() - started < 0.2
    assert tts.stopped.is_set()
    generated = tts.generated
    media.release.set()
    await asyncio.sleep(0.02)
    assert not media.frames and tts.generated == generated
    assert not [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "vasa-conversation" and not task.done()
    ]


def test_chunking_prefers_natural_clauses_and_preserves_normal_sentences() -> None:
    normal = "Your appointment is confirmed for tomorrow morning at ten o'clock."
    assert _chunks(normal) == ([normal], "")
    text = "Once we confirm your appointment, our team will send the details."
    assert _chunks(text) == (
        ["Once we confirm your appointment,", "our team will send the details."],
        "",
    )
    assert _chunks("Yes, I can help") == ([], "Yes, I can help")
    long = "Please consider " + "the available appointments " * 20
    chunks, tail = _chunks(long, final=True)
    assert not tail and all(len(chunk) <= 120 for chunk in chunks)
    assert " ".join(chunks).split() == long.split()
