import asyncio
from uuid import UUID, uuid4

import pytest

from tests.control.fixtures import ControlHarness
from vasa.contracts.models import TenantContext
from vasa.runtime_finalization import AuditedExecutor, DurableCall
from vasa.storage.calls import CallRepository
from vasa.tools.concrete import KnowledgeInput, KnowledgeOutput
from vasa.tools.gateway import ToolBinding, ToolGateway


class Search:
    name = "knowledge_search"

    async def execute(
        self, context: TenantContext, arguments: dict[str, object]
    ) -> dict[str, object]:
        return {"matches": []}


@pytest.mark.integration
async def test_durable_messages_tool_metadata_and_error_finalization(
    control_harness: ControlHarness,
) -> None:
    h = control_harness
    context = TenantContext(h.tenants[0].id, h.users[0].id)
    call = await DurableCall.create(
        h.database, context, h.instances[0].id, f"worker-{uuid4()}", "customer"
    )
    await call.on_message({"role": "system", "content": "Bounded prompt"})
    await call.on_message({"role": "user", "content": "What are your hours?"})
    gateway = ToolGateway()
    gateway.register(ToolBinding(context.tenant_id, Search(), KnowledgeInput, KnowledgeOutput))
    executor = AuditedExecutor(gateway, frozenset({"knowledge_search"}), call)
    assert await executor.execute(context, "knowledge_search", {"query": "hours"}) == {
        "matches": []
    }
    await call.finalize("cancelled")
    async with h.database.session() as session:
        repo = CallRepository(session, context)
        record = await repo.get(call.call_id)
        assert record and record.state == "ERROR" and record.outcome == "interrupted"
        assert "What are your hours?" in (record.summary or "")
        assert "knowledge_search succeeded=1" in (record.summary or "")
        assert len(await repo.messages(call.call_id)) == 2
        executions = await repo.tool_calls(call.call_id)
        assert len(executions) == 1 and executions[0].status == "succeeded"
        other = CallRepository(session, TenantContext(h.tenants[1].id, h.users[1].id))
        assert await other.get(call.call_id) is None
        assert await other.messages(call.call_id) == []


class WaitingSearch(Search):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(
        self, context: TenantContext, arguments: dict[str, object]
    ) -> dict[str, object]:
        self.started.set()
        await asyncio.Event().wait()
        return {"matches": []}


