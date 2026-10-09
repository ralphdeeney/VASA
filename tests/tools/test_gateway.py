import asyncio
import logging
from typing import Any
from uuid import uuid4

import pytest
from pydantic import Field

from vasa.contracts.models import TenantContext
from vasa.logging import JsonFormatter
from vasa.tools.gateway import ToolBinding, ToolError, ToolGateway, ToolPayload


class Input(ToolPayload):
    query: str = Field(min_length=1, max_length=100)


class Output(ToolPayload):
    found: bool


class Handler:
    name = "knowledge_search"

    def __init__(self) -> None:
        self.calls: list[tuple[TenantContext, dict[str, Any]]] = []
        self.result: dict[str, Any] = {"found": True}
        self.error: Exception | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.cleaned = False

    async def execute(self, context: TenantContext, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((context, arguments))
        self.started.set()
        try:
            await self.release.wait()
            if self.error:
                raise self.error
            return self.result
        finally:
            self.cleaned = True


def configured(timeout: float = 1) -> tuple[ToolGateway, TenantContext, Handler]:
    gateway = ToolGateway(max_concurrency=1)
    context = TenantContext(uuid4(), uuid4())
    handler = Handler()
    gateway.register(ToolBinding(context.tenant_id, handler, Input, Output, timeout))
    return gateway, context, handler


async def invoke(
    gateway: ToolGateway, context: TenantContext, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    return await gateway.execute(
        context,
        "knowledge_search",
        arguments if arguments is not None else {"query": "opening hours"},
        allowed_tools=frozenset({"knowledge_search"}),
    )


async def test_validated_snapshot_and_output() -> None:
    gateway, context, handler = configured()
    arguments = {"query": "opening hours"}
    assert await invoke(gateway, context, arguments) == {"found": True}
    assert handler.calls == [(context, arguments)]
    assert handler.calls[0][1] is not arguments


@pytest.mark.parametrize("other_tenant", [True, False])
async def test_denied_before_handler(other_tenant: bool) -> None:
    gateway, context, handler = configured()
    if other_tenant:
        context = TenantContext(uuid4(), context.user_id)
    with pytest.raises(ToolError, match="^denied$"):
        await gateway.execute(
            context,
            handler.name,
            {"query": "private"},
            allowed_tools=frozenset({handler.name}) if other_tenant else frozenset(),
        )
    assert not handler.calls


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": 123},
        {"query": ""},
        {"query": "x" * 101},
        {"query": "x", "tenant_id": "foreign"},
        {"query": float("nan")},
        {"query": "\ud800"},
        {"query": "x" * 32769},
        {"query": [0] * 2049},
        {"query": 2**257},
        {"query": object()},
    ],
)
async def test_invalid_input_never_executes(arguments: dict[str, Any]) -> None:
    gateway, context, handler = configured()
    with pytest.raises(ToolError, match="^invalid_input$"):
        await invoke(gateway, context, arguments)
    assert not handler.calls


async def test_cycle_is_rejected() -> None:
    gateway, context, handler = configured()
    payload: dict[str, Any] = {}
    payload["query"] = payload
    with pytest.raises(ToolError, match="^invalid_input$"):
        await invoke(gateway, context, payload)
    assert not handler.calls


@pytest.mark.parametrize("result", [{}, {"found": "true"}, {"found": True, "secret": "x"}])
async def test_output_validation(result: dict[str, Any]) -> None:
    gateway, context, handler = configured()
    handler.result = result
    with pytest.raises(ToolError, match="^invalid_output$"):
        await invoke(gateway, context)
    handler.result = {"found": True}
    assert await invoke(gateway, context) == handler.result


async def test_timeout_cleans_and_releases_capacity() -> None:
    gateway, context, handler = configured(0.02)
    handler.release.clear()
    with pytest.raises(ToolError, match="^timeout$"):
        await invoke(gateway, context)
    assert handler.cleaned
    handler.release.set()
    assert await invoke(gateway, context) == {"found": True}


async def test_busy_and_cancellation_release_capacity() -> None:
    gateway, context, handler = configured()
    handler.release.clear()
    task = asyncio.create_task(invoke(gateway, context))
    await asyncio.wait_for(handler.started.wait(), timeout=1)
    try:
        with pytest.raises(ToolError, match="^busy$"):
            await invoke(gateway, context)
        assert len(handler.calls) == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert handler.cleaned
    handler.release.set()
    assert await invoke(gateway, context) == {"found": True}


@pytest.mark.parametrize("error", [RuntimeError("private token"), ToolError("private token")])
async def test_exception_sanitization_and_audit(
    error: Exception, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, context, handler = configured()
    handler.error = error
    # Production disables propagation on vasa; capture this logger directly.
    tool_logger = logging.getLogger("vasa.tools")
    monkeypatch.setattr(tool_logger, "handlers", [caplog.handler])
    monkeypatch.setattr(tool_logger, "propagate", False)
    with caplog.at_level(logging.INFO, logger="vasa.tools"):
        with pytest.raises(ToolError, match="^unavailable$"):
            await invoke(gateway, context, {"query": "private transcript"})
    records = [record for record in caplog.records if record.name == "vasa.tools"]
    assert len(records) == 1
    formatted = JsonFormatter().format(records[0])
    assert '"event": "tool_failed"' in formatted
    assert "private" not in formatted
    assert str(context.tenant_id) not in formatted


def test_duplicate_registration_and_bad_configuration() -> None:
    gateway, context, handler = configured()
    with pytest.raises(ValueError):
        gateway.register(ToolBinding(context.tenant_id, handler, Input, Output))
    for timeout in (0, 31, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ToolGateway().register(ToolBinding(context.tenant_id, handler, Input, Output, timeout))
    with pytest.raises(ValueError):
        ToolGateway(max_concurrency=True)


async def test_same_name_isolated_between_tenants() -> None:
    gateway, context, first = configured()
    second_context = TenantContext(uuid4(), uuid4())
    second = Handler()
    second.result = {"found": False}
    gateway.register(ToolBinding(second_context.tenant_id, second, Input, Output))
    assert await invoke(gateway, context) == {"found": True}
    assert await invoke(gateway, second_context) == {"found": False}
    assert first.calls[0][0] == context
    assert second.calls[0][0] == second_context
