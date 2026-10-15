import asyncio
import json
from dataclasses import replace
from typing import cast
from uuid import uuid4

import httpx
import pytest

from vasa.contracts.models import CallSession, CallState, TenantContext
from vasa.contracts.providers import EvolutionClient
from vasa.storage.cache import CallRegistry
from vasa.tools.concrete import (
    CustomWebhook,
    EndCall,
    KnowledgeMatch,
    KnowledgeSearch,
    WebhookAction,
)
from vasa.tools.gateway import ToolError, ToolPayload

ORIGIN = "https://hooks.example.com"


class ActionInput(ToolPayload):
    slot: str = "Tuesday"


class ActionOutput(ToolPayload):
    reference: str


def approved_action(url: str, token: str = "") -> WebhookAction:
    return WebhookAction(url, ActionInput, ActionOutput, token)


def context() -> TenantContext:
    return TenantContext(uuid4(), uuid4())


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/run",
        "https://other.example.com/run",
        "https://user:secret@hooks.example.com/run",
        "https://hooks.example.com/run?key=secret",
        "https://hooks.example.com/run#fragment",
        "https://hooks.example.com:8443/run",
        "https://127.0.0.1/run",
        "https://[::1]/run",
        "https://hooks.local/run",
        "https://hooks.example.com/\nrun",
        "https://hooks.example.com\\@other.example.com/run",
    ],
)
def test_destination_policy(url: str) -> None:
    with pytest.raises(ValueError, match="destination"):
        CustomWebhook(uuid4(), {"book": approved_action(url)}, approved_origins=frozenset({ORIGIN}))


async def test_webhook_exact_destination_server_credentials_and_tenant_envelope() -> None:
    owner = context()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(b'{"reference":"synthetic-123"}'),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        action = approved_action(ORIGIN + "/run", "synthetic-secret")
        tool = CustomWebhook(
            owner.tenant_id,
            {"book": action},
            approved_origins=frozenset({ORIGIN}),
            http_client=client,
        )
        assert await tool.execute(owner, {"action": "book", "payload": {"slot": "Tuesday"}}) == {
            "result": {"reference": "synthetic-123"}
        }
        assert len(requests) == 1
        assert str(requests[0].url) == ORIGIN + "/run"
        assert requests[0].headers["authorization"] == "Bearer synthetic-secret"
        assert json.loads(requests[0].content) == {
            "tenant_id": str(owner.tenant_id),
            "payload": {"slot": "Tuesday"},
        }
        assert "synthetic-secret" not in repr(action)
        await tool.aclose()
        assert not client.is_closed
        with pytest.raises(ToolError, match="unavailable"):
            await tool.execute(owner, {"action": "book", "payload": {}})


@pytest.mark.parametrize(
    ("status", "headers", "body", "code"),
    [
        (302, {"location": "https://127.0.0.1/"}, b"", "unavailable"),
        (500, {}, b"secret upstream message", "unavailable"),
        (200, {"content-type": "text/html"}, b"<html/>", "invalid_output"),
        (200, {"content-type": "application/json"}, b"[]", "invalid_output"),
        (200, {"content-type": "application/json"}, b'{"x":NaN}', "invalid_output"),
        (200, {"content-type": "application/json"}, b"not json", "invalid_output"),
        (200, {"content-type": "application/json"}, b'{"reference":123}', "invalid_output"),
        (
            200,
            {"content-type": "application/json"},
            b'{"reference":"ok","secret":"extra"}',
            "invalid_output",
        ),
        (200, {"content-type": "application/json"}, b" " * 32769, "invalid_output"),
        (
            200,
            {"content-type": "application/json", "content-encoding": "gzip"},
            b"unused",
            "invalid_output",
        ),
    ],
)
async def test_webhook_response_limits_and_no_redirect_or_retry(
    status: int, headers: dict[str, str], body: bytes, code: str
) -> None:
    owner = context()
    requests: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        result = httpx.Response(status, headers=headers, stream=httpx.ByteStream(body))
        responses.append(result)
        return result

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool = CustomWebhook(
            owner.tenant_id,
            {"book": approved_action(ORIGIN + "/run")},
            approved_origins=frozenset({ORIGIN}),
            http_client=client,
        )
        with pytest.raises(ToolError, match=f"^{code}$"):
            await tool.execute(owner, {"action": "book", "payload": {}})
        assert len(requests) == 1
        assert responses[0].is_closed


@pytest.mark.eval
async def test_webhook_ownership_action_and_url_injection_denied_before_network() -> None:
    owner = context()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("must not send")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool = CustomWebhook(
            owner.tenant_id,
            {"book": approved_action(ORIGIN + "/run")},
            approved_origins=frozenset({ORIGIN}),
            http_client=client,
        )
        with pytest.raises(ToolError, match="denied"):
            await tool.execute(context(), {"action": "book", "payload": {}})
        with pytest.raises(ToolError, match="denied"):
            await tool.execute(owner, {"action": "other", "payload": {}})
        with pytest.raises(ToolError, match="invalid_input"):
            await tool.execute(owner, {"action": "book", "payload": {}, "url": "attacker"})
        with pytest.raises(ToolError, match="invalid_input"):
            await tool.execute(owner, {"action": "book", "payload": {"tenant_id": "foreign"}})
        assert not requests


