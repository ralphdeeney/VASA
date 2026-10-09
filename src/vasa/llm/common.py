import copy
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from vasa.contracts.models import TenantContext

MAX_CONTEXT_BYTES = 32768
MAX_MESSAGES = 64
MAX_TEXT_CHARS = 8192


class LLMError(Exception):
    """Only fixed error codes reach callers; upstream bodies/messages are never exposed."""

    def __init__(self, code: str) -> None:
        self.code = (
            code
            if code
            in {
                "invalid_context",
                "invalid_response",
                "unavailable",
                "timeout",
                "rate_limited",
                "authentication_failed",
                "output_limit",
                "refused",
                "tool_output",
            }
            else "unavailable"
        )
        super().__init__(self.code)


def validate_context(
    context: TenantContext, messages: list[dict[str, Any]], *, allow_tools: bool = False
) -> list[dict[str, Any]]:
    """Snapshot caller-owned data; never retain conversational state on a shared provider."""
    if (
        not isinstance(context, TenantContext)
        or not isinstance(context.tenant_id, UUID)
        or not isinstance(context.user_id, UUID)
        or not isinstance(messages, list)
        or not 1 <= len(messages) <= MAX_MESSAGES
    ):
        raise LLMError("invalid_context")
    if allow_tools:
        return validate_tool_context(messages)
    copied: list[dict[str, Any]] = []
    size = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise LLMError("invalid_context")
        role, content = message["role"], message["content"]
        if (
            not isinstance(role, str)
            or role not in {"system", "user", "assistant"}
            or (role == "system" and index != 0)
            or not isinstance(content, str)
            or not content.strip()
            or len(content) > MAX_CONTEXT_BYTES
        ):
            raise LLMError("invalid_context")
        try:
            size += len(content.encode("utf-8")) + len(role)
        except UnicodeError:
            raise LLMError("invalid_context") from None
        if size > MAX_CONTEXT_BYTES:
            raise LLMError("invalid_context")
        copied.append({"role": role, "content": content})
    conversation = copied[1:] if copied[0]["role"] == "system" else copied
    if not conversation or conversation[0]["role"] != "user" or conversation[-1]["role"] != "user":
        raise LLMError("invalid_context")
    return copied


def client_settings(
    api_key: str,
    model: str,
    base_url: str,
    max_output_tokens: int,
    timeout_seconds: float,
    http_client: httpx.AsyncClient | None,
) -> tuple[httpx.AsyncClient, bool]:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        or not isinstance(api_key, str)
        or not api_key
        or len(api_key) > 4096
        or not api_key.isascii()
        or any(character.isspace() for character in api_key)
        or not isinstance(model, str)
        or not model
        or len(model) > 128
        or not model.isascii()
        or any(character.isspace() for character in model)
        or isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not 1 <= max_output_tokens <= 2048
        or not 0 < timeout_seconds <= 120
    ):
        raise ValueError("invalid LLM provider configuration")
    if http_client is not None:
        return http_client, False
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            timeout_seconds,
            connect=min(5, timeout_seconds),
            read=min(10, timeout_seconds),
            write=min(5, timeout_seconds),
            pool=min(5, timeout_seconds),
        ),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        follow_redirects=False,
    ), True


def response_error(status: int) -> LLMError:
    if status == 429:
        return LLMError("rate_limited")
    if status in {401, 403}:
        return LLMError("authentication_failed")
    return LLMError("unavailable")


class TextBudget:
    def __init__(self) -> None:
        self.characters = 0

    def event(self, text: Any) -> dict[str, Any] | None:
        if not isinstance(text, str):
            raise LLMError("invalid_response")
        if not text:
            return None
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise LLMError("invalid_response") from None
        self.characters += len(text)
        if self.characters > MAX_TEXT_CHARS:
            raise LLMError("output_limit")
        return {"type": "text", "text": text}


def tool_specs(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if tools is None:
        return []
    try:
        snapshot = json.loads(json.dumps(tools, allow_nan=False))
        if (
            not isinstance(snapshot, list)
            or len(snapshot) > 16
            or len(json.dumps(snapshot)) > 32768
        ):
            raise ValueError
        names: set[str] = set()
        for item in snapshot:
            if (
                not isinstance(item, dict)
                or set(item) != {"name", "description", "parameters"}
                or not isinstance(item["name"], str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", item["name"])
                or item["name"] in names
                or not isinstance(item["description"], str)
                or len(item["description"]) > 1024
                or not isinstance(item["parameters"], dict)
                or item["parameters"].get("type") != "object"
            ):
                raise ValueError
            names.add(item["name"])
        return snapshot
    except (ValueError, TypeError):
        raise ValueError("invalid tool specifications") from None


def validate_tool_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        encoded = json.dumps(messages, allow_nan=False)
        if len(encoded.encode()) > MAX_CONTEXT_BYTES:
            raise ValueError
        pending: set[str] = set()
        seen: set[str] = set()
        first = True
        for index, message in enumerate(messages):
            role = message.get("role")
            content = message.get("content")
            if not isinstance(content, str) or "\x00" in content:
                raise ValueError
            if (
                role == "system"
                and index == 0
                and set(message) == {"role", "content"}
                and content.strip()
            ):
                continue
            if first:
                if role != "user":
                    raise ValueError
                first = False
            if role == "tool":
                if (
                    set(message) != {"role", "content", "tool_call_id"}
                    or message["tool_call_id"] not in pending
                ):
                    raise ValueError
                pending.remove(message["tool_call_id"])
            elif pending:
                raise ValueError
            elif role == "assistant" and "tool_calls" in message:
                if (
                    set(message) != {"role", "content", "tool_calls"}
                    or not 1 <= len(message["tool_calls"]) <= 16
                ):
                    raise ValueError
                for call in message["tool_calls"]:
                    if set(call) != {"id", "type", "function"} or call["type"] != "function":
                        raise ValueError
                    identifier, function = call["id"], call["function"]
                    if (
                        not isinstance(identifier, str)
                        or not 1 <= len(identifier) <= 128
                        or identifier in seen
                        or set(function) != {"name", "arguments"}
                        or not isinstance(function["name"], str)
                        or not isinstance(json.loads(function["arguments"]), dict)
                    ):
                        raise ValueError
                    seen.add(identifier)
                    pending.add(identifier)
            elif (
                role not in {"user", "assistant"}
                or set(message) != {"role", "content"}
                or not content.strip()
            ):
                raise ValueError
        if first or pending or messages[-1]["role"] not in {"user", "tool"}:
            raise ValueError
        return copy.deepcopy(messages)
    except (TypeError, ValueError, KeyError, AttributeError):
        raise LLMError("invalid_context") from None


def tool_event(
    identifier: str, name: str, raw_arguments: str, approved: set[str]
) -> dict[str, Any]:
    try:
        arguments = json.loads(
            raw_arguments, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
        if (
            not isinstance(identifier, str)
            or not 1 <= len(identifier) <= 128
            or name not in approved
            or not isinstance(arguments, dict)
            or len(raw_arguments.encode()) > 32768
        ):
            raise ValueError
        return {"type": "tool_call", "id": identifier, "name": name, "arguments": arguments}
    except (ValueError, TypeError):
        raise LLMError("invalid_response") from None
