"""Synthetic content reproducing the operator-observed 9Router event structure."""

import httpx
import pytest

from tests.llm.test_providers import MESSAGES, context, sse
from tests.llm.test_sse_diagnostic import Stream
from tests.llm.test_tools import TOOLS, tool_parts
from vasa.llm import LLMError, OpenAIProvider


def chunk(content=None, *, reason=None, index=0):
    return sse(
        {
            "choices": [
                {
                    "index": index,
                    "delta": {} if content is None else {"content": content},
                    "finish_reason": reason,
                }
            ],
            **({"usage": {"completion_tokens": 4}} if reason else {}),
        }
    )


async def collect(parts, *, tools=False):
    stream = Stream(parts)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
    ) as client:
        provider = OpenAIProvider(
            "fixture-only", http_client=client, tools=TOOLS if tools else None
        )
        try:
            return [event async for event in provider.respond(context(), MESSAGES)]
        finally:
            await provider.aclose()
            assert stream.closed


@pytest.mark.parametrize("done", [False, True])
async def test_observed_gateway_terminal_structure_and_standard_done(done):
    parts = [chunk("Hello"), chunk(" there."), chunk(reason="stop")]
    if done:
        parts.append(sse("[DONE]"))
    assert await collect(parts) == [
        {"type": "text", "text": "Hello"},
        {"type": "text", "text": " there."},
    ]


@pytest.mark.parametrize("done", [False, True])
async def test_complete_tools_share_finalization(done):
    parts = tool_parts("openai")
    assert await collect(parts if done else parts[:-1], tools=True) == [
        {
            "type": "tool_call",
            "id": "call_1",
            "name": "knowledge_search",
            "arguments": {"query": "hours"},
        }
    ]


@pytest.mark.parametrize("done", [False, True])
@pytest.mark.parametrize("arguments", ['{"query":', '{"query":"hours"', "[]"])
async def test_incomplete_or_invalid_tool_arguments_rejected(done, arguments):
    parts = tool_parts("openai", arguments)
    with pytest.raises(LLMError):
        await collect(parts if done else parts[:-1], tools=True)


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [chunk("hello")],
        [chunk("hello"), chunk(reason="tool_calls")],
        [chunk("hello"), chunk(reason="unsupported")],
        [chunk("hello"), chunk(reason="stop", index="0")],
        [chunk("hello"), chunk(reason="stop", index=True)],
        [chunk("hello"), chunk(reason="stop", index=1)],
        [chunk(reason="stop"), chunk("after finish")],
        [chunk(reason="stop"), chunk(reason="stop")],
        [chunk(reason="stop"), b'data: {"choices": invalid}\n\n'],
        [chunk("hello"), chunk(reason="stop").rstrip(b"\n")],
        [chunk(reason="stop"), b'data: {"choices": []}'],
        [sse({"choices": [{"index": 0, "delta": None, "finish_reason": "stop"}]})],
        [sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}] * 2})],
    ],
)
async def test_invalid_or_unfinished_eof_rejected(parts):
    with pytest.raises(LLMError):
        await collect(parts)


async def test_eof_before_tool_terminal_rejected():
    with pytest.raises(LLMError):
        await collect(tool_parts("openai")[:2], tools=True)


async def test_usage_only_after_terminal_before_clean_eof():
    parts = [chunk("hello"), chunk(reason="stop"), sse({"choices": [], "usage": {}})]
    assert await collect(parts) == [{"type": "text", "text": "hello"}]


async def test_limits_still_apply_after_terminal():
    with pytest.raises(LLMError, match="output_limit"):
        await collect([chunk(reason="stop"), b":" + b"x" * 16385 + b"\n\n"])


@pytest.mark.parametrize("field", ["id", "name"])
async def test_tool_identity_must_be_valid_at_eof(field):
    parts = tool_parts("openai")[:-1]
    if field == "id":
        parts[0] = parts[0].replace(b'"call_1"', b'""')
    else:
        parts[0] = parts[0].replace(b'"knowledge_search"', b'"unapproved_tool"')
    with pytest.raises(LLMError):
        await collect(parts, tools=True)


async def test_transport_error_after_terminal_is_not_clean_eof():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield chunk(reason="stop")
            raise httpx.ReadError("fixture disconnect")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=BrokenStream()
            )
        )
    ) as client:
        provider = OpenAIProvider("fixture-only", http_client=client)
        with pytest.raises(LLMError, match="unavailable"):
            _ = [event async for event in provider.respond(context(), MESSAGES)]
