import asyncio

import pytest

from tests.llm.conftest import Plan, SSEServer
from tests.llm.test_providers import (
    MESSAGES,
    anthropic_event,
    anthropic_parts,
    context,
    openai_parts,
    sse,
)
from vasa.llm import AnthropicProvider, FallbackProvider, LLMError, OpenAIProvider


@pytest.mark.parametrize("ending", [b"\r", b"\r\n"])
async def test_sse_cr_and_split_crlf_dispatch_text_without_waiting_for_completion(
    sse_server: SSEServer,
    ending: bytes,
) -> None:
    parts = [part.replace(b"\n", ending) for part in openai_parts()]
    # Split CRLF across HTTP chunks to exercise delimiter state and blank-line dispatch.
    if ending == b"\r\n":
        first = [parts[0][:-1], parts[0][-1:]]
    else:
        first = [parts[0]]
    hold = asyncio.Event()
    plan = Plan(first + parts[1:], hold=hold if ending == b"\r" else None)
    sse_server.plans.append(plan)
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url)
    stream = provider.respond(context(), MESSAGES)
    try:
        assert await asyncio.wait_for(anext(stream), 2) == {"type": "text", "text": "Hello"}
        hold.set()
        assert [event async for event in stream] == []
    finally:
        await stream.aclose()
        await provider.aclose()


async def test_sse_bom_comments_multiline_json_and_retry_field(sse_server: SSEServer) -> None:
    first = (
        b'\xef\xbb\xbf: keepalive\nretry: 1\ndata: {\ndata: "choices": '
        b'[{"index": 0, "delta": {"content": "Hello"}, "finish_reason": null}]\n'
        b"data: }\n\n"
    )
    sse_server.plans.append(Plan([first] + openai_parts()[1:]))
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url)
    try:
        assert [event async for event in provider.respond(context(), MESSAGES)] == [
            {"type": "text", "text": "Hello"}
        ]
        assert len(sse_server.requests) == 1
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "parts,code",
    [
        ([b"data: " + b"a" * 12000 + b"\n"] * 3 + [b"\n"], "output_limit"),
        ([b":" + b"a" * 100 + b"\n"] * 1400, "output_limit"),
        (
            [sse({"choices": [{"index": 0, "delta": {}, "finish_reason": None}]})] * 1025,
            "output_limit",
        ),
        ([b"data: " + b'{"a":' * 1200 + b"null" + b"}" * 1200 + b"\n\n"], "invalid_response"),
        (
            [
                b'data: {"choices": [{"index":0,"delta":{"content":"\\ud800"},'
                b'"finish_reason":null}]}\n\n'
            ],
            "invalid_response",
        ),
    ],
)
async def test_stream_event_line_count_and_unicode_bounds(
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


@pytest.mark.parametrize(
    "events,code",
    [
        (
            [
                anthropic_event(
                    "error",
                    error={"type": "overloaded_error", "message": "credential-bearing-text"},
                )
            ],
            "unavailable",
        ),
        (
            [anthropic_event("error", error={"type": "rate_limit_error", "message": "private"})],
            "rate_limited",
        ),
        (
            anthropic_parts()[:1]
            + [
                anthropic_event(
                    "content_block_start",
                    index=0,
                    content_block={
                        "type": "tool_use",
                        "id": "tool-id",
                        "name": "unapproved",
                        "input": {},
                    },
                )
            ],
            "tool_output",
        ),
        (
            anthropic_parts()[:2]
            + [
                anthropic_event(
                    "content_block_delta", index=[], delta={"type": "text_delta", "text": "unsafe"}
                )
            ],
            "invalid_response",
        ),
        (
            anthropic_parts()[:2]
            + [
                anthropic_event(
                    "content_block_delta",
                    index=0,
                    delta={"type": "input_json_delta", "partial_json": "{}"},
                )
            ],
            "tool_output",
        ),
        ([anthropic_event("message_stop")], "invalid_response"),
    ],
)
async def test_anthropic_errors_tools_and_invalid_lifecycle_fail_closed(
    sse_server: SSEServer,
    events: list[bytes],
    code: str,
) -> None:
    sse_server.plans.append(Plan(events))
    provider = AnthropicProvider("component-only-key", base_url=sse_server.url)
    try:
        with pytest.raises(LLMError) as failure:
            await anext(provider.respond(context(), MESSAGES))
        assert str(failure.value) == code
    finally:
        await provider.aclose()


async def test_future_anthropic_event_is_ignored_within_stream_bounds(
    sse_server: SSEServer,
) -> None:
    parts = anthropic_parts()
    sse_server.plans.append(
        Plan(parts[:1] + [anthropic_event("future_event", extra="metadata")] + parts[1:])
    )
    provider = AnthropicProvider("component-only-key", base_url=sse_server.url)
    try:
        assert [event async for event in provider.respond(context(), MESSAGES)] == [
            {"type": "text", "text": "Hello"}
        ]
    finally:
        await provider.aclose()


async def test_real_http_failover_before_text_uses_alternate_api(sse_server: SSEServer) -> None:
    sse_server.plans.extend(
        [Plan([b"private upstream body"], status=429), Plan(anthropic_parts("Alternate result"))]
    )
    primary = OpenAIProvider("component-only-key", base_url=sse_server.url)
    alternate = AnthropicProvider("component-only-key", base_url=sse_server.url)
    try:
        assert [
            event
            async for event in FallbackProvider(primary, alternate).respond(context(), MESSAGES)
        ] == [{"type": "text", "text": "Alternate result"}]
        assert [request["path"] for request in sse_server.requests] == [
            "/v1/chat/completions",
            "/v1/messages",
        ]
    finally:
        await primary.aclose()
        await alternate.aclose()


async def test_broken_real_stream_after_text_does_not_mix_alternate_output(
    sse_server: SSEServer,
) -> None:
    sse_server.plans.append(Plan(openai_parts("Already spoken")[:1], abruptly_close=True))
    primary = OpenAIProvider("component-only-key", base_url=sse_server.url)
    alternate = AnthropicProvider("component-only-key", base_url=sse_server.url)
    stream = FallbackProvider(primary, alternate).respond(context(), MESSAGES)
    try:
        assert await anext(stream) == {"type": "text", "text": "Already spoken"}
        with pytest.raises(LLMError, match="unavailable"):
            await anext(stream)
        assert len(sse_server.requests) == 1
    finally:
        await stream.aclose()
        await primary.aclose()
        await alternate.aclose()


async def test_io_deadline_does_not_cancel_consumer_while_speech_is_running(
    sse_server: SSEServer,
) -> None:
    parts = openai_parts()
    plan = Plan([parts[0], b"".join(parts[1:])], hold=asyncio.Event())
    sse_server.plans.append(plan)
    provider = OpenAIProvider("component-only-key", base_url=sse_server.url, timeout_seconds=0.1)
    stream = provider.respond(context(), MESSAGES)
    try:
        assert await anext(stream) == {"type": "text", "text": "Hello"}
        # Simulated consumer work must survive the provider's expired I/O deadline.
        await asyncio.sleep(0.15)
        with pytest.raises(LLMError, match="timeout"):
            await anext(stream)
        await asyncio.wait_for(plan.disconnected.wait(), timeout=2)
    finally:
        await stream.aclose()
        await provider.aclose()
