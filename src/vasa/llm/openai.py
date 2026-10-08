from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

import httpx

from vasa.contracts.models import TenantContext
from vasa.llm.common import LLMError, TextBudget, client_settings, validate_context
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
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client, self._owned = client_settings(
            api_key, model, base_url, max_output_tokens, timeout_seconds, http_client
        )
        self._api_key, self._model = api_key, model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._tokens, self._timeout = max_output_tokens, timeout_seconds
        self._closed = False

    async def aclose(self) -> None:
        self._closed = True
        if self._owned:
            await self._client.aclose()

    async def respond(
        self, context: TenantContext, messages: list[dict[str, str]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        snapshot = validate_context(context, messages)
        if self._closed:
            raise LLMError("unavailable")
        budget, finished = TextBudget(), False
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
            },
            self._timeout,
        )
        async with aclosing(events):
            async for event in events:
                if event.data == "[DONE]":
                    if not finished:
                        raise LLMError("invalid_response")
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
                if delta.get("tool_calls") or delta.get("function_call"):
                    raise LLMError("tool_output")
                if delta.get("refusal"):
                    raise LLMError("refused")
                if "role" in delta and delta["role"] != "assistant":
                    raise LLMError("invalid_response")
                reason = choice.get("finish_reason")
                if reason is not None and not isinstance(reason, str):
                    raise LLMError("invalid_response")
                if reason in {"tool_calls", "function_call"}:
                    raise LLMError("tool_output")
                if reason == "length":
                    raise LLMError("output_limit")
                if reason == "content_filter":
                    raise LLMError("refused")
                if reason not in {None, "stop"} or finished:
                    raise LLMError("invalid_response")
                finished = reason == "stop"
                content = delta.get("content")
                if content is not None:
                    output = budget.event(content)
                    if output:
                        yield output
        raise LLMError("invalid_response")
