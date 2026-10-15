import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.llm.conftest import Plan, SSEServer
from vasa.contracts.models import TenantContext
from vasa.llm import AnthropicProvider, FallbackProvider, LLMError, OpenAIProvider

MESSAGES = [
    {"role": "system", "content": "Server business instructions."},
    {"role": "user", "content": "Hello"},
]


def context() -> TenantContext:
    return TenantContext(uuid4(), uuid4())


def sse(data: dict[str, Any] | str, event: str | None = None) -> bytes:
    value = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return ((f"event: {event}\n" if event else "") + "data: " + value + "\n\n").encode()


def openai_parts(text: str = "Hello") -> list[bytes]:
    return [
        sse({"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}),
        sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
        sse("[DONE]"),
    ]


def anthropic_event(kind: str, **values: Any) -> bytes:
    return sse({"type": kind, **values}, kind)


def anthropic_parts(text: str = "Hello") -> list[bytes]:
    return [
        anthropic_event("message_start", message={"role": "assistant", "content": []}),
        anthropic_event("content_block_start", index=0, content_block={"type": "text", "text": ""}),
        anthropic_event("content_block_delta", index=0, delta={"type": "text_delta", "text": text}),
        anthropic_event("content_block_stop", index=0),
        anthropic_event("message_delta", delta={"stop_reason": "end_turn"}),
        anthropic_event("message_stop"),
    ]


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_real_chunked_sse_unicode_request_contract_and_input_snapshot(
    sse_server: SSEServer,
    kind: str,
) -> None:
    parts = openai_parts("Hi 😊") if kind == "openai" else anthropic_parts("Hi 😊")
    wire = b"".join(parts)
    unicode_offset = wire.index("😊".encode())
    sse_server.plans.append(
        Plan(
            [
                wire[: unicode_offset + 1],
                wire[unicode_offset + 1 : unicode_offset + 3],
                wire[unicode_offset + 3 :],
            ]
        )
    )
    cls = OpenAIProvider if kind == "openai" else AnthropicProvider
    provider = cls("component-only-key", base_url=sse_server.url)
    messages = [dict(message) for message in MESSAGES]
    try:
        assert [event async for event in provider.respond(context(), messages)] == [
            {"type": "text", "text": "Hi 😊"}
        ]
        assert messages == MESSAGES
        request = sse_server.requests[0]
        assert request["body"]["stream"] is True
        assert "tools" not in request["body"] and "tenant_id" not in request["body"]
        if kind == "openai":
            assert request["path"] == "/v1/chat/completions"
            assert request["headers"]["authorization"] == "Bearer component-only-key"
            assert request["body"]["messages"] == MESSAGES
            assert request["body"]["model"] == "gpt-4o-mini"
            assert request["body"]["max_completion_tokens"] == 512
        else:
            assert request["path"] == "/v1/messages"
            assert request["headers"]["x-api-key"] == "component-only-key"
            assert request["headers"]["anthropic-version"] == "2023-06-01"
            assert request["body"]["system"] == MESSAGES[0]["content"]
            assert request["body"]["messages"] == MESSAGES[1:]
            assert request["body"]["model"] == "claude-sonnet-4-6"
            assert request["body"]["max_tokens"] == 512
    finally:
        await provider.aclose()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_text_arrives_before_stream_finishes_and_close_releases_socket(
    sse_server: SSEServer,
    kind: str,
) -> None:
    parts = openai_parts() if kind == "openai" else anthropic_parts()
    # Hold after the complete first textual delta; this catches HTTPX fixed-chunk buffering.
    first = 1 if kind == "openai" else 3
    plan = Plan([b"".join(parts[:first]), b"".join(parts[first:])], hold=asyncio.Event())
    sse_server.plans.append(plan)
    cls = OpenAIProvider if kind == "openai" else AnthropicProvider
    provider = cls("component-only-key", base_url=sse_server.url)
    stream = provider.respond(context(), MESSAGES)
    try:
        assert await asyncio.wait_for(anext(stream), timeout=2) == {"type": "text", "text": "Hello"}
        await stream.aclose()
        await asyncio.wait_for(plan.disconnected.wait(), timeout=2)
    finally:
        await stream.aclose()
        await provider.aclose()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_cancellation_while_waiting_for_first_delta_cleans_connection(
    sse_server: SSEServer,
    kind: str,
) -> None:
    plan = Plan([b": keepalive\n\n", b"ignored"], hold=asyncio.Event())
    sse_server.plans.append(plan)
    cls = OpenAIProvider if kind == "openai" else AnthropicProvider
    provider = cls("component-only-key", base_url=sse_server.url)
    stream = provider.respond(context(), MESSAGES)
    task = asyncio.create_task(anext(stream))
    try:
        for _ in range(100):
            if sse_server.requests:
                break
            await asyncio.sleep(0.01)
        assert len(sse_server.requests) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(plan.disconnected.wait(), timeout=2)
    finally:
        await stream.aclose()
        await provider.aclose()


@pytest.mark.parametrize(
    "status,code",
    [
        (429, "rate_limited"),
        (401, "authentication_failed"),
        (503, "unavailable"),
        (302, "unavailable"),
    ],
)
async def test_http_errors_are_sanitized_and_not_retried(
    sse_server: SSEServer,
    status: int,
    code: str,
) -> None:
    sse_server.plans.append(Plan([b"private-upstream-error-component-only-key"], status=status))
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url)
    try:
        with pytest.raises(LLMError) as failure:
            await anext(provider.respond(context(), MESSAGES))
        assert str(failure.value) == code
        assert len(sse_server.requests) == 1
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "parts,code",
    [
        ([b"data: {bad-json}\n\n"], "invalid_response"),
        ([b"data: \xff\n\n"], "invalid_response"),
        ([b"data: " + b"x" * 20000], "output_limit"),
        ([b"data: {}\n"], "invalid_response"),
        (
            [
                sse(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "unsafe", "tool_calls": [{}]},
                                "finish_reason": None,
                            }
                        ]
                    }
                )
            ],
            "tool_output",
        ),
        (
            [sse({"choices": [{"index": 0, "delta": {}, "finish_reason": {"bad": "shape"}}]})],
            "invalid_response",
        ),
        ([sse("[DONE]")], "invalid_response"),
    ],
)
async def test_malformed_bounded_stream_and_tools_fail_before_emission(
    sse_server: SSEServer,
    parts: list[bytes],
    code: str,
) -> None:
    sse_server.plans.append(Plan(parts))
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url)
    try:
        with pytest.raises(LLMError) as failure:
            await anext(provider.respond(context(), MESSAGES))
        assert failure.value.code == code
    finally:
        await provider.aclose()


