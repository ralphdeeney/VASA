"""Bounded durable per-call evidence and honest extractive summaries."""

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from vasa.contracts.models import CallState, TenantContext
from vasa.storage.calls import CallRepository, Role, ToolStatus
from vasa.storage.database import Database
from vasa.tools.gateway import ToolError, ToolGateway


def extractive_summary(
    messages: list[dict[str, str]],
    tool_outcomes: list[tuple[str, str]] | None = None,
) -> str:
    """Quote observed text and audit status; never infer customer resolution."""
    excerpts = [message["content"] for message in messages if message.get("role") == "user"]
    if not excerpts:
        summary = "No customer transcript was captured. No customer outcome was inferred."
    else:
        selected = excerpts if len(excerpts) <= 3 else [excerpts[0], *excerpts[-2:]]
        quotes = [" ".join(text.split())[:1000] for text in selected]
        summary = (
            "Customer transcript excerpts: "
            + " | ".join(quotes)
            + ". Resolution was not inferred from transcript text."
        )
    if tool_outcomes:
        # Names and status come exclusively from the trusted metadata repository.
        counts = Counter(tool_outcomes)
        status_text = "; ".join(
            f"{name} {status}={count}" for (name, status), count in sorted(counts.items())
        )
        summary += (
            " Recorded tool execution statuses: "
            + status_text
            + ". A tool status does not establish customer resolution."
        )
    return summary[:4000]


def transcript_segments(content: str) -> list[str]:
    """Lossless JSON envelopes for oversized messages, including whitespace slices.

    Every segment can be independently decoded; concatenate its content in
    segment order to recover the original message exactly.
    """
    if len(content) > 32768:
        raise ValueError("message exceeds runtime bound")
    if len(content) <= 16384:
        return [content]
    result: list[str] = []
    offset = 0
    while offset < len(content):

        def encode(size: int, start: int = offset, index: int = len(result)) -> str:
            return json.dumps(
                {"transcript_segment": index, "content": content[start : start + size]},
                ensure_ascii=False,
                separators=(",", ":"),
            )

        low, high = 1, min(16384, len(content) - offset)
        while low < high:
            middle = (low + high + 1) // 2
            if len(encode(middle)) <= 16384:
                low = middle
            else:
                high = middle - 1
        result.append(encode(low))
        offset += low
    return result


class DurableCall:
    """One transaction per event; never retain a DB lock during external actions."""

    def __init__(self, database: Database, context: TenantContext, call_id: UUID) -> None:
        self.database, self.context, self.call_id = database, context, call_id
        self.messages: list[dict[str, str]] = []

    @classmethod
    async def create(
        cls,
        database: Database,
        context: TenantContext,
        instance: UUID,
        external_call_id: str,
        caller: str,
    ) -> "DurableCall":
        async with asyncio.timeout(5):
            async with database.session() as session, session.begin():
                record = await CallRepository(session, context).create(
                    instance, external_call_id, caller=caller
                )
                if record is None:
                    raise ValueError("unknown trusted instance")
                call_id = record.id
        return cls(database, context, call_id)

    async def on_message(self, message: dict[str, Any]) -> None:
        role_map: dict[str, Role] = {
            "user": "customer",
            "assistant": "agent",
            "tool": "tool",
            "system": "system",
        }
        role = role_map.get(message.get("role", ""))
        content = message.get("content")
        if role is None or not isinstance(content, str) or not content.strip():
            return
        async with asyncio.timeout(5):
            async with self.database.session() as session, session.begin():
                repository = CallRepository(session, self.context)
                for segment in transcript_segments(content):
                    record = await repository.append_message(self.call_id, role, segment)
                    if record is None:
                        raise ValueError("missing trusted call")
        if len(self.messages) < 1000:
            self.messages.append({"role": message["role"], "content": content})

    async def finalize(self, error: str | None) -> None:
        # Reuse identical values for idempotent retry after an uncertain commit.
        ended_at = datetime.now(UTC)
        tool_outcomes: list[tuple[str, str]] = []
        audit_loaded = True
        try:
            async with asyncio.timeout(5):
                async with self.database.session() as session:
                    repository = CallRepository(session, self.context)
                    for offset in (0, 100):
                        rows = await repository.tool_calls(self.call_id, limit=100, offset=offset)
                        tool_outcomes.extend((row.name, row.status) for row in rows)
                        if len(rows) < 100:
                            break
        except Exception:
            audit_loaded = False
            tool_outcomes.clear()
        summary = extractive_summary(self.messages, tool_outcomes)
        if not audit_loaded:
            summary = summary[:3900] + " Tool execution statuses could not be loaded."
        for attempt in range(2):
            try:
                async with asyncio.timeout(5):
                    async with self.database.session() as session, session.begin():
                        record = await CallRepository(session, self.context).finalize(
                            self.call_id,
                            ended_at=ended_at,
                            state=CallState.ERROR if error else CallState.ENDED,
                            summary=summary,
                            outcome="interrupted" if error else "call_ended",
                        )
                        if record is None:
                            raise ValueError("missing trusted call")
                return
            except Exception:
                if attempt:
                    raise


class AuditedExecutor:
    def __init__(
        self, gateway: ToolGateway, allowed: frozenset[str], durable: DurableCall | None
    ) -> None:
        self.gateway, self.allowed, self.durable = gateway, allowed, durable

    async def execute(
        self, context: TenantContext, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        durable = self.durable
        execution_id: UUID | None = None
        if durable:
            if context != durable.context:
                raise ToolError("denied")
            async with asyncio.timeout(5):
                async with durable.database.session() as session, session.begin():
                    row = await CallRepository(session, context).start_tool(durable.call_id, name)
                    if row is None:
                        raise ToolError("unavailable")
                    execution_id = row.id
        status: ToolStatus = "unknown"
        code: str | None = None
        try:
            result = await self.gateway.execute(
                context, name, arguments, allowed_tools=self.allowed
            )
            status = "succeeded"
            return result
        except asyncio.CancelledError:
            status, code = "cancelled", "cancelled"
            raise
        except ToolError as error:
            status, code = "failed", error.code
            raise
        except Exception:
            status, code = "unknown", "unavailable"
            raise ToolError("unavailable") from None
        finally:
            if durable and execution_id:

                async def finish() -> None:
                    async with asyncio.timeout(5):
                        async with durable.database.session() as session, session.begin():
                            await CallRepository(session, context).finish_tool(
                                execution_id, status, error_code=code
                            )

                task = asyncio.create_task(finish())
                cancelled = False
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        cancelled = True
                await task
                if cancelled:
                    raise asyncio.CancelledError