@pytest.mark.integration
async def test_cancelled_action_has_durable_cancelled_metadata(
    control_harness: ControlHarness,
) -> None:
    h = control_harness
    context = TenantContext(h.tenants[0].id, h.users[0].id)
    call = await DurableCall.create(
        h.database, context, h.instances[0].id, f"worker-{uuid4()}", "customer"
    )
    tool = WaitingSearch()
    gateway = ToolGateway()
    gateway.register(ToolBinding(context.tenant_id, tool, KnowledgeInput, KnowledgeOutput))
    executor = AuditedExecutor(gateway, frozenset({tool.name}), call)
    task = asyncio.create_task(executor.execute(context, tool.name, {"query": "hours"}))
    await asyncio.wait_for(tool.started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with h.database.session() as session:
        rows = await CallRepository(session, context).tool_calls(call.call_id)
        assert len(rows) == 1 and rows[0].status == "cancelled"
        assert rows[0].error_code == "cancelled" and rows[0].ended_at is not None


@pytest.mark.integration
async def test_answer_failure_still_finalizes_durable_call(
    control_harness: ControlHarness,
) -> None:
    from tests.voice_worker.test_worker import Registry, Runtime, Transport
    from vasa.contracts.models import IncomingCall
    from vasa.voice_worker import handle_call

    h = control_harness
    context = TenantContext(h.tenants[0].id, h.users[0].id)
    incoming = IncomingCall(h.instances[0].external_id, f"worker-{uuid4()}", "customer")
    client, registry = Transport(failure="answer"), Registry()
    report = await handle_call(
        client,
        registry,
        context,
        incoming.instance_id,
        incoming,
        Runtime(),
        database=h.database,
        instance_uuid=h.instances[0].id,
    )
    assert report["error"] == "call_failed" and report["persisted"] is True
    assert client.calls[-1][0] == "hangup" and len(registry.deleted) == 1
    async with h.database.session() as session:
        record = await CallRepository(session, context).get(UUID(str(report["call_id"])))
        assert record and record.state == "ERROR" and record.ended_at is not None
        assert record.summary == (
            "No customer transcript was captured. No customer outcome was inferred."
        )


@pytest.mark.integration
async def test_persisted_prompt_greeting_and_explicit_operator_overrides(
    control_harness: ControlHarness,
) -> None:
    from vasa.runtime import RuntimeConfig
    from vasa.storage.models import Agent
    from vasa.voice_worker import persisted_config

    h = control_harness
    context = TenantContext(h.tenants[0].id, h.users[0].id)
    async with h.database.session() as session, session.begin():
        session.add(
            Agent(
                tenant_id=context.tenant_id,
                name="Reception",
                business_name="Clinic",
                business_description="Open weekdays",
                greeting="Welcome to the clinic",
                instructions="Do not offer medical advice",
                language="en",
                voice="kokoro_af_maple",
            )
        )
    config = await persisted_config(h.database, context, RuntimeConfig())
    assert config.greeting == "Welcome to the clinic"
    assert "Clinic" in config.system_prompt and "Open weekdays" in config.system_prompt
    assert "Do not offer medical advice" in config.system_prompt
    override = RuntimeConfig(greeting="Operator greeting", system_prompt="Operator instructions")
    assert (
        await persisted_config(
            h.database,
            context,
            override,
            greeting_override=True,
            instructions_override=True,
        )
        == override
    )
    foreign = TenantContext(h.tenants[1].id, h.users[1].id)
    assert await persisted_config(h.database, foreign, override) == override


@pytest.mark.integration
async def test_all_instance_contexts_come_from_matching_tenant_users(
    control_harness: ControlHarness,
) -> None:
    from vasa.voice_worker import resolve_all

    h = control_harness
    rows = await resolve_all(h.database)
    indexed = {instance: (context, external) for context, instance, external in rows}
    for tenant, user, instance in zip(h.tenants, h.users, h.instances, strict=True):
        assert indexed[instance.id] == (TenantContext(tenant.id, user.id), instance.external_id)


@pytest.mark.integration
async def test_large_tool_transcript_preserves_blank_slices_and_every_original_character(
    control_harness: ControlHarness,
) -> None:
    import json

    h = control_harness
    context = TenantContext(h.tenants[0].id, h.users[0].id)
    call = await DurableCall.create(
        h.database, context, h.instances[0].id, f"worker-{uuid4()}", "customer"
    )
    content = '{"text":"' + " " * 20000 + "\\\\" * 2000 + "\\n" * 2000 + '"}'
    await call.on_message({"role": "tool", "content": content})
    async with h.database.session() as session:
        rows = await CallRepository(session, context).messages(call.call_id)
        assert len(rows) >= 2
        assert all(len(row.content) <= 16384 and row.content.strip() for row in rows)
        segments = [json.loads(row.content) for row in rows]
        assert [part["transcript_segment"] for part in segments] == list(range(len(rows)))
        assert "".join(part["content"] for part in segments) == content
        assert call.messages == [{"role": "tool", "content": content}]


@pytest.mark.integration
async def test_unexpected_gateway_failure_never_records_false_success(
    control_harness: ControlHarness,
) -> None:
    from vasa.tools.gateway import ToolError

    class BrokenGateway(ToolGateway):
        async def execute(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("private detail")

    h = control_harness
    context = TenantContext(h.tenants[0].id, h.users[0].id)
    call = await DurableCall.create(
        h.database, context, h.instances[0].id, f"worker-{uuid4()}", "customer"
    )
    executor = AuditedExecutor(BrokenGateway(), frozenset({"knowledge_search"}), call)
    with pytest.raises(ToolError, match="unavailable"):
        await executor.execute(context, "knowledge_search", {"query": "hours"})
    await call.finalize("call_failed")
    async with h.database.session() as session:
        repository = CallRepository(session, context)
        rows = await repository.tool_calls(call.call_id)
        assert rows[0].status == "unknown" and rows[0].error_code == "unavailable"
        record = await repository.get(call.call_id)
        assert record and "knowledge_search unknown=1" in (record.summary or "")
        assert "private detail" not in (record.summary or "")
