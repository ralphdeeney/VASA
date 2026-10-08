from collections.abc import AsyncGenerator
from typing import Any

from vasa.contracts.models import TenantContext
from vasa.contracts.providers import LLMProvider
from vasa.llm.common import LLMError, TextBudget, validate_context


def _event(event: dict[str, Any], budget: TextBudget) -> dict[str, Any]:
    if not isinstance(event, dict) or event.get("type") != "text":
        raise LLMError("tool_output")
    if set(event) != {"type", "text"}:
        raise LLMError("invalid_response")
    return budget.event(event["text"]) or {"type": "text", "text": ""}


class FallbackProvider:
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self.primary, self.fallback = primary, fallback

    async def respond(
        self, context: TenantContext, messages: list[dict[str, str]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        snapshot = validate_context(context, messages)
        emitted = False
        budget = TextBudget()
        try:
            stream = self.primary.respond(context, [dict(item) for item in snapshot])
            try:
                async for event in stream:
                    checked = _event(event, budget)
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
                yield _event(event, budget)
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
