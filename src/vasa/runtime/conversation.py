"""Stream caller audio independently of model and paced speech output.

Transmitted frames are transport evidence only. They do not establish playback or
that a caller heard a generated response. No conversation data is logged here.
"""

import asyncio
import copy
import json
import math
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from vasa.contracts.models import AudioFrame, CallState, TenantContext
from vasa.contracts.providers import LLMProvider, MediaConnection, STTProvider, TTSProvider
from vasa.speech.vad import StreamingVAD


class ToolExecutor(Protocol):
    async def execute(
        self, context: TenantContext, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...


MessageCallback = Callable[[dict[str, Any]], Awaitable[None]]
StateCallback = Callable[[CallState], Awaitable[None]]
# Native WebRTC can first declare speech after quiet opening phonemes. Retain
# 480 ms of acoustic context for streamed STT, independently of VAD's 120 ms
# segmentation preroll. The pinned real fixture starts VAD at 420 ms; a 120 ms
# capture preroll clipped its first word even though full-fixture STT recognized it.
_STREAM_PREROLL_FRAMES = 8


class ConversationError(Exception):
    """Fixed failure codes only; provider exception text must never escape."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if code
            in {
                "audio_backpressure",
                "invalid_audio",
                "stt_failed",
                "stt_timeout",
                "llm_failed",
                "llm_timeout",
                "tts_failed",
                "tts_timeout",
                "media_failed",
                "tool_not_enabled",
                "invalid_response",
                "response_limit",
                "turn_limit",
                "call_timeout",
                "state_callback_failed",
                "cleanup_timeout",
                "cancelled",
            }
            else "invalid_response"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    system_prompt: str = (
        "You are a helpful business voice assistant. Keep responses concise. "
        "Never invent business facts."
    )
    greeting: str = "Hello, how can I help?"
    max_call_seconds: float = 600
    max_turns: int = 50
    max_tool_rounds: int = 4
    max_tool_actions: int = 8
    max_history_messages: int = 32
    max_response_chars: int = 2000
    audio_queue_frames: int = 64
    stt_timeout_seconds: float = 30
    llm_timeout_seconds: float = 45
    tts_timeout_seconds: float = 30

    def __post_init__(self) -> None:
        integer_bounds = (
            (self.max_turns, 1, 1000),
            (self.max_tool_rounds, 1, 8),
            (self.max_tool_actions, 1, 16),
            (self.max_history_messages, 3, 64),
            (self.max_response_chars, 1, 2000),
            (self.audio_queue_frames, 1, 512),
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high
            for value, low, high in integer_bounds
        ):
            raise ValueError("invalid runtime resource bounds")
        for value in (
            self.max_call_seconds,
            self.stt_timeout_seconds,
            self.llm_timeout_seconds,
            self.tts_timeout_seconds,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 3600:
                raise ValueError("invalid runtime timeout")
        if (
            not self.system_prompt.strip()
            or len(self.system_prompt) > 4096
            or len(self.greeting) > self.max_response_chars
            or "\x00" in self.system_prompt
            or "\x00" in self.greeting
        ):
            raise ValueError("invalid runtime instructions")


@dataclass(slots=True)
class ConversationResult:
    received_frames: int = 0
    sent_frames: int = 0
    completed_turns: int = 0
    interruptions: int = 0
    state_transitions: list[str] = field(default_factory=list)
    latencies_ms: dict[str, list[float]] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class ConversationRuntime:
    def __init__(
        self,
        stt: STTProvider,
        tts: TTSProvider,
        llm: LLMProvider,
        *,
        config: RuntimeConfig | None = None,
        tool_executor: ToolExecutor | None = None,
        vad_factory: Callable[[], StreamingVAD] = StreamingVAD,
    ) -> None:
        self.tool_executor = tool_executor
        self.stt = stt
        self.tts = tts
        self.llm = llm
        self.config = config or RuntimeConfig()
        self.vad_factory = vad_factory

    async def run(
        self,
        context: TenantContext,
        media: MediaConnection,
        *,
        on_state: StateCallback | None = None,
        on_message: MessageCallback | None = None,
    ) -> ConversationResult:
        return await _Session(self, context, media, on_state, on_message).run()


class _Session:
    def __init__(
        self,
        runtime: ConversationRuntime,
        context: TenantContext,
        media: MediaConnection,
        on_state: StateCallback | None,
        on_message: MessageCallback | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = runtime.config
        self.context = context
        self.media = media
        self.on_state = on_state
        self.on_message = on_message
        self.executed_ids: set[str] = set()
        self.tool_actions = 0
        self.result = ConversationResult(
            messages=[
                {"role": "system", "content": self.config.system_prompt},
            ]
        )
        self.vad = runtime.vad_factory()
        self.generation = 0
        self.tasks: set[asyncio.Task[Any]] = set()
        self.failure: asyncio.Future[ConversationError] = asyncio.get_running_loop().create_future()
        self.response: asyncio.Task[None] | None = None
        self.transcription: asyncio.Task[str] | None = None
        self.audio: asyncio.Queue[AudioFrame | None] | None = None
        self.preroll: deque[AudioFrame] = deque(maxlen=_STREAM_PREROLL_FRAMES)
        self.state_lock = asyncio.Lock()
        self.state_revision = 0
        self.utterances = 0
        self.utterance_frames = 0
        self.speech_end = time.monotonic()
        self.last_speech = self.speech_end
        self.next_send = self.speech_end
        self.response_message: dict[str, str] | None = None
        self.closing = False

    def metric(self, name: str, seconds: float) -> None:
        self.result.latencies_ms.setdefault(name, []).append(max(0.0, seconds * 1000))

    def spawn(self, coroutine: Awaitable[Any], generation: int | None) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coroutine)
        task.set_name("vasa-conversation")
        self.tasks.add(task)

        def completed(done: asyncio.Task[Any]) -> None:
            self.tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None and not self.closing and generation in {None, self.generation}:
                code = (
                    error
                    if isinstance(error, ConversationError)
                    else ConversationError("invalid_response")
                )
                if not self.failure.done():
                    self.failure.set_result(code)

        task.add_done_callback(completed)
        return task

    def schedule_state(self, state: CallState, generation: int) -> None:
        # Allocate order in the reader, before the scheduled coroutine can be delayed.
        self.state_revision += 1
        self.spawn(self.state(state, generation, revision=self.state_revision), generation)

    async def state(
        self,
        state: CallState,
        generation: int | None = None,
        *,
        revision: int | None = None,
    ) -> None:
        if generation is not None and generation != self.generation:
            return
        if revision is None:
            self.state_revision += 1
            revision = self.state_revision
        async with self.state_lock:
            if revision != self.state_revision or (
                generation is not None and generation != self.generation
            ):
                return
            if self.on_state is not None:
                try:
                    async with asyncio.timeout(2):
                        await self.on_state(state)
                except Exception:
                    raise ConversationError("state_callback_failed") from None
            if revision == self.state_revision and (
                generation is None or generation == self.generation
            ):
                if not self.result.state_transitions or self.result.state_transitions[-1] != state:
                    self.result.state_transitions.append(state.value)

    def append(self, role: str, text: str) -> dict[str, str]:
        message = {"role": role, "content": text}
        previous = list(self.result.messages)
        self.result.messages.append(message)
        try:
            self.trim_history()
        except ConversationError:
            self.result.messages = previous
            raise
        return message

    def trim_history(self) -> None:
        maximum = self.config.max_history_messages
        if len(self.result.messages) > maximum:
            while len(self.result.messages) > maximum:
                next_user = next(
                    (
                        i
                        for i in range(2, len(self.result.messages))
                        if self.result.messages[i]["role"] == "user"
                    ),
                    None,
                )
                if next_user is None:
                    raise ConversationError("response_limit")
                del self.result.messages[1:next_user]

    async def persist(self, message: dict[str, Any]) -> None:
        if self.on_message is not None:
            try:
                async with asyncio.timeout(2):
                    await self.on_message(copy.deepcopy(message))
            except Exception:
                raise ConversationError("state_callback_failed") from None

    def snapshot(self) -> list[dict[str, Any]]:
        messages = copy.deepcopy(self.result.messages)
        # Drop greeting and complete old user turns, never split tool protocol groups.
        while len(messages) > 1 and messages[1]["role"] != "user":
            del messages[1]
        while sum(len(json.dumps(item).encode("utf-8")) for item in messages) > 32768:
            next_user = next(
                (i for i in range(2, len(messages)) if messages[i]["role"] == "user"), None
            )
            if next_user is None:
                raise ConversationError("response_limit")
            del messages[1:next_user]
        return messages

    async def run(self) -> ConversationResult:
        cancelled = False
        try:
            await self.persist(self.result.messages[0])
            await self.state(CallState.CONNECTED)
            await self.state(CallState.LISTENING)
            reader = self.spawn(self.read(), None)
            if self.config.greeting.strip():
                self.response = self.spawn(self.greet(0), 0)
            done, _ = await asyncio.wait(
                {reader, self.failure},
                timeout=self.config.max_call_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                self.result.error = "call_timeout"
            elif self.failure in done:
                self.result.error = self.failure.result().code
            elif reader.done() and not reader.cancelled() and reader.exception() is not None:
                error = reader.exception()
                self.result.error = (
                    error.code if isinstance(error, ConversationError) else "media_failed"
                )
        except asyncio.CancelledError:
            cancelled = True
            self.result.error = "cancelled"
        except ConversationError as error:
            self.result.error = error.code
        finally:
            self.closing = True
            self.generation += 1
            self.vad.finish()
            pending = list(self.tasks)
            for task in pending:
                task.cancel()
            if pending:
                _, stuck = await asyncio.wait(pending, timeout=3)
                if stuck and self.result.error is None:
                    self.result.error = "cleanup_timeout"
            self.failure.cancel()
            try:
                if self.result.error is not None:
                    await self.state(CallState.ERROR)
                await self.state(CallState.ENDING)
                await self.state(CallState.ENDED)
            except ConversationError:
                self.result.error = self.result.error or "state_callback_failed"
        if cancelled:
            raise asyncio.CancelledError
        return self.result

    def enqueue(self, frame: AudioFrame | None) -> None:
        assert self.audio is not None
        try:
            self.audio.put_nowait(frame)
        except asyncio.QueueFull:
            raise ConversationError("audio_backpressure") from None

    async def read(self) -> None:
        try:
            while True:
                frame = await self.media.receive()
                if frame is None:
                    return
                self.result.received_frames += 1
                if frame.sample_rate != 16000 or frame.channels != 1 or len(frame.pcm) != 1920:
                    raise ConversationError("invalid_audio")
                try:
                    detection = self.vad.process(frame)
                except ValueError:
                    raise ConversationError("invalid_audio") from None
                if detection.speech:
                    self.last_speech = time.monotonic()
                if detection.started:
                    self.utterances += 1
                    if self.utterances > self.config.max_turns:
                        raise ConversationError("turn_limit")
                    self.generation += 1
                    generation = self.generation
                    if self.response is not None and not self.response.done():
                        cancellation_started = time.monotonic()
                        self.result.interruptions += 1
                        if self.response_message is not None:
                            self.response_message["content"] += (
                                " [Interrupted; transmitted audio playback is unconfirmed.]"
                            )
                            self.spawn(self.persist(copy.deepcopy(self.response_message)), None)
                        self.response.cancel()
                        self.metric(
                            "barge_in_cancel_request", time.monotonic() - cancellation_started
                        )
                    if self.transcription is not None and not self.transcription.done():
                        self.transcription.cancel()
                    self.response_message = None
                    self.audio = asyncio.Queue(maxsize=self.config.audio_queue_frames)
                    self.transcription = self.spawn(self.transcribe(self.audio), generation)
                    self.utterance_frames = 0
                    for previous in self.preroll:
                        self.enqueue(previous)
                        self.utterance_frames += 1
                    self.schedule_state(CallState.LISTENING, generation)
                if self.audio is not None:
                    self.enqueue(frame)
                    self.utterance_frames += 1
                    if detection.ended or self.utterance_frames >= 333:
                        self.enqueue(None)
                        self.audio = None
                        self.speech_end = self.last_speech
                        assert self.transcription is not None
                        self.response = self.spawn(
                            self.respond(self.generation, self.transcription), self.generation
                        )
                        if not detection.ended:
                            self.vad.finish()
                self.preroll.append(frame)
        except asyncio.CancelledError:
            raise
        except ConversationError:
            raise
        except Exception:
            raise ConversationError("media_failed") from None

    async def transcribe(self, queue: asyncio.Queue[AudioFrame | None]) -> str:
        async def frames() -> AsyncIterator[AudioFrame]:
            while (frame := await queue.get()) is not None:
                yield frame

        latest = ""
        iterator = self.runtime.stt.transcribe(frames())
        try:
            async with asyncio.timeout(self.config.stt_timeout_seconds):
                async for text in iterator:
                    if not isinstance(text, str) or len(text) > 8192 or "\x00" in text:
                        raise ConversationError("invalid_response")
                    latest = text.strip()
        except TimeoutError:
            raise ConversationError("stt_timeout") from None
        except ConversationError:
            raise
        except Exception:
            raise ConversationError("stt_failed") from None
        finally:
            await _close_iterator(iterator)
        return latest

    async def greet(self, generation: int) -> None:
        self.response_message = None
        for chunk in _chunks(self.config.greeting, final=True)[0]:
            await self.speak(chunk, generation, None)
        if self.response_message is not None:
            await self.persist(self.response_message)
        await self.state(CallState.LISTENING, generation)

    async def respond(self, generation: int, transcription: asyncio.Task[str]) -> None:
        await self.state(CallState.TRANSCRIBING, generation)
        started = time.monotonic()
        text = await transcription
        self.metric("stt_finalization", time.monotonic() - started)
        if generation != self.generation:
            return
        if not text:
            await self.state(CallState.LISTENING, generation)
            return
        await self.persist(self.append("user", text))
        self.response_message = None
        await self.state(CallState.THINKING, generation)
        if self.runtime.tool_executor is not None:
            await self.respond_tools(generation)
            return
        iterator = self.runtime.llm.respond(self.context, self.snapshot())
        pending = ""
        count = 0
        llm_wait = 0.0
        llm_started = time.monotonic()
        first = True
        first_audio = True
        try:
            while generation == self.generation:
                waited = time.monotonic()
                try:
                    async with asyncio.timeout(self.config.llm_timeout_seconds - llm_wait):
                        event = await anext(iterator)
                except StopAsyncIteration:
                    break
                llm_wait += time.monotonic() - waited
                if generation != self.generation:
                    return
                if not isinstance(event, dict):
                    raise ConversationError("invalid_response")
                if event.get("type") != "text":
                    raise ConversationError("tool_not_enabled")
                if set(event) != {"type", "text"}:
                    raise ConversationError("invalid_response")
                fragment = event.get("text")
                if not isinstance(fragment, str) or "\x00" in fragment:
                    raise ConversationError("invalid_response")
                count += len(fragment)
                if count > self.config.max_response_chars:
                    raise ConversationError("response_limit")
                if fragment and first:
                    self.metric("llm_time_to_first_token", time.monotonic() - llm_started)
                    first = False
                pending += fragment
                chunks, pending = _chunks(pending)
                for chunk in chunks:
                    await self.speak(chunk, generation, self.speech_end if first_audio else None)
                    first_audio = False
            for chunk in _chunks(pending, final=True)[0]:
                await self.speak(chunk, generation, self.speech_end if first_audio else None)
                first_audio = False
            if first_audio:
                raise ConversationError("invalid_response")
            if generation == self.generation:
                self.result.completed_turns += 1
                await self.state(CallState.LISTENING, generation)
        except TimeoutError:
            raise ConversationError("llm_timeout") from None
        except ConversationError:
            raise
        except Exception:
            raise ConversationError("llm_failed") from None
        finally:
            await _close_iterator(iterator)
            if self.response_message is not None:
                await self.persist(self.response_message)

    async def respond_tools(self, generation: int) -> None:
        assert self.runtime.tool_executor is not None
        for round_number in range(self.config.max_tool_rounds + 1):
            iterator = self.runtime.llm.respond(self.context, self.snapshot())
            calls: list[dict[str, Any]] = []
            text = ""
            pending = ""
            llm_wait = 0.0
            self.response_message = None
            stream_finished = False
            try:
                while generation == self.generation:
                    waited = time.monotonic()
                    try:
                        async with asyncio.timeout(self.config.llm_timeout_seconds - llm_wait):
                            event = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    llm_wait += time.monotonic() - waited
                    if generation != self.generation:
                        return
                    if event.get("type") == "text" and set(event) == {"type", "text"}:
                        fragment = event["text"]
                        if not isinstance(fragment, str) or "\x00" in fragment:
                            raise ConversationError("invalid_response")
                        text += fragment
                        if len(text) > self.config.max_response_chars:
                            raise ConversationError("response_limit")
                        pending += fragment
                        chunks, pending = _chunks(pending)
                        for chunk in chunks:
                            await self.speak(chunk, generation, self.speech_end)
                    elif event.get("type") == "tool_call" and set(event) == {
                        "type",
                        "id",
                        "name",
                        "arguments",
                    }:
                        identifier, name, arguments = (
                            event["id"],
                            event["name"],
                            event["arguments"],
                        )
                        if (
                            not isinstance(identifier, str)
                            or not 1 <= len(identifier) <= 128
                            or identifier in self.executed_ids
                            or any(c["id"] == identifier for c in calls)
                            or not isinstance(name, str)
                            or not 1 <= len(name) <= 64
                            or not isinstance(arguments, dict)
                            or len(json.dumps(arguments, allow_nan=False)) > 32768
                        ):
                            raise ConversationError("invalid_response")
                        calls.append(event)
                        if len(calls) > self.config.max_tool_actions:
                            raise ConversationError("response_limit")
                    else:
                        raise ConversationError("invalid_response")
                stream_finished = True
            except TimeoutError:
                raise ConversationError("llm_timeout") from None
            except ConversationError:
                raise
            except Exception:
                raise ConversationError("llm_failed") from None
            finally:
                await _close_iterator(iterator)
                if not stream_finished and self.response_message is not None:
                    await self.persist(self.response_message)
            if calls:
                if (
                    round_number >= self.config.max_tool_rounds
                    or self.tool_actions + len(calls) > self.config.max_tool_actions
                ):
                    raise ConversationError("response_limit")
                # Commit the protocol request/results together after all actions complete.
                if self.response_message is not None:
                    await self.persist(self.response_message)
                    self.result.messages.remove(self.response_message)
                    self.response_message = None
                request: dict[str, Any] = {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": json.dumps(c["arguments"], allow_nan=False),
                            },
                        }
                        for c in calls
                    ],
                }
                completed_tools: list[dict[str, Any]] = []
                for call in calls:
                    self.executed_ids.add(call["id"])
                    self.tool_actions += 1
                    try:
                        async with asyncio.timeout(30):
                            result = await self.runtime.tool_executor.execute(
                                self.context, call["name"], call["arguments"]
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        result = {"status": "unknown", "code": "outcome_unknown"}
                    if not isinstance(result, dict):
                        raise ConversationError("invalid_response")
                    content = json.dumps(result, allow_nan=False)
                    if len(content.encode()) > 32768:
                        raise ConversationError("response_limit")
                    message = {"role": "tool", "tool_call_id": call["id"], "content": content}
                    completed_tools.append(message)
                    await self.persist(message)
                if generation != self.generation:
                    return
                previous = list(self.result.messages)
                self.result.messages.extend([request, *completed_tools])
                try:
                    self.trim_history()
                    self.snapshot()
                except ConversationError:
                    self.result.messages = previous
                    raise
                continue
            if not text.strip():
                raise ConversationError("invalid_response")
            try:
                for chunk in _chunks(pending, final=True)[0]:
                    await self.speak(chunk, generation, self.speech_end)
            finally:
                if self.response_message is not None:
                    await self.persist(self.response_message)
            self.result.completed_turns += 1
            await self.state(CallState.LISTENING, generation)
            return

    async def speak(self, text: str, generation: int, speech_end: float | None) -> None:
        if generation != self.generation:
            return
        iterator = self.runtime.tts.synthesize(text)
        started = time.monotonic()
        first = True
        frames = 0
        try:
            async with asyncio.timeout(self.config.tts_timeout_seconds):
                async for frame in iterator:
                    if generation != self.generation:
                        return
                    if frame.sample_rate != 16000 or frame.channels != 1 or len(frame.pcm) != 1920:
                        raise ConversationError("invalid_audio")
                    delay = self.next_send - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    if generation != self.generation:
                        return
                    if first:
                        await self.state(CallState.SPEAKING, generation)
                    if generation != self.generation:
                        return
                    send_started = time.monotonic()
                    try:
                        async with asyncio.timeout(5):
                            await self.media.send(
                                AudioFrame(
                                    pcm=frame.pcm,
                                    sample_rate=16000,
                                    sequence=self.result.sent_frames,
                                    timestamp_ns=time.monotonic_ns(),
                                )
                            )
                    except Exception:
                        raise ConversationError("media_failed") from None
                    # Pace send starts, without adding network write time to every frame.
                    self.next_send = send_started + 0.06
                    self.result.sent_frames += 1
                    frames += 1
                    if first:
                        self.metric("tts_time_to_first_audio", time.monotonic() - started)
                        if speech_end is not None:
                            self.metric(
                                "end_of_speech_to_first_audio", time.monotonic() - speech_end
                            )
                        first = False
            if not frames:
                raise ConversationError("tts_failed")
            if generation == self.generation:
                if self.response_message is None:
                    self.response_message = self.append("assistant", text)
                else:
                    self.response_message["content"] += " " + text
        except TimeoutError:
            raise ConversationError("tts_timeout") from None
        except ConversationError:
            raise
        except Exception:
            raise ConversationError("tts_failed") from None
        finally:
            await _close_iterator(iterator)


async def _close_iterator(iterator: object) -> None:
    closer = getattr(iterator, "aclose", None)
    if closer is not None:
        try:
            async with asyncio.timeout(1):
                await closer()
        except (Exception, asyncio.CancelledError):
            pass


def _chunks(text: str, *, final: bool = False) -> tuple[list[str], str]:
    """Emit complete sentences or <=200-character word chunks, retaining a short tail."""
    chunks: list[str] = []
    while text:
        sentence = re.search(r"[.!?](?:\s|$)", text[:200])
        if sentence is not None:
            boundary = sentence.start() + 1
        elif len(text) >= 200:
            boundary = text.rfind(" ", 0, 201)
            if boundary <= 0:
                boundary = 200
        elif final:
            boundary = len(text)
        else:
            break
        part = text[:boundary].strip()
        if part:
            chunks.append(part)
        text = text[boundary:].lstrip()
    return chunks, text
