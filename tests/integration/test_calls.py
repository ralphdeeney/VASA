import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vasa.config import Settings
from vasa.contracts.models import TenantContext
from vasa.control.models import WhatsAppInstance
from vasa.storage.calls import CallMessage, CallRecord, CallRepository, Role, ToolExecution
from vasa.storage.database import Database
from vasa.storage.models import Tenant

pytestmark = pytest.mark.integration


async def instance(session: AsyncSession, owner: TenantContext) -> WhatsAppInstance:
    mapping = WhatsAppInstance(
        tenant_id=owner.tenant_id, external_id=f"test-call-{uuid4()}", name="Synthetic instance"
    )
    session.add(mapping)
    await session.flush()
    return mapping


async def test_call_transcript_and_tool_records_are_tenant_scoped(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    a, b = tenant_contexts
    mapping = await instance(db_session, a)
    own, foreign = CallRepository(db_session, a), CallRepository(db_session, b)
    call = await own.create(mapping.id, "synthetic-call", caller="synthetic-caller")
    assert call is not None
    assert await foreign.create(mapping.id, "forged") is None
    assert await foreign.get(call.id) is None
    assert await foreign.list() == []
    assert await foreign.append_message(call.id, "customer", "foreign") is None
    assert await foreign.start_tool(call.id, "end_call") is None
    assert await foreign.finalize(call.id, ended_at=datetime.now(UTC)) is None
    first = await own.append_message(call.id, "customer", "Synthetic request")
    second = await own.append_message(call.id, "agent", "Synthetic answer")
    assert first is not None and second is not None
    assert [message.sequence for message in await own.messages(call.id)] == [1, 2]
    assert await own.messages(call.id, after_sequence=1, limit=1) == [second]
    assert await foreign.messages(call.id) == []
    execution = await own.start_tool(call.id, "custom_webhook")
    assert execution is not None and execution.status == "pending"
    assert await foreign.finish_tool(execution.id, "succeeded") is None
    assert await foreign.tool_calls(call.id) == []
    assert await own.finish_tool(execution.id, "unknown", error_code="timeout") is execution
    assert await own.tool_calls(call.id) == [execution]
    assert execution.ended_at is not None
    assert db_session.in_transaction(), "repository must not commit caller writes"


async def test_database_rejects_foreign_instance_message_and_tool_parent(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    a, b = tenant_contexts
    mapping = await instance(db_session, a)
    call = await CallRepository(db_session, a).create(mapping.id, "synthetic-call")
    assert call is not None
    now = datetime.now(UTC)
    rows = [
        CallRecord(
            tenant_id=b.tenant_id,
            instance_id=mapping.id,
            external_call_id="foreign",
            started_at=now,
        ),
        CallMessage(
            tenant_id=b.tenant_id,
            call_id=call.id,
            sequence=1,
            role="customer",
            content="foreign",
            created_at=now,
        ),
        ToolExecution(tenant_id=b.tenant_id, call_id=call.id, name="end_call", started_at=now),
    ]
    for row in rows:
        async with db_session.begin_nested():
            db_session.add(row)
            with pytest.raises(IntegrityError):
                await db_session.flush()


async def test_finalize_is_immutable_and_rejects_late_messages_and_tools(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    owner = tenant_contexts[0]
    mapping = await instance(db_session, owner)
    repo = CallRepository(db_session, owner)
    call = await repo.create(mapping.id, "synthetic-call")
    assert call is not None
    with pytest.raises(ValueError, match="finalization"):
        await repo.finalize(call.id, ended_at=call.started_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone"):
        await repo.finalize(call.id, ended_at=datetime(2026, 1, 1))
    end = call.started_at + timedelta(seconds=10)
    assert await repo.finalize(call.id, ended_at=end, summary="Synthetic summary") is call
    assert await repo.finalize(call.id, ended_at=end, summary="Synthetic summary") is call
    assert (call.ended_at - call.started_at).total_seconds() == 10
    with pytest.raises(ValueError, match="already finalized"):
        await repo.finalize(call.id, ended_at=end, outcome="different")
    with pytest.raises(ValueError, match="closed"):
        await repo.append_message(call.id, "customer", "late")
    with pytest.raises(ValueError, match="closed"):
        await repo.start_tool(call.id, "end_call")


async def test_tool_completion_codes_and_idempotency(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    owner = tenant_contexts[0]
    repo = CallRepository(db_session, owner)
    mapping = await instance(db_session, owner)
    call = await repo.create(mapping.id, "synthetic-call")
    assert call is not None
    execution = await repo.start_tool(call.id, "custom_webhook")
    assert execution is not None
    with pytest.raises(ValueError, match="completion"):
        await repo.finish_tool(execution.id, "succeeded", error_code="private token")
    with pytest.raises(ValueError, match="time"):
        await repo.finish_tool(
            execution.id, "failed", ended_at=execution.started_at - timedelta(seconds=1)
        )
    assert await repo.finish_tool(execution.id, "succeeded") is execution
    assert await repo.finish_tool(execution.id, "succeeded") is execution
    with pytest.raises(ValueError, match="already finalized"):
        await repo.finish_tool(execution.id, "failed", error_code="unavailable")
    assert not hasattr(execution, "arguments")
    assert not hasattr(execution, "result")


async def test_message_schema_and_capacity_bounds(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    owner = tenant_contexts[0]
    repo = CallRepository(db_session, owner)
    mapping = await instance(db_session, owner)
    call = await repo.create(mapping.id, "synthetic-call")
    assert call is not None
    for content in ("", "x" * 16385, "\x00", "\ud800"):
        with pytest.raises(ValueError, match="text"):
            await repo.append_message(call.id, "customer", content)
    with pytest.raises(ValueError, match="role"):
        await repo.append_message(call.id, cast(Role, "assistant"), "synthetic")
    call.message_sequence = 999
    await db_session.flush()
    message = await repo.append_message(call.id, "system", "capacity boundary")
    assert message is not None and message.sequence == 1000
    with pytest.raises(ValueError, match="capacity"):
        await repo.append_message(call.id, "system", "overflow")
    for limit in (0, 101, True):
        with pytest.raises(ValueError, match="pagination"):
            await repo.list(limit=limit)
        with pytest.raises(ValueError, match="pagination"):
            await repo.messages(call.id, limit=limit)
    with pytest.raises(ValueError, match="cursor"):
        await repo.messages(call.id, after_sequence=-1)


async def test_tool_capacity_and_duplicate_external_call(
    db_session: AsyncSession, tenant_contexts: tuple[TenantContext, TenantContext]
) -> None:
    owner = tenant_contexts[0]
    repo = CallRepository(db_session, owner)
    mapping = await instance(db_session, owner)
    call = await repo.create(mapping.id, "synthetic-call")
    assert call is not None
    db_session.add_all(
        ToolExecution(
            tenant_id=owner.tenant_id,
            call_id=call.id,
            name="custom_webhook",
            started_at=datetime.now(UTC),
        )
        for _ in range(200)
    )
    await db_session.flush()
    with pytest.raises(ValueError, match="capacity"):
        await repo.start_tool(call.id, "custom_webhook")
    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            await repo.create(mapping.id, "synthetic-call")


async def test_concurrent_message_writers_allocate_unique_ordered_sequences(
    dependency_settings: Settings,
) -> None:
    database = Database(dependency_settings.database_url.get_secret_value(), timeout_seconds=3)
    owner = TenantContext(uuid4(), uuid4())
    try:
        async with database.session() as session, session.begin():
            session.add(Tenant(id=owner.tenant_id, name="Concurrent persistence fixture"))
            await session.flush()
            mapping = await instance(session, owner)
            call = await CallRepository(session, owner).create(mapping.id, "concurrent-fixture")
            assert call is not None
            call_id = call.id

        async def append(number: int) -> int:
            async with database.session() as writer, writer.begin():
                message = await CallRepository(writer, owner).append_message(
                    call_id, "customer", f"synthetic-{number}"
                )
                assert message is not None
                return message.sequence

        async with asyncio.timeout(10):
            sequences = await asyncio.gather(*(append(number) for number in range(8)))
        assert sorted(sequences) == list(range(1, 9))
        async with database.session() as reader:
            repo = CallRepository(reader, owner)
            messages = await repo.messages(call_id)
            assert {message.content for message in messages} == {f"synthetic-{n}" for n in range(8)}
            persisted = await repo.get(call_id)
            assert persisted is not None and persisted.message_sequence == 8
    finally:
        try:
            async with database.session() as cleanup, cleanup.begin():
                await cleanup.execute(delete(Tenant).where(Tenant.id == owner.tenant_id))
            async with database.session() as check:
                assert (
                    await check.scalar(
                        select(CallRecord.id).where(CallRecord.tenant_id == owner.tenant_id)
                    )
                    is None
                )
        finally:
            await database.aclose()


async def test_persistence_writes_remain_uncommitted(
    db_session: AsyncSession,
    tenant_contexts: tuple[TenantContext, TenantContext],
    dependency_settings: Settings,
) -> None:
    owner = tenant_contexts[0]
    mapping = await instance(db_session, owner)
    repo = CallRepository(db_session, owner)
    call = await repo.create(mapping.id, "uncommitted-call")
    assert call is not None
    await repo.append_message(call.id, "customer", "synthetic-uncommitted")
    database = Database(dependency_settings.database_url.get_secret_value())
    try:
        async with database.session() as observer:
            assert await CallRepository(observer, owner).get(call.id) is None
        call_id = call.id
        await db_session.rollback()
        async with database.session() as observer:
            assert await CallRepository(observer, owner).get(call_id) is None
            assert await CallRepository(observer, owner).messages(call_id) == []
    finally:
        await database.aclose()
