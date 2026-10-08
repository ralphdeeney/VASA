import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
import traceback
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

from vasa.contracts.models import AudioFrame
from vasa.evolution import EvolutionCalls, EvolutionError

ADMIN, STREAM, INSTANCE = "a" * 32, "s" * 32, "i" * 32
PCM = bytes(range(256)) * 7 + bytes(range(128))
MEDIA = {"event": "media", "track": "inbound", "payload": base64.b64encode(PCM).decode()}
START = {"event": "start", "callId": "ABC123", "sampleRate": 16000}


async def test_bidirectional_local_ws_component_signed_handshake_and_stop() -> None:
    received: list[dict[str, object]] = []

    async def upstream(ws: ServerConnection) -> None:
        assert ws.request is not None
        path = urlsplit(ws.request.path)
        assert path.path == "/call/stream/ABC123"
        query = parse_qs(path.query)
        assert set(query) == {"instance", "exp", "token"}
        exp = int(query["exp"][0])
        assert 58 <= exp - int(time.time()) <= 60
        assert query["instance"] == ["tenant-1"]
        expected = hmac.new(
            STREAM.encode(), f"tenant-1|ABC123|{exp}".encode(), hashlib.sha256
        ).hexdigest()
        assert query["token"] == [expected]
        await ws.send(json.dumps(MEDIA))  # upstream race before start is supported
        await ws.send(json.dumps(START))
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"event": "stop", "reason": "hangup"}))
        await ws.wait_closed()

    async with serve(upstream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            async with client.open_media("tenant-1", "ABC123") as stream:
                frame = await stream.receive()
                assert frame is not None and frame.pcm == PCM
                assert frame.sample_rate == 16000 and frame.sequence == 0
                await stream.send(AudioFrame(PCM, 16000, 0, 0))
                assert await stream.receive() is None
                await stream.close()  # safe after upstream stop
        finally:
            await client.aclose()
    assert received == [
        {"event": "media", "track": "outbound", "payload": base64.b64encode(PCM).decode()}
    ]


@pytest.mark.parametrize(
    "messages",
    [
        [{**START, "callId": "foreign"}],
        [{**START, "sampleRate": 8000}],
        [{**START, "video": True}],
        [{**START, "video": "false"}],
        [{"event": "video"}],
        [MEDIA] * 5 + [START],
        ["not-json"],
        [{**MEDIA, "payload": "?" * 2560}],
    ],
)
async def test_malformed_handshake_and_prestart_frames_fail_closed(messages: list[object]) -> None:
    async def upstream(ws: ServerConnection) -> None:
        for message in messages:
            await ws.send(message if isinstance(message, str) else json.dumps(message))
        await ws.wait_closed()

    async with serve(upstream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            with pytest.raises(EvolutionError, match="invalid_response"):
                async with client.open_media("tenant-1", "ABC123"):
                    pytest.fail("invalid handshake was accepted")
        finally:
            await client.aclose()


@pytest.mark.parametrize(
    "message",
    [
        {"event": "media", "track": "outbound", "payload": MEDIA["payload"]},
        {"event": "media", "track": "inbound", "payload": "AAAA"},
        {"event": "video"},
        {"event": "start"},
    ],
)
async def test_malformed_poststart_media_closes_stream(message: dict[str, str]) -> None:
    async def upstream(ws: ServerConnection) -> None:
        await ws.send(json.dumps(START))
        await ws.send(json.dumps(message))
        await ws.wait_closed()

    async with serve(upstream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            async with client.open_media("tenant-1", "ABC123") as stream:
                with pytest.raises(EvolutionError, match="invalid_response"):
                    await stream.receive()
                assert await stream.receive() is None
        finally:
            await client.aclose()


async def test_handshake_timeout_releases_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vasa.evolution.stream.READ_TIMEOUT_SECONDS", 0.03)
    closed = asyncio.Event()

    async def upstream(ws: ServerConnection) -> None:
        await ws.wait_closed()
        closed.set()

    async with serve(upstream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            with pytest.raises(EvolutionError, match="unavailable"):
                async with client.open_media("tenant-1", "ABC123"):
                    pytest.fail("handshake timeout was ignored")
            await asyncio.wait_for(closed.wait(), 1)
        finally:
            await client.aclose()


async def test_authenticated_event_socket_yields_only_verified_calls() -> None:
    token = hmac.new(INSTANCE.encode(), b"vasa:instance:tenant-1", hashlib.sha256).hexdigest()

    async def upstream(ws: ServerConnection) -> None:
        assert ws.request is not None
        query = parse_qs(urlsplit(ws.request.path).query)
        assert query == {"token": [ADMIN], "instanceId": ["tenant-1"]}
        event = {
            "instanceId": "tenant-1",
            "instanceToken": token,
            "event": "CallOffer",
            "data": {"CallID": "ABC123", "CallCreator": "12345@s.whatsapp.net"},
        }
        await ws.send(json.dumps({"queue": "tenant-1.calloffer", "payload": json.dumps(event)}))
        await ws.close()

    async with serve(upstream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            events = [event async for event in client.events("tenant-1")]
            assert len(events) == 1 and events[0].call_id == "ABC123"
        finally:
            await client.aclose()


@pytest.mark.parametrize(
    "body,code",
    [
        ({"code": "LICENSE_REQUIRED"}, "license_required"),
        ({"error": "unavailable"}, "unavailable"),
    ],
)
async def test_ws_upgrade_failures_are_sanitized_and_do_not_log_signed_queries(
    body: dict[str, str],
    code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    server_logger = logging.Logger("test.evolution.no-secret-logging")
    server_logger.disabled = True

    async def upstream(ws: ServerConnection) -> None:
        pytest.fail("failed upgrade must not reach handler")

    def reject(ws: ServerConnection, _: Request) -> Response:
        return ws.respond(503, json.dumps({**body, "error": "secret-error-" + STREAM}))

    async with serve(
        upstream, "127.0.0.1", 0, process_request=reject, logger=server_logger
    ) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            with pytest.raises(EvolutionError) as caught:
                async with client.open_media("tenant-1", "ABC123"):
                    pytest.fail("failed upgrade accepted")
            assert caught.value.code == code
            output = "".join(traceback.format_exception(caught.value))
            assert STREAM not in output
            assert "token=" not in output
            assert "token=" not in caplog.text
        finally:
            await client.aclose()


async def test_rejects_wrong_output_frame_before_sending() -> None:
    received: list[str | bytes] = []

    async def upstream(ws: ServerConnection) -> None:
        await ws.send(json.dumps(START))
        async for message in ws:
            received.append(message)

    async with serve(upstream, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        try:
            async with client.open_media("tenant-1", "ABC123") as stream:
                with pytest.raises(ValueError, match="960 mono PCM16"):
                    await stream.send(AudioFrame(b"xx", 16000, 0, 0))
        finally:
            await client.aclose()
    assert not received


async def test_idle_event_socket_uses_ping_health_and_cancellation_closes_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("vasa.evolution.stream.READ_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr("vasa.evolution.client.EVENT_PING_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr("vasa.evolution.client.EVENT_PING_TIMEOUT_SECONDS", 0.02)
    caplog.set_level(logging.DEBUG)
    connected, closed = asyncio.Event(), asyncio.Event()
    server_logger = logging.Logger("test.evolution.idle-no-secrets")
    server_logger.disabled = True

    async def upstream(ws: ServerConnection) -> None:
        connected.set()
        await ws.wait_closed()
        closed.set()

    async with serve(upstream, "127.0.0.1", 0, logger=server_logger) as server:
        port = server.sockets[0].getsockname()[1]
        client = EvolutionCalls(f"http://127.0.0.1:{port}", ADMIN, STREAM, INSTANCE)
        events = client.events("tenant-1")
        pending = asyncio.create_task(anext(events))
        try:
            await asyncio.wait_for(connected.wait(), 1)
            # Several media deadlines and ping/pong cycles pass without any call event.
            await asyncio.sleep(0.1)
            assert not pending.done()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(closed.wait(), 1)
            assert ADMIN not in caplog.text
            assert "token=" not in caplog.text
        finally:
            pending.cancel()
            await events.aclose()
            await client.aclose()
