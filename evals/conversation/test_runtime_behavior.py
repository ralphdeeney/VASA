"""Scripted-provider behavioral component evals, not live model reasoning evidence."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from vasa.contracts.models import AudioFrame, CallState, TenantContext
from vasa.runtime import ConversationRuntime, RuntimeConfig
from vasa.speech.vad import StreamingVAD, VadResult

pytestmark = pytest.mark.eval


class ControlledVAD(StreamingVAD):
    def __init__(self) -> None:
        self.active = False

    def process(self, frame: AudioFrame) -> VadResult:
        speech = frame.pcm[0] != 0
        if speech and not self.active:
            self.active = True
            return VadResult(started=True, speech=True)
        if not speech and self.active:
            self.active = False
            return VadResult(ended=True, segment=[])
        return VadResult(speech=speech)

    def finish(self) -> None:
        self.active = False


class Media:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[AudioFrame | None] = asyncio.Queue()
        self.sent: list[AudioFrame] = []
        self.first_audio = asyncio.Event()
        self.completed: asyncio.Queue[int] = asyncio.Queue()
        self.speaking = False

    async def receive(self) -> AudioFrame | None:
        return await self.incoming.get()

    async def send(self, frame: AudioFrame) -> None:
        self.sent.append(frame)
        self.first_audio.set()

    async def close(self) -> None:
        pass

    async def state(self, state: CallState) -> None:
        if state == CallState.SPEAKING:
            self.speaking = True
        elif state == CallState.LISTENING and self.speaking:
            self.speaking = False
            await self.completed.put(self.sent[-1].pcm[0])

    async def turn(self, sequence: int) -> None:
        await self.incoming.put(AudioFrame(b"\1" * 1920, 16000, sequence, 0))
        await self.incoming.put(AudioFrame(b"\0" * 1920, 16000, sequence + 1, 0))


class Transcripts:
    def __init__(self, texts: list[str]) -> None:
        self.texts = deque(texts)

    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        async for _ in frames:
            yield "Temporary hypothesis"
        yield self.texts.popleft()


class Speech:
    def __init__(self, *, block_first: bool = False) -> None:
        self.texts: list[str] = []
        self.block_first = block_first
        self.cancelled = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        self.texts.append(text)
        marker = len(self.texts)
        try:
            yield AudioFrame(bytes([marker]) * 1920, 16000, 0, 0)
            if self.block_first and marker == 1:
                await asyncio.Event().wait()
        finally:
            if self.block_first and marker == 1:
                self.cancelled.set()


class ScriptedResponses:
    def __init__(self, responses: list[str]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[TenantContext, list[dict[str, str]]]] = []

    async def respond(
        self, context: TenantContext, messages: list[dict[str, str]]
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append((context, [dict(message) for message in messages]))
        # A provider mutating its received snapshot must not alter trusted future history.
        messages[0]["content"] = "mutated-provider-snapshot"
        yield {"type": "text", "text": self.responses.popleft()}


async def test_scripted_multiturn_eval_preserves_trusted_instructions_context_and_greeting() -> (
    None
):
    context = TenantContext(uuid4(), uuid4())
    prompt = "Acme: do not invent opening hours. Ask for the customer's name before booking."
    stt = Transcripts(["Book an appointment.", "My name is Ada."])
    tts = Speech()
    llm = ScriptedResponses(["What is your name?", "Thanks, Ada. What day works for you?"])
    media = Media()
    runtime = ConversationRuntime(
        stt,
        tts,
        llm,
        config=RuntimeConfig(system_prompt=prompt, greeting="Welcome to Acme.", max_call_seconds=3),
        vad_factory=ControlledVAD,
    )
    task = asyncio.create_task(runtime.run(context, media, on_state=media.state))
    try:
        await asyncio.wait_for(media.completed.get(), 1)
        for sequence in (0, 2):
            await media.turn(sequence)
            await asyncio.wait_for(media.completed.get(), 1)
        await media.incoming.put(None)
        result = await asyncio.wait_for(task, 1)
        assert result.error is None and result.completed_turns == 2
        assert tts.texts == [
            "Welcome to Acme.",
            "What is your name?",
            "Thanks, Ada.",
            "What day works for you?",
        ]
        assert len(llm.calls) == 2 and all(tenant == context for tenant, _ in llm.calls)
        for _, messages in llm.calls:
            assert messages[0] == {"role": "system", "content": prompt}
            assert messages[1]["role"] == "user" and messages[-1]["role"] == "user"
            assert "Welcome to Acme." not in [item["content"] for item in messages]
        second = llm.calls[1][1]
        assert {"role": "user", "content": "Book an appointment."} in second
        assert {"role": "assistant", "content": "What is your name?"} in second
        assert second[-1] == {"role": "user", "content": "My name is Ada."}
        assert "Temporary hypothesis" not in str(result.messages)
        assert result.messages[0]["content"] == prompt
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_scripted_interruption_eval_recovers_context_and_drops_future_old_audio() -> None:
    context = TenantContext(uuid4(), uuid4())
    stt = Transcripts(["Make it today.", "Actually, make it tomorrow."])
    tts = Speech(block_first=True)
    llm = ScriptedResponses(["The original response.", "Tomorrow requires confirmation."])
    media = Media()
    runtime = ConversationRuntime(
        stt,
        tts,
        llm,
        config=RuntimeConfig(greeting="", max_call_seconds=3),
        vad_factory=ControlledVAD,
    )
    task = asyncio.create_task(runtime.run(context, media, on_state=media.state))
    try:
        await media.turn(0)
        await asyncio.wait_for(media.first_audio.wait(), 1)
        await media.turn(2)
        await asyncio.wait_for(tts.cancelled.wait(), 1)
        async with asyncio.timeout(1):
            while await media.completed.get() != 2:
                pass
        await media.incoming.put(None)
        result = await asyncio.wait_for(task, 1)
        assert result.error is None and result.interruptions == 1 and result.completed_turns == 1
        assert [frame.pcm[0] for frame in media.sent] == [1, 2]
        assert tts.texts == ["The original response.", "Tomorrow requires confirmation."]
        assert len(llm.calls) == 2
        history = llm.calls[1][1]
        assert {"role": "user", "content": "Make it today."} in history
        assert history[-1] == {"role": "user", "content": "Actually, make it tomorrow."}
        assert {"role": "assistant", "content": "The original response."} not in history
        assert result.messages[-1] == {
            "role": "assistant",
            "content": "Tomorrow requires confirmation.",
        }
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
