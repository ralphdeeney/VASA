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


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        max_output_tokens: int = 512,
        timeout_seconds: float = 30.0,
        tools: list[dict[str, Any]] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client, self._owned = client_settings(
            api_key, model, base_url, max_output_tokens, timeout_seconds, http_client
        )
        self._api_key, self._model = api_key, model
        self._url = base_url.rstrip("/") + "/chat/completions"
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
        budget, finished = TextBudget(), False
        calls: dict[int, dict[str, str]] = {}

        def finalize() -> list[dict[str, Any]]:
            if not finished:
                raise LLMError("invalid_response")
            # Validate every call before emitting any tool event, for either terminator.
            return [
                tool_event(call["id"], call["name"], call["arguments"], self._approved)
                for call in calls.values()
            ]

        events = stream_events(
            self._client,
            self._url,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "text/event-stream",
                "Accept-Encoding": "identity",
            },
            {
                "model": self._model,
                "messages": snapshot,
                "max_completion_tokens": self._tokens,
                "stream": True,
                "n": 1,
                **(
                    {
                        "tools": [{"type": "function", "function": item} for item in self._tools],
                        "parallel_tool_calls": False,
                    }
                    if self._tools
                    else {}
                ),
            },
            self._timeout,
        )
        async with aclosing(events):
            async for event in events:
                if event.data == "[DONE]":
                    for output_event in finalize():
                        yield output_event
                    return
                data = event.json()
                if event.name == "error" or "error" in data:
                    raise LLMError("unavailable")
                choices = data.get("choices")
                if not isinstance(choices, list):
                    raise LLMError("invalid_response")
                if not choices and "usage" in data:
                    continue
                if len(choices) != 1 or not isinstance(choices[0], dict):
                    raise LLMError("invalid_response")
                choice = choices[0]
                if (
                    not isinstance(choice.get("index"), int)
                    or isinstance(choice.get("index"), bool)
                    or choice["index"] != 0
                ):
                    raise LLMError("invalid_response")
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    raise LLMError("invalid_response")
                if delta.get("function_call"):
                    raise LLMError("tool_output")
                if delta.get("tool_calls"):
                    if not self._tools:
                        raise LLMError("tool_output")
                    fragments = delta["tool_calls"]
                    if not isinstance(fragments, list) or len(fragments) > 16:
                        raise LLMError("invalid_response")
                    for fragment in fragments:
                        if not isinstance(fragment, dict):
                            raise LLMError("invalid_response")
                        index = fragment.get("index")
                        if (
                            not isinstance(index, int)
                            or isinstance(index, bool)
                            or not 0 <= index < 16
                        ):
                            raise LLMError("invalid_response")
                        call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        function = fragment.get("function", {})
                        if (
                            not isinstance(function, dict)
                            or fragment.get("type", "function") != "function"
                        ):
                            raise LLMError("invalid_response")
                        for key, value in (
                            ("id", fragment.get("id", "")),
                            ("name", function.get("name", "")),
                            ("arguments", function.get("arguments", "")),
                        ):
                            if not isinstance(value, str):
                                raise LLMError("invalid_response")
                            call[key] += value
                        if len(json.dumps(call)) > 32768:
                            raise LLMError("output_limit")
                if delta.get("refusal"):
                    raise LLMError("refused")
                if "role" in delta and delta["role"] != "assistant":
                    raise LLMError("invalid_response")
                reason = choice.get("finish_reason")
                if reason is not None and not isinstance(reason, str):
                    raise LLMError("invalid_response")
                if reason in {"tool_calls", "function_call"} and not self._tools:
                    raise LLMError("tool_output")
                if reason == "length":
                    raise LLMError("output_limit")
                if reason == "content_filter":
                    raise LLMError("refused")
                if reason not in {None, "stop", "tool_calls"} or finished:
                    raise LLMError("invalid_response")
                finished = reason in {"stop", "tool_calls"}
                if reason == "stop" and calls or reason == "tool_calls" and not calls:
                    raise LLMError("invalid_response")
                content = delta.get("content")
                if content is not None:
                    output = budget.event(content)
                    if output:
                        yield output
        # Some compatible gateways close cleanly after the terminal choice chunk.
        # The SSE iterator must exhaust successfully (including framing checks).
        for output_event in finalize():
            yield output_event
