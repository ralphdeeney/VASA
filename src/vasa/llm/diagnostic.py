"""Bounded operator-only SSE shape inspection; never render remote strings."""

import asyncio
import json
import logging
from contextlib import aclosing
from typing import Any

import httpx

from vasa.config import Settings
from vasa.llm.common import client_settings
from vasa.llm.sse import SSEEvent, _events

KNOWN_KEYS = frozenset(
    {
        "id",
        "object",
        "created",
        "model",
        "choices",
        "usage",
        "system_fingerprint",
        "service_tier",
        "error",
        "index",
        "delta",
        "finish_reason",
        "logprobs",
        "role",
        "content",
        "reasoning",
        "reasoning_content",
        "refusal",
        "tool_calls",
        "function_call",
        "message",
    }
)


def keys(value: dict[str, Any]) -> dict[str, Any]:
    # Even JSON property names are untrusted and can contain response text/secrets.
    return {
        "keys": sorted(set(value) & KNOWN_KEYS),
        "unknown_key_count": len(set(value) - KNOWN_KEYS),
    }


def shape(event: SSEEvent) -> dict[str, Any]:
    result: dict[str, Any] = {
        "event_name": event.name if event.name in {"message", "error", "done"} else "other",
        "done": event.data == "[DONE]",
    }
    if result["done"]:
        return result
    try:
        data = json.loads(event.data)
    except (ValueError, RecursionError):
        return {**result, "json_parses": False}
    result["json_parses"] = True
    if not isinstance(data, dict):
        return {**result, "json_object": False}
    result.update(keys(data))
    choices = data.get("choices")
    result["choices_count"] = len(choices) if isinstance(choices, list) else None
    rows = []
    for choice in choices[:16] if isinstance(choices, list) else []:
        if not isinstance(choice, dict):
            rows.append({"choice_object": False})
            continue
        index = choice.get("index")
        row = keys(choice)
        row["index_type"] = (
            "missing"
            if "index" not in choice
            else "null"
            if index is None
            else "boolean"
            if isinstance(index, bool)
            else "integer"
            if isinstance(index, int)
            else "string"
            if isinstance(index, str)
            else "other"
        )
        row["index_value"] = (
            index
            if type(index) is int and 0 <= index < 16
            else index
            if type(index) is str and index in {str(n) for n in range(16)}
            else None
        )
        reason = choice.get("finish_reason")
        row["finish_reason"] = (
            reason
            if reason is None
            or isinstance(reason, str)
            and reason in {"stop", "length", "tool_calls", "function_call", "content_filter"}
            else "other"
        )
        delta = choice.get("delta")
        row["delta_object"] = isinstance(delta, dict)
        if isinstance(delta, dict):
            row["delta"] = keys(delta)
            row["content_exists"] = "content" in delta
        rows.append(row)
    result["choices"] = rows
    return result


async def diagnose(settings: Settings, client: httpx.AsyncClient | None = None) -> int:
    count, done = 0, False
    active, owned = client_settings(
        settings.openai_api_key.get_secret_value(),
        settings.openai_model,
        settings.openai_base_url,
        32,
        30,
        client,
    )
    try:
        async with asyncio.timeout(35):
            async with active.stream(
                "POST",
                settings.openai_base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": "Bearer " + settings.openai_api_key.get_secret_value(),
                    "Accept": "text/event-stream",
                    "Accept-Encoding": "identity",
                },
                json={
                    "model": settings.openai_model,
                    "messages": [{"role": "user", "content": "Say hello briefly."}],
                    "max_completion_tokens": 32,
                    "stream": True,
                    "n": 1,
                },
            ) as response:
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                encoding = response.headers.get("content-encoding", "identity").lower()
                print(
                    json.dumps(
                        {
                            "http_status": response.status_code,
                            "content_type_parameters": ";"
                            in response.headers.get("content-type", ""),
                            "content_type": content_type
                            if content_type
                            in {"text/event-stream", "application/json", "text/plain"}
                            else "other",
                            "content_encoding": encoding
                            if encoding in {"identity", "gzip", "br", "deflate", "zstd"}
                            else "other",
                        }
                    ),
                    flush=True,
                )
                if response.status_code != 200 or encoding != "identity":
                    return 1
                deadline = asyncio.get_running_loop().time() + 30
                async with aclosing(_events(response, deadline)) as events:
                    async for event in events:
                        count += 1
                        metadata = shape(event)
                        done |= bool(metadata["done"])
                        print(json.dumps(metadata), flush=True)
        return 0 if done else 1
    finally:
        print(json.dumps({"event_count": count, "done_received": done}), flush=True)
        if owned:
            async with asyncio.timeout(3):
                await active.aclose()


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(diagnose(Settings()))
    except Exception:
        # No exception strings, tracebacks, validation inputs or response bodies.
        return 1
