from collections.abc import AsyncGenerator
from typing import Any

from vasa.contracts.models import TenantContext
from vasa.contracts.providers import LLMProvider
from vasa.llm.common import LLMError, TextBudget, validate_context


def _event(event: dict[str, Any], budget: TextBudget, allow_tools: bool = False) -> dict[str, Any]:
    if allow_tools and isinstance(event, dict) and event.get("type") == "tool_call":
        if set(event) != {"type", "id", "name", "arguments"}:
            raise LLMError("invalid_response")
        return event
    if not isinstance(event, dict) or event.get("type") != "text":
        raise LLMError("tool_output")
    if set(event) != {"type", "text"}:
        raise LLMError("invalid_response")
    return budget.event(event["text"]) or {"type": "text", "text": ""}


class FallbackProvider:
    def __init__(
        self, primary: LLMProvider, fallback: LLMProvider, *, allow_tools: bool = False
    ) -> None:
        self.allow_tools = allow_tools
        self.primary, self.fallback = primary, fallback

    async def respond(
        self, context: TenantContext, messages: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        snapshot = validate_context(context, messages, allow_tools=self.allow_tools)
        emitted = False
        budget = TextBudget()
        try:
            stream = self.primary.respond(context, [dict(item) for item in snapshot])
            try:
                async for event in stream:
                    checked = _event(event, budget, self.allow_tools)
                    emitted = True
                    yield checked
            finally:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
            return
        except LLMError as error:
            if emitted or error.code in {
                "invalid_context",
                "tool_output",
                "refused",
                "output_limit",
            }:
                raise
        stream = self.fallback.respond(context, [dict(item) for item in snapshot])
        try:
            async for event in stream:
                yield _event(event, budget, self.allow_tools)
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
