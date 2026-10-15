"""ASGI admission checks exercise slow bodies, overload, and capacity cleanup."""

import asyncio

import pytest
from starlette.types import Message, Receive, Scope, Send

from vasa.request_limits import ControlBodyLimit


def scope(path: str = "/api/knowledge/upload") -> Scope:
    return {"type": "http", "method": "POST", "path": path, "headers": []}


class Request:
    def __init__(self, body: bytes = b"", *, block: bool = False) -> None:
        self.body = body
        self.block = block
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.messages: list[Message] = []
        self.reads = 0

    async def receive(self) -> Message:
        self.reads += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        return {"type": "http.request", "body": self.body, "more_body": False}

    async def send(self, message: Message) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        return next(
            (
                message["status"]
                for message in self.messages
                if message["type"] == "http.response.start"
            ),
            None,
        )


async def accepted(scope: Scope, receive: Receive, send: Send) -> None:
    message = await receive()
    assert message["type"] == "http.request"
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_four_slow_uploads_fail_fast_fifth_and_release_on_cancellation() -> None:
    middleware = ControlBodyLimit(accepted)
    requests = [Request(block=True) for _ in range(4)]
    tasks = [
        asyncio.create_task(middleware(scope(), request.receive, request.send))
        for request in requests
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*(r.started.wait() for r in requests)), 1)
        rejected = Request(b"body must remain unread")
        await asyncio.wait_for(middleware(scope(), rejected.receive, rejected.send), 0.1)
        assert rejected.status == 429 and rejected.reads == 0
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        replacement = Request(b"valid")
        await asyncio.wait_for(middleware(scope(), replacement.receive, replacement.send), 0.1)
        assert replacement.status == 204
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_knowledge_text_and_binary_upload_share_admission_capacity() -> None:
    middleware = ControlBodyLimit(accepted)
    requests = [Request(block=True) for _ in range(4)]
    tasks = [
        asyncio.create_task(middleware(scope("/api/knowledge"), r.receive, r.send))
        for r in requests
    ]
    try:
        await asyncio.wait_for(asyncio.gather(*(r.started.wait() for r in requests)), 1)
        request = Request()
        await asyncio.wait_for(middleware(scope(), request.receive, request.send), 0.1)
        assert request.status == 429
        ordinary = Request(b"{}")
        await asyncio.wait_for(
            middleware(scope("/api/agent"), ordinary.receive, ordinary.send), 0.1
        )
        assert ordinary.status == 204
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_application_errors_release_all_upload_slots() -> None:
    count = 0

    async def fail(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal count
        count += 1
        await receive()
        raise RuntimeError("controlled component failure")

    middleware = ControlBodyLimit(fail)
    for _ in range(6):
        request = Request(b"{}")
        with pytest.raises(RuntimeError, match="controlled component failure"):
            await asyncio.wait_for(middleware(scope(), request.receive, request.send), 0.1)
        assert request.status is None
    assert count == 6


@pytest.mark.parametrize(
    "path,limit", [("/api/knowledge/upload", 2 * 1024 * 1024), ("/api/knowledge", 512 * 1024)]
)
async def test_upload_body_size_boundary_and_rejection_release_capacity(
    path: str, limit: int
) -> None:
    middleware = ControlBodyLimit(accepted)
    for _ in range(5):
        oversized = Request(b"x" * (limit + 1))
        await middleware(scope(path), oversized.receive, oversized.send)
        assert oversized.status == 413
    request = Request(b"x" * limit)
    await middleware(scope(path), request.receive, request.send)
    assert request.status == 204


async def test_chunked_body_limit_counts_accumulated_bytes() -> None:
    middleware = ControlBodyLimit(accepted)
    chunks: list[Message] = [
        {"type": "http.request", "body": b"x" * (512 * 1024), "more_body": True},
        {"type": "http.request", "body": b"x", "more_body": False},
    ]
    request = Request()

    async def receive() -> Message:
        return chunks.pop(0)

    await middleware(scope("/api/knowledge"), receive, request.send)
    assert request.status == 413


async def test_slow_body_times_out_after_five_seconds_and_releases_capacity() -> None:
    middleware = ControlBodyLimit(accepted)
    requests = [Request(block=True) for _ in range(4)]
    started = asyncio.get_running_loop().time()
    async with asyncio.timeout(7):
        await asyncio.gather(*(middleware(scope(), r.receive, r.send) for r in requests))
    elapsed = asyncio.get_running_loop().time() - started
    assert 4.8 <= elapsed < 7
    assert all(r.status == 408 for r in requests)
    replacement = Request(b"valid")
    await middleware(scope(), replacement.receive, replacement.send)
    assert replacement.status == 204
