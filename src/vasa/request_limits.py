import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_CONTROL_BODY_BYTES = 8192


class ControlBodyLimit:
    """Bound JSON control bodies before framework parsing, including chunked requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._uploads = asyncio.Semaphore(4)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        large = (
            scope["type"] == "http"
            and scope["path"] in {"/api/knowledge", "/api/knowledge/upload"}
            and scope["method"] == "POST"
        )
        if large:
            if self._uploads.locked():
                await JSONResponse({"detail": "capacity_unavailable"}, status_code=429)(
                    scope, receive, send
                )
                return
            async with self._uploads:
                await self._bounded(scope, receive, send)
        else:
            await self._bounded(scope, receive, send)

    async def _bounded(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/api/")
            or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        maximum = MAX_CONTROL_BODY_BYTES
        if scope["path"] == "/api/knowledge/upload":
            maximum = 2 * 1024 * 1024
        elif scope["path"] == "/api/knowledge":
            maximum = 512 * 1024
        elif scope["path"] == "/api/agent":
            maximum = 32768
        try:
            async with asyncio.timeout(5):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > maximum:
                        await JSONResponse({"detail": "request_too_large"}, status_code=413)(
                            scope, receive, send
                        )
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await JSONResponse({"detail": "request_timeout"}, status_code=408)(scope, receive, send)
            return
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
