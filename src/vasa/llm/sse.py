import asyncio
import json
import re
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

import httpx

from vasa.llm.common import LLMError, response_error

MAX_LINE_BYTES = 16384
MAX_EVENT_BYTES = 32768
MAX_STREAM_BYTES = 131072
MAX_EVENTS = 1024


@dataclass(frozen=True, slots=True)
class SSEEvent:
    name: str
    data: str

    def json(self) -> dict[str, Any]:
        try:
            value = json.loads(self.data)
        except (ValueError, UnicodeError, RecursionError):
            raise LLMError("invalid_response") from None
        if not isinstance(value, dict):
            raise LLMError("invalid_response")
        return value


async def _lines(response: httpx.Response, deadline: float) -> AsyncGenerator[bytes, None]:
    buffer = b""
    size = 0
    skip_lf = False
    # A fixed HTTPX chunk_size buffers tiny SSE deltas until the chunk fills, delaying speech.
    chunks = response.aiter_raw()
    while True:
        try:
            async with asyncio.timeout_at(deadline):
                chunk = await anext(chunks)
        except StopAsyncIteration:
            break
        size += len(chunk)
        if size > MAX_STREAM_BYTES:
            raise LLMError("output_limit")
        if skip_lf and chunk:
            chunk = chunk.removeprefix(b"\n")
            skip_lf = False
        buffer += chunk
        while match := re.search(rb"\r\n|\r|\n", buffer):
            # Dispatch a bare CR immediately; swallow a split CRLF's following LF once.
            skip_lf = match.group() == b"\r" and match.end() == len(buffer)
            line, buffer = buffer[: match.start()], buffer[match.end() :]
            if len(line) > MAX_LINE_BYTES:
                raise LLMError("output_limit")
            yield line
        if len(buffer) > MAX_LINE_BYTES:
            raise LLMError("output_limit")
    if buffer:
        yield buffer


async def _events(response: httpx.Response, deadline: float) -> AsyncGenerator[SSEEvent, None]:
    name = "message"
    data: list[str] = []
    size = 0
    count = 0
    first_line = True
    async with aclosing(_lines(response, deadline)) as lines:
        async for raw in lines:
            if first_line:
                raw = raw.removeprefix(b"\xef\xbb\xbf")
                first_line = False
            if not raw:
                if data:
                    count += 1
                    if count > MAX_EVENTS:
                        raise LLMError("output_limit")
                    yield SSEEvent(name, "\n".join(data))
                name, data, size = "message", [], 0
                continue
            if raw.startswith(b":"):
                continue
            try:
                line = raw.decode("utf-8", errors="strict")
            except UnicodeError:
                raise LLMError("invalid_response") from None
            field, separator, value = line.partition(":")
            if not separator:
                value = ""
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                if len(value) > 128:
                    raise LLMError("invalid_response")
                name = value
            elif field == "data":
                size += len(raw)
                if size > MAX_EVENT_BYTES:
                    raise LLMError("output_limit")
                data.append(value)
    # SSE dispatch requires a blank line. An incomplete event must not become valid output.
    if data:
        raise LLMError("invalid_response")


async def stream_events(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> AsyncGenerator[SSEEvent, None]:
    if client.is_closed:
        raise LLMError("unavailable")
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    manager = client.stream("POST", url, headers=headers, json=payload)
    response: httpx.Response | None = None
    try:
        async with asyncio.timeout_at(deadline):
            response = await manager.__aenter__()
        if response.status_code != 200:
            raise response_error(response.status_code)
        if (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "text/event-stream"
        ):
            raise LLMError("invalid_response")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise LLMError("invalid_response")
        async with aclosing(_events(response, deadline)) as events:
            async for event in events:
                yield event
    except httpx.TimeoutException:
        raise LLMError("timeout") from None
    except TimeoutError:
        raise LLMError("timeout") from None
    except httpx.HTTPError:
        raise LLMError("unavailable") from None
    finally:
        if response is not None:
            async with asyncio.timeout(5):
                await manager.__aexit__(None, None, None)