class Registry:
    def __init__(self, call: CallSession) -> None:
        self.call: CallSession | None = call

    async def get(self, owner: TenantContext, call_id: object) -> CallSession | None:
        assert call_id is not None
        return self.call


class Calls:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error = False

    async def hangup(self, instance_id: str, call_id: str) -> None:
        self.calls.append((instance_id, call_id))
        if self.error:
            raise RuntimeError("private Evolution key")


def end_tool() -> tuple[EndCall, TenantContext, Registry, Calls]:
    owner = context()
    call = CallSession(uuid4(), owner.tenant_id, "instance", "external", CallState.CONNECTED)
    registry, client = Registry(call), Calls()
    tool = EndCall(owner, call, cast(EvolutionClient, client), cast(CallRegistry, registry))
    return tool, owner, registry, client


async def test_end_call_bound_identity_idempotency_and_acknowledgment() -> None:
    tool, owner, _, client = end_tool()
    assert await tool.execute(owner, {}) == {"requested": True}
    assert await tool.execute(owner, {"reason": "finished"}) == {"requested": True}
    assert client.calls == [("instance", "external")]
    assert tool.end_requested.is_set()


@pytest.mark.eval
async def test_end_call_rejects_foreign_context_and_model_call_identifier() -> None:
    tool, owner, _, client = end_tool()
    for foreign in (context(), TenantContext(owner.tenant_id, uuid4())):
        with pytest.raises(ToolError, match="denied"):
            await tool.execute(foreign, {})
    with pytest.raises(ToolError, match="invalid_input"):
        await tool.execute(owner, {"call_id": "other"})
    assert not client.calls


@pytest.mark.parametrize("state", [CallState.ENDED, CallState.ERROR, CallState.RINGING])
async def test_end_call_rejects_stale_state(state: CallState) -> None:
    tool, owner, registry, client = end_tool()
    assert registry.call is not None
    registry.call = replace(registry.call, state=state)
    with pytest.raises(ToolError, match="denied"):
        await tool.execute(owner, {})
    assert not client.calls


async def test_end_call_rejects_expired_or_rebound_session() -> None:
    tool, owner, registry, client = end_tool()
    assert registry.call is not None
    registry.call = replace(registry.call, external_call_id="foreign")
    with pytest.raises(ToolError, match="denied"):
        await tool.execute(owner, {})
    registry.call = None
    with pytest.raises(ToolError, match="denied"):
        await tool.execute(owner, {})
    assert not client.calls


async def test_end_call_failure_does_not_claim_acknowledgment() -> None:
    tool, owner, _, client = end_tool()
    client.error = True
    with pytest.raises(ToolError, match="^unavailable$"):
        await tool.execute(owner, {})
    assert not tool.end_requested.is_set()
    assert len(client.calls) == 1


class Retriever:
    def __init__(self, matches: list[KnowledgeMatch]) -> None:
        self.matches = matches
        self.calls: list[tuple[TenantContext, str, int]] = []

    async def search(self, owner: TenantContext, query: str, top_k: int) -> list[KnowledgeMatch]:
        self.calls.append((owner, query, top_k))
        return self.matches


@pytest.mark.eval
async def test_knowledge_contract_forwards_trusted_context_and_rejects_foreign_matches() -> None:
    owner = context()
    match = KnowledgeMatch(
        tenant_id=str(owner.tenant_id),
        source_id=str(uuid4()),
        chunk_id=str(uuid4()),
        text="Synthetic opening hours",
        score=0.9,
    )
    retriever = Retriever([match])
    tool = KnowledgeSearch(owner.tenant_id, retriever)
    assert await tool.execute(owner, {"query": "hours", "top_k": 1}) == {
        "matches": [match.model_dump()]
    }
    assert retriever.calls == [(owner, "hours", 1)]
    retriever.matches = [match.model_copy(update={"tenant_id": str(uuid4())})]
    with pytest.raises(ToolError, match="^invalid_output$"):
        await tool.execute(owner, {"query": "hours"})


async def test_knowledge_without_backend_fails_closed_and_bounds_top_k() -> None:
    owner = context()
    tool = KnowledgeSearch(owner.tenant_id)
    with pytest.raises(ToolError, match="unavailable"):
        await tool.execute(owner, {"query": "hours"})
    with pytest.raises(ToolError, match="invalid_input"):
        await tool.execute(owner, {"query": "hours", "top_k": 6})
    with pytest.raises(ToolError, match="denied"):
        await tool.execute(context(), {"query": "hours"})


async def test_webhook_cancellation_releases_response_stream() -> None:
    started, closed = asyncio.Event(), asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"unused"

        async def aclose(self) -> None:
            closed.set()

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=Stream())

    owner = context()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool = CustomWebhook(
            owner.tenant_id,
            {"book": approved_action(ORIGIN + "/run")},
            approved_origins=frozenset({ORIGIN}),
            http_client=client,
        )
        task = asyncio.create_task(tool.execute(owner, {"action": "book", "payload": {}}))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
