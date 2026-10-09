"""Real gateway + scripted model behavioral components; no live-model acceptance."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from tests.runtime.test_conversation import STT, TTS, Media, ScriptVAD, context
from tests.runtime.test_runtime_tools import ToolResponses
from vasa.contracts.models import CallState, TenantContext
from vasa.runtime import ConversationRuntime, RuntimeConfig
from vasa.tools.concrete import KnowledgeInput, KnowledgeMatch, KnowledgeOutput, KnowledgeSearch
from vasa.tools.gateway import ToolBinding, ToolError, ToolGateway

pytestmark = pytest.mark.eval


class Retriever:
    def __init__(self, *, foreign: bool) -> None:
        self.foreign = foreign
        self.calls = 0

    async def search(self, tenant: TenantContext, query: str, top_k: int) -> list[KnowledgeMatch]:
        self.calls += 1
        return [
            KnowledgeMatch(
                tenant_id=str(uuid4() if self.foreign else tenant.tenant_id),
                source_id=str(uuid4()),
                chunk_id=str(uuid4()),
                text="We open at nine.",
                score=0.9,
            )
        ]


class ApprovedExecutor:
    def __init__(self, gateway: ToolGateway, granted: bool) -> None:
        self.gateway = gateway
        self.allowed = frozenset({"knowledge_search"}) if granted else frozenset()

    async def execute(
        self, tenant: TenantContext, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return await self.gateway.execute(tenant, name, arguments, allowed_tools=self.allowed)
        except ToolError as error:
            return {"status": "error", "code": error.code}


@pytest.mark.parametrize("mode", ["approved", "denied", "foreign_result"])
async def test_scripted_model_gateway_continuation_never_exposes_foreign_knowledge(
    mode: str,
) -> None:
    tenant, media, retriever = context(), Media(), Retriever(foreign=mode == "foreign_result")
    gateway = ToolGateway()
    gateway.register(
        ToolBinding(
            tenant.tenant_id,
            KnowledgeSearch(tenant.tenant_id, retriever),
            KnowledgeInput,
            KnowledgeOutput,
        )
    )
    executor = ApprovedExecutor(gateway, mode != "denied")
    speech = TTS()
    records: list[dict[str, Any]] = []
    completed = asyncio.Event()

    async def record(message: dict[str, Any]) -> None:
        records.append(message)

    async def state(value: CallState) -> None:
        if value == CallState.LISTENING and media.sent:
            completed.set()

    runtime = ConversationRuntime(
        STT(),
        speech,
        ToolResponses(),
        config=RuntimeConfig(greeting=""),
        tool_executor=executor,
        vad_factory=ScriptVAD,
    )
    task = asyncio.create_task(runtime.run(tenant, media, on_state=state, on_message=record))
    await media.turn()
    await asyncio.wait_for(completed.wait(), 1)
    await media.incoming.put(None)
    result = await task
    assert result.error is None
    assert retriever.calls == (0 if mode == "denied" else 1)
    expected = "We open at nine." if mode == "approved" else "The action is unavailable."
    assert speech.texts == [expected]
    assert records[-1]["content"] == expected
    if mode != "approved":
        assert "We open at nine" not in str(records)
