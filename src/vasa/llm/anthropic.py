import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

import httpx

from vasa.contracts.models import TenantContext
from vasa.llm.common import (
    LLMError,
    TextBudget,
    client_settings,
    tool_event,
    tool_specs,
    validate_context,
)
from vasa.llm.sse import stream_events


class AnthropicProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-sonnet-4-6",
        base_url: str = "https://api.anthropic.com/v1",
        max_output_tokens: int = 512,
        timeout_seconds: float = 30.0,
        tools: list[dict[str, Any]] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client, self._owned = client_settings(
            api_key, model, base_url, max_output_tokens, timeout_seconds, http_client
        )
        self._api_key, self._model = api_key, model
        self._url = base_url.rstrip("/") + "/messages"
        self._tokens, self._timeout = max_output_tokens, timeout_seconds
        self._tools = tool_specs(tools)
        self._approved = {item["name"] for item in self._tools}
        self._closed = False

    async def aclose(self) -> None:
        self._closed = True
        if self._owned:
            await self._client.aclose()

    async def respond(
        self, context: TenantContext, messages: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        snapshot = validate_context(context, messages, allow_tools=bool(self._tools))
        if self._closed:
            raise LLMError("unavailable")
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._tokens,
            "stream": True,
            "messages": snapshot[1:] if snapshot[0]["role"] == "system" else snapshot,
        }
        if snapshot[0]["role"] == "system":
            payload["system"] = snapshot[0]["content"]
        if self._tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in self._tools
            ]
            converted: list[dict[str, Any]] = []
            for item in payload["messages"]:
                if item["role"] == "tool":
                    result_block = {
                        "type": "tool_result",
                        "tool_use_id": item["tool_call_id"],
                        "content": item["content"],
                    }
                    if (
                        converted
                        and converted[-1]["role"] == "user"
                        and isinstance(converted[-1]["content"], list)
                    ):
                        converted[-1]["content"].append(result_block)
                    else:
                        converted.append({"role": "user", "content": [result_block]})
                elif "tool_calls" in item:
                    content: list[dict[str, Any]] = []
                    if item["content"]:
                        content.append({"type": "text", "text": item["content"]})
                    for call in item["tool_calls"]:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": call["id"],
                                "name": call["function"]["name"],
                                "input": json.loads(call["function"]["arguments"]),
                            }
                        )
                    converted.append({"role": "assistant", "content": content})
                else:
                    converted.append(item)
            payload["messages"] = converted
        calls: dict[int, dict[str, str]] = {}
        started, finished, blocks = False, False, set[int]()
        seen_blocks: set[int] = set()
        budget = TextBudget()
        events = stream_events(
            self._client,
            self._url,
            {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Accept": "text/event-stream",
                "Accept-Encoding": "identity",
            },
            payload,
            self._timeout,
        )
        async with aclosing(events):
            async for event in events:
                data = event.json()
                kind = data.get("type")
                if event.name != kind:
                    raise LLMError("invalid_response")
                if kind == "error":
                    error = data.get("error")
                    code = error.get("type") if isinstance(error, dict) else None
                    raise LLMError("rate_limited" if code == "rate_limit_error" else "unavailable")
                if kind == "ping":
                    continue
                if kind == "message_start":
                    message = data.get("message")
                    if (
                        started
                        or not isinstance(message, dict)
                        or message.get("role") != "assistant"
                    ):
                        raise LLMError("invalid_response")
                    if message.get("content") != []:
                        raise LLMError("invalid_response")
                    started = True
                elif kind == "content_block_start":
                    index, block = data.get("index"), data.get("content_block")
                    if (
                        not started
                        or finished
                        or not isinstance(index, int)
                        or isinstance(index, bool)
                        or index in blocks
                        or index in seen_blocks
                        or not 0 <= index < 16
                    ):
                        raise LLMError("invalid_response")
                    if not isinstance(block, dict):
                        raise LLMError("invalid_response")
                    if block.get("type") == "tool_use":
                        if not self._tools:
                            raise LLMError("tool_output")
                        if (
                            block.get("input") != {}
                            or not isinstance(block.get("id"), str)
                            or not isinstance(block.get("name"), str)
                        ):
                            raise LLMError("invalid_response")
                        calls[index] = {"id": block["id"], "name": block["name"], "arguments": ""}
                        blocks.add(index)
                        seen_blocks.add(index)
                        continue
                    if block.get("type") != "text":
                        raise LLMError("invalid_response")
                    blocks.add(index)
                    seen_blocks.add(index)
                    output = budget.event(block.get("text"))
                    if output:
                        yield output
                elif kind == "content_block_delta":
                    index, delta = data.get("index"), data.get("delta")
                    if (
                        not started
                        or finished
                        or not isinstance(index, int)
                        or isinstance(index, bool)
                        or index not in blocks
                        or not isinstance(delta, dict)
                    ):
                        raise LLMError("invalid_response")
                    if delta.get("type") == "input_json_delta":
                        if not self._tools:
                            raise LLMError("tool_output")
                        fragment = delta.get("partial_json")
                        if index not in calls or not isinstance(fragment, str):
                            raise LLMError("invalid_response")
                        calls[index]["arguments"] += fragment
                        if len(calls[index]["arguments"].encode()) > 32768:
                            raise LLMError("output_limit")
                        continue
                    if index in calls:
                        raise LLMError("invalid_response")
                    if delta.get("type") != "text_delta":
                        raise LLMError("invalid_response")
                    output = budget.event(delta.get("text"))
                    if output:
                        yield output
                elif kind == "content_block_stop":
                    index = data.get("index")
                    if not isinstance(index, int) or isinstance(index, bool) or index not in blocks:
                        raise LLMError("invalid_response")
                    blocks.remove(index)
                elif kind == "message_delta":
                    delta = data.get("delta")
                    if not started or finished or blocks or not isinstance(delta, dict):
                        raise LLMError("invalid_response")
                    reason = delta.get("stop_reason")
                    if not isinstance(reason, str):
                        raise LLMError("invalid_response")
                    if reason == "tool_use" and not self._tools:
                        raise LLMError("tool_output")
                    if reason == "max_tokens":
                        raise LLMError("output_limit")
                    if reason not in {"end_turn", "stop_sequence", "tool_use"}:
                        raise LLMError("invalid_response")
                    if (reason == "tool_use") != bool(calls):
                        raise LLMError("invalid_response")
                    finished = True
                elif kind == "message_stop":
                    if not started or not finished or blocks:
                        raise LLMError("invalid_response")
                    for call in calls.values():
                        yield tool_event(
                            call["id"], call["name"], call["arguments"] or "{}", self._approved
                        )
                    return
                # Anthropic documents future unknown event types: ignore within stream bounds.
        raise LLMError("invalid_response")
