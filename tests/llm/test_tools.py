"""Tool stream/continuation contracts using HTTP fixtures, not live provider evidence."""

import json
from typing import Any

import pytest

from tests.llm.conftest import Plan, SSEServer
from tests.llm.test_providers import MESSAGES, anthropic_event, context, sse
from vasa.llm import AnthropicProvider, LLMError, OpenAIProvider
from vasa.llm.common import validate_context

TOOLS = [
    {
        "name": "knowledge_search",
        "description": "Search approved knowledge.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
            "required": ["query"],
        },
    }
]


def tool_parts(kind: str, arguments: str = '{"query":"hours"}') -> list[bytes]:
    if kind == "openai":
        return [
            sse(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "knowledge_search",
                                            "arguments": arguments[:8],
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            sse(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": arguments[8:]}}
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}),
            sse("[DONE]"),
        ]
    return [
        anthropic_event("message_start", message={"role": "assistant", "content": []}),
        anthropic_event(
            "content_block_start",
            index=0,
            content_block={
                "type": "tool_use",
                "id": "call_1",
                "name": "knowledge_search",
                "input": {},
            },
        ),
        anthropic_event(
            "content_block_delta",
            index=0,
            delta={"type": "input_json_delta", "partial_json": arguments[:8]},
        ),
        anthropic_event(
            "content_block_delta",
            index=0,
            delta={"type": "input_json_delta", "partial_json": arguments[8:]},
        ),
        anthropic_event("content_block_stop", index=0),
        anthropic_event("message_delta", delta={"stop_reason": "tool_use"}),
        anthropic_event("message_stop"),
    ]


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
async def test_tool_stream_and_protocol_valid_continuation(
    sse_server: SSEServer, kind: str
) -> None:
    sse_server.plans.extend([Plan(tool_parts(kind)), Plan(tool_parts(kind))])
    cls = OpenAIProvider if kind == "openai" else AnthropicProvider
    provider = cls("fixture-key", base_url=sse_server.url, tools=TOOLS)
    try:
        assert [event async for event in provider.respond(context(), MESSAGES)] == [
            {
                "type": "tool_call",
                "id": "call_1",
                "name": "knowledge_search",
                "arguments": {"query": "hours"},
            }
        ]
        messages: list[dict[str, Any]] = [
            *MESSAGES,
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "prior",
                        "type": "function",
                        "function": {"name": "knowledge_search", "arguments": '{"query":"hours"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "prior", "content": '{"matches":[]}'},
        ]
        _ = [event async for event in provider.respond(context(), messages)]
        body = sse_server.requests[-1]["body"]
        assert body["tools"]
        if kind == "openai":
            assert body["messages"] == messages
        else:
            assert body["messages"][-1]["role"] == "user"
            assert body["messages"][-1]["content"][0]["type"] == "tool_result"
            assert body["messages"][-2]["content"][0]["type"] == "tool_use"
    finally:
        await provider.aclose()


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("arguments", ['{"query":NaN}', "[]", '{"query":'])
async def test_bad_tool_arguments_fail_before_event(
    sse_server: SSEServer, kind: str, arguments: str
) -> None:
    sse_server.plans.append(Plan(tool_parts(kind, arguments)))
    cls = OpenAIProvider if kind == "openai" else AnthropicProvider
    provider = cls("fixture-key", base_url=sse_server.url, tools=TOOLS)
    try:
        with pytest.raises(LLMError, match="invalid_response"):
            _ = [event async for event in provider.respond(context(), MESSAGES)]
    finally:
        await provider.aclose()


def test_unmatched_tool_result_and_unfinished_request_rejected() -> None:
    for message in [
        {"role": "tool", "tool_call_id": "unknown", "content": "{}"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "x", "type": "function", "function": {"name": "end_call", "arguments": "{}"}}
            ],
        },
    ]:
        with pytest.raises(LLMError, match="invalid_context"):
            validate_context(context(), [*MESSAGES, message], allow_tools=True)


def test_tool_specs_are_snapshotted_and_unknown_fields_fail() -> None:
    tools = json.loads(json.dumps(TOOLS))
    provider = OpenAIProvider("fixture-key", tools=tools)
    tools[0]["name"] = "mutated"
    assert provider._tools[0]["name"] == "knowledge_search"
    with pytest.raises(ValueError, match="tool specifications"):
        OpenAIProvider("fixture-key", tools=[{**TOOLS[0], "tenant_id": "injected"}])