async def test_cumulative_text_cap_is_enforced_across_deltas(sse_server: SSEServer) -> None:
    parts = openai_parts("a" * 5000)[:1] + openai_parts("b" * 5000)
    sse_server.plans.append(Plan(parts))
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url)
    stream = provider.respond(context(), MESSAGES)
    try:
        assert (await anext(stream))["text"] == "a" * 5000
        with pytest.raises(LLMError, match="output_limit"):
            await anext(stream)
    finally:
        await stream.aclose()
        await provider.aclose()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_total_deadline_and_wrong_content_type(sse_server: SSEServer, kind: str) -> None:
    cls = OpenAIProvider if kind == "openai" else AnthropicProvider
    for plan, code in [
        (Plan([b": hold\n\n", b"ignored"], hold=asyncio.Event()), "timeout"),
        (Plan([b"{}"], content_type="application/json"), "invalid_response"),
    ]:
        sse_server.plans.append(plan)
        provider = cls("component-only-key", base_url=sse_server.url, timeout_seconds=0.1)
        try:
            with pytest.raises(LLMError) as failure:
                await anext(provider.respond(context(), MESSAGES))
            assert failure.value.code == code
            await asyncio.wait_for(plan.disconnected.wait(), timeout=2)
        finally:
            await provider.aclose()


async def test_concurrent_calls_keep_tenant_messages_and_output_separate(
    sse_server: SSEServer,
) -> None:
    sse_server.plans.extend([Plan(openai_parts("A response")), Plan(openai_parts("B response"))])
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url)
    inputs = [
        [{"role": "user", "content": text}] for text in ("Tenant A private", "Tenant B private")
    ]

    async def collect(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        return [event async for event in provider.respond(context(), messages)]

    try:
        outputs = await asyncio.gather(*(collect(messages) for messages in inputs))
        assert {tuple(event["text"] for event in output) for output in outputs} == {
            ("A response",),
            ("B response",),
        }
        bodies = [request["body"]["messages"] for request in sse_server.requests]
        assert sorted(body[0]["content"] for body in bodies) == [
            "Tenant A private",
            "Tenant B private",
        ]
        assert all(len(body) == 1 for body in bodies)
    finally:
        await provider.aclose()


class StubProvider:
    def __init__(
        self, *, text: str | None = None, code: str | None = None, mutate: bool = False
    ) -> None:
        self.text, self.code, self.mutate = text, code, mutate
        self.calls = 0
        self.closed = False
        self.inputs: list[list[dict[str, str]]] = []

    async def respond(
        self, context: TenantContext, messages: list[dict[str, str]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        self.calls += 1
        self.inputs.append([dict(item) for item in messages])
        try:
            if self.mutate:
                messages[0]["content"] = "tampered"
            if self.text is not None:
                yield {"type": "text", "text": self.text}
            if self.code:
                raise LLMError(self.code)
        finally:
            self.closed = True


async def test_fallback_only_before_any_event_and_uses_clean_context_copy() -> None:
    primary = StubProvider(code="unavailable", mutate=True)
    alternate = StubProvider(text="Fallback response")
    messages = [dict(item) for item in MESSAGES]
    fallback = FallbackProvider(primary, alternate)
    assert [event async for event in fallback.respond(context(), messages)] == [
        {"type": "text", "text": "Fallback response"}
    ]
    assert messages == MESSAGES and alternate.inputs == [MESSAGES]
    assert primary.closed and alternate.closed
    primary = StubProvider(text="Already spoken", code="unavailable")
    alternate = StubProvider(text="Must not mix")
    stream = FallbackProvider(primary, alternate).respond(context(), MESSAGES)
    assert await anext(stream) == {"type": "text", "text": "Already spoken"}
    with pytest.raises(LLMError, match="unavailable"):
        await anext(stream)
    assert alternate.calls == 0 and primary.closed


@pytest.mark.parametrize("code", ["tool_output", "refused", "output_limit", "invalid_context"])
async def test_semantic_failures_do_not_trigger_provider_failover(code: str) -> None:
    primary, alternate = StubProvider(code=code), StubProvider(text="Wrong alternate")
    with pytest.raises(LLMError, match=code):
        await anext(FallbackProvider(primary, alternate).respond(context(), MESSAGES))
    assert alternate.calls == 0


async def test_injected_http_client_remains_caller_owned_and_provider_close_stops_requests() -> (
    None
):
    async with httpx.AsyncClient() as client:
        provider = OpenAIProvider("component-only-key", http_client=client)
        await provider.aclose()
        assert not client.is_closed
        with pytest.raises(LLMError, match="unavailable"):
            await anext(provider.respond(context(), MESSAGES))
