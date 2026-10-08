import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class Plan:
    parts: list[bytes]
    status: int = 200
    content_type: str = "text/event-stream"
    hold: asyncio.Event | None = None
    abruptly_close: bool = False
    disconnected: asyncio.Event = field(default_factory=asyncio.Event)


class SSEServer:
    """Real loopback HTTP/chunked SSE fixtures; no model reasoning is simulated or scored."""

    def __init__(self) -> None:
        self.plans: list[Plan] = []
        self.requests: list[dict[str, Any]] = []
        self.tasks: set[asyncio.Task[None]] = set()
        self.url = ""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.tasks.add(task)
        peer: asyncio.Task[bytes] | None = None
        release: asyncio.Task[bool] | None = None
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode("ascii").split("\r\n")
            headers = {
                key.lower(): value
                for key, value in (line.split(": ", 1) for line in lines[1:] if line)
            }
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            self.requests.append(
                {"path": lines[0].split()[1], "headers": headers, "body": json.loads(body)}
            )
            plan = self.plans.pop(0)
            writer.write(
                (
                    f"HTTP/1.1 {plan.status} fixture\r\nContent-Type: {plan.content_type}\r\n"
                    "Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                ).encode()
            )
            await writer.drain()
            peer = asyncio.create_task(reader.read())
            for index, part in enumerate(plan.parts):
                writer.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                await writer.drain()
                if index == 0 and plan.hold is not None:
                    release = asyncio.create_task(plan.hold.wait())
                    done, _ = await asyncio.wait(
                        {release, peer}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if peer in done:
                        return
                await asyncio.sleep(0)
            if plan.abruptly_close:
                return
            writer.write(b"0\r\n\r\n")
            await writer.drain()
            await peer
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            if "plan" in locals():
                plan.disconnected.set()
            for pending in (peer, release):
                if pending is not None:
                    pending.cancel()
            await asyncio.gather(
                *(pending for pending in (peer, release) if pending is not None),
                return_exceptions=True,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(task)


@pytest.fixture
async def sse_server() -> AsyncIterator[SSEServer]:
    fixture = SSEServer()
    server = await asyncio.start_server(fixture.handle, "127.0.0.1", 0)
    fixture.url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
    try:
        yield fixture
    finally:
        server.close()
        await server.wait_closed()
        for task in list(fixture.tasks):
            task.cancel()
        await asyncio.gather(*fixture.tasks, return_exceptions=True)
