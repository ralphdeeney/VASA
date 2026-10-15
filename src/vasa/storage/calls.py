import builtins
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from vasa.contracts.models import CallState, TenantContext
from vasa.storage.models import Base

Role = Literal["customer", "agent", "tool", "system"]
ToolStatus = Literal["succeeded", "failed", "cancelled", "unknown"]
ERROR_CODES = frozenset(
    {"denied", "invalid_input", "invalid_output", "busy", "timeout", "unavailable", "cancelled"}
)


class CallRecord(Base):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_calls_id_tenant"),
        UniqueConstraint("tenant_id", "instance_id", "external_call_id", name="uq_calls_external"),
        ForeignKeyConstraint(
            ["instance_id", "tenant_id"],
            ["whatsapp_instances.id", "whatsapp_instances.tenant_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_calls_times"),
        CheckConstraint("message_sequence BETWEEN 0 AND 1000", name="ck_calls_sequence"),
        CheckConstraint(
            "state IN (" + ",".join(f"'{state.value}'" for state in CallState) + ")",
            name="ck_calls_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    instance_id: Mapped[UUID] = mapped_column(Uuid)
    external_call_id: Mapped[str] = mapped_column(String(200))
    caller: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(20), default=CallState.CONNECTED.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(String(4000))
    outcome: Mapped[str | None] = mapped_column(String(200))
    message_sequence: Mapped[int] = mapped_column(default=0)


class CallMessage(Base):
    __tablename__ = "call_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["call_id", "tenant_id"], ["calls.id", "calls.tenant_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("call_id", "sequence", name="uq_messages_sequence"),
        CheckConstraint("sequence BETWEEN 1 AND 1000", name="ck_messages_sequence"),
        CheckConstraint("role IN ('customer','agent','tool','system')", name="ck_messages_role"),
        CheckConstraint("length(content) BETWEEN 1 AND 16384", name="ck_messages_content"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    sequence: Mapped[int]
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ToolExecution(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["call_id", "tenant_id"], ["calls.id", "calls.tenant_id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "status IN ('pending','succeeded','failed','cancelled','unknown')",
            name="ck_tool_calls_status",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_tool_calls_times"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN ("
            + ",".join(f"'{code}'" for code in sorted(ERROR_CODES))
            + ")",
            name="ck_tool_calls_code",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _time(value: datetime | None = None) -> datetime:
    value = value if value is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(UTC)


def _text(value: str | None, maximum: int, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError("invalid text field")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("invalid text field") from None
    return value


def _page(limit: int, offset: int = 0) -> None:
    if (
        type(limit) is not int
        or type(offset) is not int
        or not 1 <= limit <= 100
        or not 0 <= offset <= 100000
    ):
        raise ValueError("invalid pagination")


class CallRepository:
    """Trusted tenant context only; callers own transactions and durable audit policy."""

    def __init__(self, session: AsyncSession, context: TenantContext) -> None:
        if not isinstance(context.tenant_id, UUID) or not isinstance(context.user_id, UUID):
            raise ValueError("invalid trusted context")
        self.session, self.context = session, context

    async def get(self, call_id: UUID, *, lock: bool = False) -> CallRecord | None:
        query = select(CallRecord).where(
            CallRecord.id == call_id, CallRecord.tenant_id == self.context.tenant_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(query)

    async def create(
        self,
        instance_id: UUID,
        external_call_id: str,
        *,
        caller: str | None = None,
        started_at: datetime | None = None,
    ) -> CallRecord | None:
        from vasa.control.models import WhatsAppInstance

        instance = await self.session.scalar(
            select(WhatsAppInstance.id).where(
                WhatsAppInstance.id == instance_id,
                WhatsAppInstance.tenant_id == self.context.tenant_id,
            )
        )
        if instance is None:
            return None
        record = CallRecord(
            tenant_id=self.context.tenant_id,
            instance_id=instance_id,
            external_call_id=_text(external_call_id, 200),
            caller=_text(caller, 128, optional=True),
            started_at=_time(started_at),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[CallRecord]:
        _page(limit, offset)
        return list(
            (
                await self.session.scalars(
                    select(CallRecord)
                    .where(CallRecord.tenant_id == self.context.tenant_id)
                    .order_by(CallRecord.started_at.desc(), CallRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )

    async def append_message(self, call_id: UUID, role: Role, content: str) -> CallMessage | None:
        record = await self.get(call_id, lock=True)
        if record is None:
            return None
        if record.ended_at is not None or record.message_sequence >= 1000:
            raise ValueError("call closed or message capacity reached")
        if role not in {"customer", "agent", "tool", "system"}:
            raise ValueError("invalid message role")
        text = _text(content, 16384)
        record.message_sequence += 1
        message = CallMessage(
            tenant_id=self.context.tenant_id,
            call_id=call_id,
            sequence=record.message_sequence,
            role=role,
            content=text,
            created_at=_time(),
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def messages(
        self, call_id: UUID, *, after_sequence: int = 0, limit: int = 100
    ) -> builtins.list[CallMessage]:
        _page(limit)
        if type(after_sequence) is not int or not 0 <= after_sequence <= 1000:
            raise ValueError("invalid sequence cursor")
        return list(
            (
                await self.session.scalars(
                    select(CallMessage)
                    .where(
                        CallMessage.call_id == call_id,
                        CallMessage.tenant_id == self.context.tenant_id,
                        CallMessage.sequence > after_sequence,
                    )
                    .order_by(CallMessage.sequence)
                    .limit(limit)
                )
            ).all()
        )

    async def finalize(
        self,
        call_id: UUID,
        *,
        ended_at: datetime,
        state: CallState = CallState.ENDED,
        summary: str | None = None,
        outcome: str | None = None,
    ) -> CallRecord | None:
        record = await self.get(call_id, lock=True)
        if record is None:
            return None
        end = _time(ended_at)
        summary, outcome = _text(summary, 4000, optional=True), _text(outcome, 200, optional=True)
        if state not in {CallState.ENDED, CallState.ERROR} or end < record.started_at:
            raise ValueError("invalid call finalization")
        values = (end, state.value, summary, outcome)
        if record.ended_at is not None:
            if (record.ended_at, record.state, record.summary, record.outcome) != values:
                raise ValueError("call already finalized")
            return record
        record.ended_at, record.state, record.summary, record.outcome = values
        await self.session.flush()
        return record

    async def start_tool(self, call_id: UUID, name: str) -> ToolExecution | None:
        record = await self.get(call_id, lock=True)
        if record is None:
            return None
        if record.ended_at is not None or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("call closed or invalid tool name")
        count = await self.session.scalar(
            select(func.count())
            .select_from(ToolExecution)
            .where(
                ToolExecution.call_id == call_id, ToolExecution.tenant_id == self.context.tenant_id
            )
        )
        if count is not None and count >= 200:
            raise ValueError("tool capacity reached")
        execution = ToolExecution(
            tenant_id=self.context.tenant_id, call_id=call_id, name=name, started_at=_time()
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def finish_tool(
        self,
        execution_id: UUID,
        status: ToolStatus,
        *,
        error_code: str | None = None,
        ended_at: datetime | None = None,
    ) -> ToolExecution | None:
        execution = await self.session.scalar(
            select(ToolExecution)
            .where(
                ToolExecution.id == execution_id,
                ToolExecution.tenant_id == self.context.tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if execution is None:
            return None
        if (
            status not in {"succeeded", "failed", "cancelled", "unknown"}
            or (error_code is not None and error_code not in ERROR_CODES)
            or (status == "succeeded" and error_code is not None)
        ):
            raise ValueError("invalid tool completion")
        if execution.ended_at is not None:
            if (execution.status, execution.error_code) != (status, error_code) or (
                ended_at is not None and execution.ended_at != _time(ended_at)
            ):
                raise ValueError("tool already finalized")
            return execution
        end = _time(ended_at)
        if end < execution.started_at:
            raise ValueError("invalid tool completion time")
        execution.status, execution.error_code, execution.ended_at = status, error_code, end
        await self.session.flush()
        return execution

    async def tool_calls(
        self, call_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> builtins.list[ToolExecution]:
        _page(limit, offset)
        return list(
            (
                await self.session.scalars(
                    select(ToolExecution)
                    .where(
                        ToolExecution.call_id == call_id,
                        ToolExecution.tenant_id == self.context.tenant_id,
                    )
                    .order_by(ToolExecution.started_at, ToolExecution.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
