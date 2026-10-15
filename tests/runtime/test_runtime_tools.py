"""Scripted tool execution components: bounded and tenant-local, never live acceptance."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.runtime.test_conversation import LLM, STT, TTS, Media, ScriptVAD, context, frame
from vasa.contracts.models import CallState, TenantContext
from vasa.llm.common import validate_context
from vasa.runtime import ConversationRuntime, RuntimeConfig


class ToolResponses(LLM):
    def __init__(self, *, repeat: bool = False, loop: bool = False) -> None:
        super().__init__()
        self.repeat, self.loop = repeat, loop
        self.snapshots: list[list[dict[str, Any]]] = []

    async def respond(
        self, tenant: TenantContext, messages: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        validate_context(tenant, messages, allow_tools=True)
        self.snapshots.append(messages)
        index = len(self.snapshots)
        if index == 1 or self.repeat or self.loop:
            yield {
                "type": "tool_call",
                "id": "action" if not self.loop else f"action{index}",
                "name": "knowledge_search",
                "arguments": {"query": "hours"},
            }
        else:
            result = json.loads(messages[-1]["content"])
            yield {
                "type": "text",
                "text": "The action is unavailable." if result.get("code") else "We open at nine.",
            }


class Executor:
    def __init__(self, *, code: str | None = None, block: bool = False) -> None:
        self.code, self.block = code, block
        self.calls: list[TenantContext] = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(
        self, tenant: TenantContext, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(tenant)
        self.started.set()
        if self.block:
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()
        return {"code": self.code} if self.code else {"matches": [{"text": "We open at nine."}]}


@pytest.mark.parametrize("code", [None, "denied", "unavailable"])
async def test_tool_results_continue_without_retry_and_persist_each_message(
    code: str | None,
) -> None:
    media, executor, llm = Media(), Executor(code=code), ToolResponses()
    tenant = context()
    records: list[dict[str, Any]] = []
    complete = asyncio.Event()

    async def persist(message: dict[str, Any]) -> None:
        records.append(message)

    async def state(value: CallState) -> None:
        if value == CallState.LISTENING and media.sent:
            complete.set()

    engine = ConversationRuntime(
        STT(),
        TTS(),
        llm,
        config=RuntimeConfig(greeting=""),
        tool_executor=executor,
        vad_factory=ScriptVAD,
    )
    task = asyncio.create_task(engine.run(tenant, media, on_state=state, on_message=persist))
    await media.turn()
    await asyncio.wait_for(complete.wait(), 1)
    await media.incoming.put(None)
    result = await task
    assert result.error is None and result.completed_turns == 1
    assert executor.calls == [tenant]
    assert [r["role"] for r in records] == ["system", "user", "tool", "assistant"]
    assert records[-1]["content"] == ("The action is unavailable." if code else "We open at nine.")
    assert llm.snapshots[-1][-1]["tool_call_id"] == "action"


@pytest.mark.parametrize("repeat", [True, False])
async def test_duplicate_ids_and_round_limit_never_repeat_business_action(repeat: bool) -> None:
    media, executor, llm = Media(), Executor(), ToolResponses(repeat=repeat, loop=not repeat)
    engine = ConversationRuntime(
        STT(),
        TTS(),
        llm,
        config=RuntimeConfig(greeting="", max_tool_rounds=2),
        tool_executor=executor,
        vad_factory=ScriptVAD,
    )
    task = asyncio.create_task(engine.run(context(), media))
    await media.turn()
    result = await asyncio.wait_for(task, 1)
    assert result.error == ("invalid_response" if repeat else "response_limit")
    assert len(executor.calls) == (1 if repeat else 2)
    assert not media.sent


async def test_barge_in_cancels_action_and_removes_unfinished_protocol_group() -> None:
    media, executor, llm = Media(), Executor(block=True), ToolResponses()
    engine = ConversationRuntime(
        STT(),
        TTS(),
        llm,
        config=RuntimeConfig(greeting=""),
        tool_executor=executor,
        vad_factory=ScriptVAD,
    )
    task = asyncio.create_task(engine.run(context(), media))
    await media.turn()
    await asyncio.wait_for(executor.started.wait(), 1)
    await media.incoming.put(frame(10))
    await asyncio.wait_for(executor.cancelled.wait(), 1)
    await media.incoming.put(None)
    result = await task
    assert result.interruptions == 1 and len(executor.calls) == 1
    assert not any("tool_calls" in item for item in result.messages)
    assert not media.sent


async def test_persistence_is_independent_of_bounded_context_and_includes_greeting() -> None:
    media, records = Media(), []
    llm = LLM("Done.")
    engine = ConversationRuntime(
        STT(),
        TTS(),
        llm,
        config=RuntimeConfig(greeting="Hello.", max_history_messages=5),
        vad_factory=ScriptVAD,
    )

    async def persist(message: dict[str, Any]) -> None:
        records.append(message)

    task = asyncio.create_task(engine.run(context(), media, on_message=persist))
    await media.wait_sent(1)
    await asyncio.sleep(0.01)
    for index in range(4):
        await media.turn(index * 10)
        await media.wait_sent(index + 2)
        await asyncio.sleep(0.01)
    await media.incoming.put(None)
    result = await task
    assert len(result.messages) <= 5
    assert len(records) == 10 and records[1] == {"role": "assistant", "content": "Hello."}


async def test_tool_mode_streams_text_before_provider_finishes_and_persists_interruption() -> None:
    class Streaming(LLM):
        def __init__(self) -> None:
            super().__init__()
            self.waiting = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def respond(
            self, tenant: TenantContext, messages: list[dict[str, Any]]
        ) -> AsyncIterator[dict[str, Any]]:
            yield {"type": "text", "text": "One complete sentence. "}
            self.waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()

    media, llm, records = Media(), Streaming(), []

    async def persist(message: dict[str, Any]) -> None:
        records.append(message)

    engine = ConversationRuntime(
        STT(),
        TTS(),
        llm,
        config=RuntimeConfig(greeting=""),
        tool_executor=Executor(),
        vad_factory=ScriptVAD,
    )
    task = asyncio.create_task(engine.run(context(), media, on_message=persist))
    await media.turn()
    await asyncio.wait_for(llm.waiting.wait(), 1)
    assert len(media.sent) == 1
    await media.incoming.put(frame(10))
    await asyncio.wait_for(llm.cancelled.wait(), 1)
    await media.incoming.put(None)
    result = await task
    assert result.interruptions == 1
    assistants = [message for message in records if message["role"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0]["content"].startswith("One complete sentence.")
    assert "playback is unconfirmed" in assistants[0]["content"]


async def test_failed_message_callback_stops_safely_with_fixed_code() -> None:
    async def persist(message: dict[str, Any]) -> None:
        raise RuntimeError("private database details")

    engine = ConversationRuntime(
        STT(), TTS(), LLM(), config=RuntimeConfig(greeting=""), vad_factory=ScriptVAD
    )
    result = await engine.run(context(), Media(), on_message=persist)
    assert result.error == "state_callback_failed"
    assert "private" not in str(result)
