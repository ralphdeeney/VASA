"""Component orchestration checks with scripted providers, never live LLM evidence."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from vasa.contracts.models import AudioFrame, CallState, TenantContext
from vasa.runtime import ConversationError, ConversationRuntime, RuntimeConfig
from vasa.runtime.conversation import _chunks, _Session
from vasa.speech.vad import StreamingVAD, VadResult


def frame(sequence: int, *, voiced: bool = True) -> AudioFrame:
    return AudioFrame(bytes([1 if voiced else 0]) * 1920, 16000, sequence, 0)


def context() -> TenantContext:
    return TenantContext(uuid4(), uuid4())


class ScriptVAD(StreamingVAD):
    def __init__(self) -> None:
        self.active = False

    def process(self, audio: AudioFrame) -> VadResult:
        speech = audio.pcm[0] != 0
        if speech and not self.active:
            self.active = True
            return VadResult(started=True, speech=True)
        if not speech and self.active:
            self.active = False
            return VadResult(ended=True, segment=[])
        return VadResult(speech=speech)

    def finish(self) -> list[AudioFrame] | None:
        self.active = False
        return None


class Media:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[AudioFrame | None] = asyncio.Queue()
        self.sent: list[AudioFrame] = []
        self.send_times: list[float] = []
        self.updated = asyncio.Condition()
        self.closed = False

    async def receive(self) -> AudioFrame | None:
        return await self.incoming.get()

    async def send(self, audio: AudioFrame) -> None:
        self.sent.append(audio)
        self.send_times.append(time.monotonic())
        async with self.updated:
            self.updated.notify_all()

    async def close(self) -> None:
        self.closed = True

    async def wait_sent(self, count: int) -> None:
        async with asyncio.timeout(2), self.updated:
            await self.updated.wait_for(lambda: len(self.sent) >= count)

    async def turn(self, sequence: int = 0) -> None:
        await self.incoming.put(frame(sequence))
        await self.incoming.put(frame(sequence + 1, voiced=False))


class STT:
    def __init__(self, text: str = "What are your opening hours?") -> None:
        self.text = text
        self.sequences: list[list[int]] = []
        self.started = asyncio.Event()
        self.consumed = asyncio.Event()

    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        current: list[int] = []
        self.sequences.append(current)
        self.started.set()
        async for audio in frames:
            current.append(audio.sequence)
            self.consumed.set()
            yield "A partial hypothesis"
        yield self.text


class TTS:
    def __init__(self, frames_per_chunk: int = 1) -> None:
        self.texts: list[str] = []
        self.frames_per_chunk = frames_per_chunk
        self.started = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        self.texts.append(text)
        self.started.set()
        for index in range(self.frames_per_chunk):
            yield frame(index)


class LLM:
    def __init__(self, text: str = "We open at nine. Please check with the business.") -> None:
        self.text = text
        self.calls: list[tuple[TenantContext, list[dict[str, str]]]] = []
        self.finished = asyncio.Event()

    async def respond(
        self,
        tenant: TenantContext,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append((tenant, messages))
        yield {"type": "text", "text": self.text}
        self.finished.set()


def runtime(stt: STT, tts: TTS, llm: LLM, **config: Any) -> ConversationRuntime:
    return ConversationRuntime(
        stt,
        tts,
        llm,
        config=RuntimeConfig(greeting="", **config),
        vad_factory=ScriptVAD,
    )


async def no_runtime_tasks() -> None:
    await asyncio.sleep(0)
    assert not [
        task
        for task in asyncio.all_tasks()
        if task.get_name() == "vasa-conversation" and not task.done()
    ]


async def test_streams_stt_before_endpoint_and_uses_final_cumulative_text() -> None:
    media, stt, tts, llm = Media(), STT(), TTS(), LLM()
    states: list[CallState] = []
    completed = asyncio.Event()

    async def state(value: CallState) -> None:
        states.append(value)
        if value == CallState.LISTENING and len(media.sent) >= 2:
            completed.set()

    worker = asyncio.create_task(runtime(stt, tts, llm).run(context(), media, on_state=state))
    await media.incoming.put(frame(0, voiced=False))
    await media.incoming.put(frame(1, voiced=False))
    await media.incoming.put(frame(2))
    await asyncio.wait_for(stt.consumed.wait(), 1)
    assert stt.sequences == [[0, 1, 2]]
    assert not llm.calls
    await media.incoming.put(frame(3, voiced=False))
    await asyncio.wait_for(completed.wait(), 2)
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.error is None
    assert result.completed_turns == 1
    assert llm.calls[0][1][-1] == {"role": "user", "content": stt.text}
    assert [audio.sequence for audio in media.sent] == [0, 1]
    assert media.send_times[1] - media.send_times[0] >= 0.055
    assert all(len(text) <= 200 for text in tts.texts)
    assert CallState.TRANSCRIBING in states and CallState.THINKING in states
    assert CallState.SPEAKING in states and states[-1] == CallState.ENDED
    assert "end_of_speech_to_first_audio" in result.latencies_ms
    assert not media.closed
    await no_runtime_tasks()


class BlockLLM(LLM):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def respond(
        self,
        tenant: TenantContext,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        self.started.set()
        try:
            await self.release.wait()
            yield {"type": "text", "text": "Old response."}
        finally:
            self.cancelled.set()


class BlockTTS(TTS):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        self.started.set()
        try:
            await self.release.wait()
            yield frame(0)
        finally:
            self.cancelled.set()


@pytest.mark.parametrize("blocked", ["llm", "tts", "output"])
async def test_barge_in_cancels_thinking_synthesis_and_paced_output(blocked: str) -> None:
    media, stt = Media(), STT()
    llm = BlockLLM() if blocked == "llm" else LLM("A long response.")
    tts = BlockTTS() if blocked == "tts" else TTS(20)
    worker = asyncio.create_task(runtime(stt, tts, llm).run(context(), media))
    await media.turn()
    if isinstance(llm, BlockLLM):
        await asyncio.wait_for(llm.started.wait(), 1)
    elif isinstance(tts, BlockTTS):
        await asyncio.wait_for(tts.started.wait(), 1)
    else:
        await media.wait_sent(2)
    before = len(media.sent)
    await media.incoming.put(frame(10))
    # Reader must keep receiving while providers/output are blocked.
    await asyncio.sleep(0.03)
    assert len(stt.sequences) == 2
    if isinstance(llm, BlockLLM):
        await asyncio.wait_for(llm.cancelled.wait(), 1)
    if isinstance(tts, BlockTTS):
        await asyncio.wait_for(tts.cancelled.wait(), 1)
    await asyncio.sleep(0.08)
    assert len(media.sent) == before
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.interruptions == 1
    assert result.completed_turns == 0
    assert result.received_frames == 3
    assert not [message for message in result.messages if message["role"] == "assistant"]
    await no_runtime_tasks()


async def test_greeting_is_interruptible_and_not_a_completed_turn() -> None:
    media, stt, tts, llm = Media(), STT(), TTS(20), LLM()
    engine = ConversationRuntime(stt, tts, llm, vad_factory=ScriptVAD)
    worker = asyncio.create_task(engine.run(context(), media))
    await media.wait_sent(1)
    await media.incoming.put(frame(0))
    await asyncio.sleep(0.03)
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.interruptions == 1
    assert result.completed_turns == 0
    assert not llm.calls
    assert result.sent_frames == 1
    await no_runtime_tasks()


class StalledSTT(STT):
    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        self.started.set()
        await asyncio.Event().wait()
        yield "Never"


async def test_backpressure_is_explicit_and_cleans_all_tasks() -> None:
    media, stt = Media(), StalledSTT()
    worker = asyncio.create_task(
        runtime(stt, TTS(), LLM(), audio_queue_frames=3).run(context(), media)
    )
    await media.incoming.put(frame(0))
    await asyncio.wait_for(stt.started.wait(), 1)
    for sequence in range(1, 5):
        await media.incoming.put(frame(sequence))
    result = await asyncio.wait_for(worker, 2)
    assert result.error == "audio_backpressure"
    assert result.sent_frames == 0
    assert result.state_transitions[-3:] == ["ERROR", "ENDING", "ENDED"]
    await no_runtime_tasks()


class BrokenSTT(STT):
    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        async for _ in frames:
            yield "Unfinished partial"
            raise RuntimeError("secret provider body must stay private")


async def test_stt_partial_failure_does_not_generate_or_expose_provider_error() -> None:
    media, llm = Media(), LLM()
    worker = asyncio.create_task(runtime(BrokenSTT(), TTS(), llm).run(context(), media))
    await media.turn()
    result = await asyncio.wait_for(worker, 2)
    assert result.error == "stt_failed"
    assert not llm.calls and result.sent_frames == 0
    assert "secret" not in str(result)
    await no_runtime_tasks()


class ToolLLM(LLM):
    async def respond(
        self,
        tenant: TenantContext,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "tool_call", "name": "unsafe_tool", "arguments": {}}


async def test_tools_fail_closed() -> None:
    media = Media()
    worker = asyncio.create_task(runtime(STT(), TTS(), ToolLLM()).run(context(), media))
    await media.turn()
    result = await asyncio.wait_for(worker, 2)
    assert result.error == "tool_not_enabled"
    assert result.sent_frames == 0
    await no_runtime_tasks()


async def test_two_tenants_share_providers_without_sharing_history() -> None:
    first, second, llm = Media(), Media(), LLM("Done.")
    engine = runtime(STT("Private request"), TTS(), llm)
    tenants = [context(), context()]
    workers = [
        asyncio.create_task(engine.run(tenant, stream))
        for tenant, stream in zip(tenants, [first, second], strict=True)
    ]
    await asyncio.gather(first.turn(), second.turn())
    await asyncio.gather(first.wait_sent(1), second.wait_sent(1))
    await asyncio.sleep(0.02)
    await first.incoming.put(None)
    await second.incoming.put(None)
    results = await asyncio.gather(*workers)
    assert all(result.error is None and result.completed_turns == 1 for result in results)
    assert {call[0] for call in llm.calls} == set(tenants)
    assert llm.calls[0][1] is not llm.calls[1][1]
    llm.calls[0][1][-1]["content"] = "Tampered provider-owned snapshot"
    assert all(result.messages[1]["content"] == "Private request" for result in results)
    assert results[0].messages is not results[1].messages
    await no_runtime_tasks()


async def test_caller_cancellation_propagates_after_cleanup() -> None:
    media, llm = Media(), BlockLLM()
    worker = asyncio.create_task(runtime(STT(), TTS(), llm).run(context(), media))
    await media.turn()
    await asyncio.wait_for(llm.started.wait(), 1)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert llm.cancelled.is_set()
    assert not media.closed
    await no_runtime_tasks()


@pytest.mark.parametrize("kind", ["call", "stt", "llm", "tts"])
async def test_timeout_is_sanitized_and_releases_tasks(kind: str) -> None:
    media = Media()
    config = {f"{kind}_timeout_seconds": 0.02} if kind != "call" else {"max_call_seconds": 0.02}
    stt = StalledSTT() if kind == "stt" else STT()
    llm = BlockLLM() if kind == "llm" else LLM()
    tts = BlockTTS() if kind == "tts" else TTS()
    worker = asyncio.create_task(runtime(stt, tts, llm, **config).run(context(), media))
    if kind != "call":
        await media.turn()
    result = await asyncio.wait_for(worker, 2)
    assert result.error == f"{kind}_timeout"
    await no_runtime_tasks()


def test_sentence_and_long_word_chunks_have_hard_bounds() -> None:
    text = "First sentence. " + ("word " * 100) + ("x" * 650)
    chunks, tail = _chunks(text, final=True)
    assert tail == ""
    assert chunks[0] == "First sentence."
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_configuration_and_exception_codes_are_bounded() -> None:
    assert str(ConversationError("sensitive arbitrary exception")) == "invalid_response"
    for values in (
        {"audio_queue_frames": 0},
        {"max_response_chars": 2001},
        {"max_history_messages": 2},
        {"max_call_seconds": float("inf")},
    ):
        with pytest.raises(ValueError):
            RuntimeConfig(**values)


class BrokenLLM(LLM):
    async def respond(
        self,
        tenant: TenantContext,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "text", "text": "A complete sentence."}
        raise RuntimeError("Private provider failure")


class BrokenTTS(TTS):
    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        yield frame(0)
        raise RuntimeError("Private synthesis failure")


@pytest.mark.parametrize("kind", ["llm", "tts"])
async def test_partial_provider_failure_preserves_only_completed_output_chunks(kind: str) -> None:
    media = Media()
    llm = BrokenLLM() if kind == "llm" else LLM("A complete sentence.")
    tts = BrokenTTS() if kind == "tts" else TTS()
    worker = asyncio.create_task(runtime(STT(), tts, llm).run(context(), media))
    await media.turn()
    result = await asyncio.wait_for(worker, 2)
    assert result.error == f"{kind}_failed"
    assert result.sent_frames == 1 and result.completed_turns == 0
    assistants = [entry["content"] for entry in result.messages if entry["role"] == "assistant"]
    assert assistants == (["A complete sentence."] if kind == "llm" else [])
    assert "Private" not in str(result)
    await no_runtime_tasks()


class SlowSecondChunk(TTS):
    def __init__(self) -> None:
        super().__init__()
        self.blocked = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        self.texts.append(text)
        if len(self.texts) == 2:
            self.blocked.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
        yield frame(0)


async def test_interruption_marks_transmitted_history_without_claiming_playback() -> None:
    media, tts = Media(), SlowSecondChunk()
    worker = asyncio.create_task(runtime(STT(), tts, LLM()).run(context(), media))
    await media.turn()
    await asyncio.wait_for(tts.blocked.wait(), 1)
    await media.incoming.put(frame(10))
    await asyncio.wait_for(tts.cancelled.wait(), 1)
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.interruptions == 1
    assistants = [entry["content"] for entry in result.messages if entry["role"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].startswith("We open at nine.")
    assert "playback is unconfirmed" in assistants[0]
    assert "Please check" not in assistants[0]
    await no_runtime_tasks()


class LateTTS(TTS):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            await self.release.wait()
        try:
            yield frame(0)
        finally:
            self.finished.set()


async def test_generation_guard_blocks_late_output_after_provider_cancellation() -> None:
    media, tts = Media(), LateTTS()
    states: list[CallState] = []

    async def state(value: CallState) -> None:
        states.append(value)

    worker = asyncio.create_task(runtime(STT(), tts, LLM()).run(context(), media, on_state=state))
    await media.turn()
    await asyncio.wait_for(tts.started.wait(), 1)
    await media.incoming.put(frame(10))
    await asyncio.wait_for(tts.cancelled.wait(), 1)
    tts.release.set()
    await asyncio.wait_for(tts.finished.wait(), 1)
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.sent_frames == 0
    assert result.interruptions == 1
    assert CallState.SPEAKING not in states
    await no_runtime_tasks()


async def test_bounded_history_preserves_system_and_latest_turns() -> None:
    media, llm = Media(), LLM("Done.")
    completed = asyncio.Queue[None]()

    async def state(value: CallState) -> None:
        if value == CallState.LISTENING and llm.calls:
            completed.put_nowait(None)

    worker = asyncio.create_task(
        runtime(STT(), TTS(), llm, max_history_messages=5).run(
            context(),
            media,
            on_state=state,
        )
    )
    for sequence in range(4):
        await media.turn(sequence * 10)
        # Every new turn also queues a LISTENING transition, so wait for output completion.
        await media.wait_sent(sequence + 1)
        await asyncio.sleep(0.02)
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.completed_turns == 4
    assert len(result.messages) <= 5
    assert result.messages[0]["role"] == "system"
    for _, messages in llm.calls:
        assert len(messages) <= 5
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user" and messages[-1]["role"] == "user"
    await no_runtime_tasks()


@pytest.mark.parametrize("target", ["receive", "send"])
async def test_transport_failure_does_not_escape_provider_details(target: str) -> None:
    class BrokenMedia(Media):
        async def receive(self) -> AudioFrame | None:
            if target == "receive":
                raise RuntimeError("Private transport detail")
            return await super().receive()

        async def send(self, audio: AudioFrame) -> None:
            raise RuntimeError("Private transport detail")

    media = BrokenMedia()
    worker = asyncio.create_task(runtime(STT(), TTS(), LLM()).run(context(), media))
    if target == "send":
        await media.turn()
    result = await asyncio.wait_for(worker, 2)
    assert result.error == "media_failed"
    assert "Private" not in str(result)
    await no_runtime_tasks()


async def test_delayed_onset_state_cannot_overwrite_a_later_response_phase() -> None:
    states: list[CallState] = []

    async def state(value: CallState) -> None:
        states.append(value)

    session = _Session(runtime(STT(), TTS(), LLM()), context(), Media(), state)
    # The reader schedules onset, but the scheduler starts the response phase first.
    session.schedule_state(CallState.LISTENING, 0)
    await session.state(CallState.SPEAKING, 0)
    await asyncio.gather(*session.tasks)
    assert states == [CallState.SPEAKING]
    assert session.result.state_transitions == ["SPEAKING"]
    await no_runtime_tasks()


async def test_delayed_vad_onset_retains_early_acoustic_frames_for_streamed_stt() -> None:
    class DelayedVAD(ScriptVAD):
        def process(self, audio: AudioFrame) -> VadResult:
            # Component reproduction of the measured real fixture's 420 ms onset.
            # Early frames contain acoustic input, despite the negative VAD decision.
            if audio.sequence < 7:
                return VadResult()
            return super().process(audio)

    media, stt, llm = Media(), STT(), LLM("Done.")
    engine = ConversationRuntime(
        stt,
        TTS(),
        llm,
        config=RuntimeConfig(greeting=""),
        vad_factory=DelayedVAD,
    )
    worker = asyncio.create_task(engine.run(context(), media))
    for sequence in range(8):
        await media.incoming.put(frame(sequence))
    await asyncio.wait_for(stt.consumed.wait(), 1)
    assert stt.sequences == [list(range(8))]
    await media.incoming.put(frame(8, voiced=False))
    await media.wait_sent(1)
    await asyncio.sleep(0.02)
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.error is None and result.completed_turns == 1
    assert stt.sequences == [list(range(9))]
    await no_runtime_tasks()


async def test_acoustic_preroll_is_bounded_and_never_replays_entire_idle_history() -> None:
    media, stt = Media(), STT()
    worker = asyncio.create_task(runtime(stt, TTS(), LLM("Done.")).run(context(), media))
    for sequence in range(20):
        await media.incoming.put(frame(sequence, voiced=False))
    await media.incoming.put(frame(20))
    await asyncio.wait_for(stt.consumed.wait(), 1)
    assert stt.sequences == [list(range(12, 21))]
    await media.incoming.put(None)
    result = await asyncio.wait_for(worker, 2)
    assert result.error is None
    await no_runtime_tasks()
