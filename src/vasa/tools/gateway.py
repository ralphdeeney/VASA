import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from vasa.contracts.models import TenantContext
from vasa.contracts.providers import Tool

logger = logging.getLogger("vasa.tools")


class ToolError(Exception):
    """Fixed codes only: tool exceptions and payloads must never reach logs/clients."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ToolPayload(BaseModel):
    model_config = {"strict": True, "extra": "forbid", "allow_inf_nan": False}


@dataclass(frozen=True, slots=True)
class ToolBinding:
    tenant_id: UUID
    tool: Tool
    input_model: type[ToolPayload]
    output_model: type[ToolPayload]
    timeout_seconds: float = 10.0


def _snapshot(payload: object, code: str) -> dict[str, Any]:
    """Bound depth, node count and wire bytes before handing untrusted data to schemas."""
    remaining = 2048
    text_bytes = 32768

    def consume_text(value: str) -> None:
        nonlocal text_bytes
        if len(value) > 32768:
            raise ToolError(code)
        try:
            text_bytes -= len(value.encode("utf-8"))
        except UnicodeError:
            raise ToolError(code) from None
        if text_bytes < 0:
            raise ToolError(code)

    def visit(value: object, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise ToolError(code)
        if type(value) is dict:
            if len(value) > 2048:
                raise ToolError(code)
            for key, item in value.items():
                if type(key) is not str or len(key) > 32768:
                    raise ToolError(code)
                consume_text(key)
                visit(item, depth + 1)
        elif type(value) is list:
            if len(value) > 2048:
                raise ToolError(code)
            for item in value:
                visit(item, depth + 1)
        elif type(value) is str:
            consume_text(value)
        elif type(value) is float:
            if not math.isfinite(value):
                raise ToolError(code)
        elif type(value) is int:
            if value.bit_length() > 256:
                raise ToolError(code)
        elif value is not None and type(value) is not bool:
            raise ToolError(code)

    if type(payload) is not dict:
        raise ToolError(code)
    visit(payload, 0)
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > 32768:
            raise ToolError(code)
        result: dict[str, Any] = json.loads(encoded)
        return result
    except (ValueError, UnicodeError):
        raise ToolError(code) from None


class ToolGateway:
    """Server-owned registry and grants. Never populate either from model/browser input.

    Capacity is fail-fast; no unbounded waiting queue or automatic action retries.
    Handlers must use cancellation-safe async I/O with their own external deadlines.
    """

    def __init__(self, *, max_concurrency: int = 4) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 32:
            raise ValueError("invalid tool capacity")
        self._capacity = max_concurrency
        self._active = 0
        self._bindings: dict[tuple[UUID, str], ToolBinding] = {}

    def register(self, binding: ToolBinding) -> None:
        if (
            not isinstance(binding.tenant_id, UUID)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", binding.tool.name)
            or isinstance(binding.timeout_seconds, bool)
            or not math.isfinite(binding.timeout_seconds)
            or not 0 < binding.timeout_seconds <= 30
            or not issubclass(binding.input_model, ToolPayload)
            or not issubclass(binding.output_model, ToolPayload)
            or any(
                model.model_config.get("extra") != "forbid"
                or model.model_config.get("strict") is not True
                for model in (binding.input_model, binding.output_model)
            )
        ):
            raise ValueError("invalid tool binding")
        key = (binding.tenant_id, binding.tool.name)
        if key in self._bindings or len(self._bindings) >= 1024:
            raise ValueError("duplicate tool or registry full")
        self._bindings[key] = binding

    async def execute(
        self,
        context: TenantContext,
        name: str,
        arguments: dict[str, Any],
        *,
        allowed_tools: frozenset[str],
    ) -> dict[str, Any]:
        status = "failed"
        acquired = False
        try:
            if (
                not isinstance(context, TenantContext)
                or not isinstance(context.tenant_id, UUID)
                or not isinstance(context.user_id, UUID)
                or type(name) is not str
                or type(allowed_tools) is not frozenset
            ):
                raise ToolError("denied")
            binding = self._bindings.get((context.tenant_id, name))
            if binding is None or name not in allowed_tools:
                raise ToolError("denied")
            payload = _snapshot(arguments, "invalid_input")
            try:
                validated = binding.input_model.model_validate(payload, strict=True)
            except ValidationError:
                raise ToolError("invalid_input") from None
            if self._active >= self._capacity:
                raise ToolError("busy")
            self._active += 1
            acquired = True
            try:
                async with asyncio.timeout(binding.timeout_seconds):
                    output = await binding.tool.execute(context, validated.model_dump(mode="json"))
            except TimeoutError:
                raise ToolError("timeout") from None
            except Exception:
                raise ToolError("unavailable") from None
            result = _snapshot(output, "invalid_output")
            try:
                checked = binding.output_model.model_validate(result, strict=True)
            except ValidationError:
                raise ToolError("invalid_output") from None
            result = _snapshot(checked.model_dump(mode="json"), "invalid_output")
            status = "succeeded"
            return result
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            if acquired:
                self._active -= 1
            # Exactly one controlled event per attempt. Durable audit is Wave 7.
            logger.info("tool_attempt", extra={"event": f"tool_{status}"})
