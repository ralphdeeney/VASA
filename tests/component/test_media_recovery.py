import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import serve

from scripts.sanitize_call_diagnostics import classify
from tests.component.test_call_lifecycle import event
from tests.component.test_media import ADMIN, INSTANCE, MEDIA, PCM, START, STREAM
from vasa.contracts.models import AudioFrame
from vasa.evolution import EvolutionCalls, EvolutionError


@pytest.fixture
def deadlines(monkeypatch):
    # Keep the production ratios separate; accelerated tests exercise real sockets.
    monkeypatch.setattr("vasa.evolution.stream.READ_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr("vasa.evolution.stream.GAP_OBSERVE_SECONDS", 0.01)
    monkeypatch.setattr("vasa.evolution.stream.RECOVERY_TIMEOUT_SECONDS", 0.25)


@asynccontextmanager
async def connected(handler):
    async with serve(handler, "127.0.0.1", 0) as server:
        client = EvolutionCalls(
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", ADMIN, STREAM, INSTANCE
        )
        try:
            async with client.open_media("tenant-1", "ABC123") as media:
                yield client, media
        finally:
            await client.aclose()


async def test_recovery_after_old_deadline_keeps_same_socket_and_pcm(deadlines, capsys):
    received = []

    async def upstream(ws):
        await ws.send(json.dumps(START))
        await ws.send(json.dumps(MEDIA))
        received.append(json.loads(await ws.recv()))
        # Longer than the OLD read deadline. A hard read timeout used to close here.
        await asyncio.sleep(0.06)
        await ws.send(json.dumps(MEDIA))
        await ws.send(json.dumps({"event": "stop", "reason": "hangup"}))
        await ws.wait_closed()

    async with connected(upstream) as (_, media):
        first = await media.receive()
        assert first is not None
        reading = asyncio.create_task(media.receive())
        await asyncio.sleep(0.03)
        assert not reading.done() and not media._closed
        # Outbound is independent: inbound loss does not prove outbound loss.
        await media.send(AudioFrame(PCM, 16000, 0, 0))
        second = await asyncio.wait_for(reading, 1)
        assert second is not None and second.pcm == first.pcm == PCM
        assert second.sequence == first.sequence + 1
        assert second.timestamp_ns > first.timestamp_ns
        assert await media.receive() is None and media.upstream_stopped
    output = capsys.readouterr().out
    assert "CALL_MEDIA=receive_gap_started" in output
    assert "CALL_MEDIA=receive_recovered_ms=" in output
    assert "recovery_grace_expired" not in output
    assert len(received) == 1


async def test_permanent_loss_expires_once_and_closes(deadlines, capsys):
    closed = asyncio.Event()

    async def upstream(ws):
        await ws.send(json.dumps(START))
        await ws.wait_closed()
        closed.set()

    async with connected(upstream) as (_, media):
        started = time.monotonic()
        with pytest.raises(EvolutionError, match="unavailable"):
            await asyncio.wait_for(media.receive(), 1)
        assert 0.20 <= time.monotonic() - started < 1
        assert media.recovery_expired and media._closed
        await asyncio.wait_for(closed.wait(), 1)
    assert capsys.readouterr().out.count("CALL_MEDIA=recovery_grace_expired") == 1


@pytest.mark.parametrize("ending", ["remote_terminate", "upstream_stop"])
async def test_authoritative_end_interrupts_grace_immediately(deadlines, ending, capsys):
    release = asyncio.Event()

    async def upstream(ws):
        await ws.send(json.dumps(START))
        await release.wait()
        if ending == "upstream_stop":
            await ws.send(json.dumps({"event": "stop"}))
        await ws.wait_closed()

    async with connected(upstream) as (client, media):
        pending = asyncio.create_task(media.receive())
        await asyncio.sleep(0.03)
        started = time.monotonic()
        if ending == "remote_terminate":
            client.parse_event(event(client, "CallTerminate"), "tenant-1")
        release.set()
        assert await asyncio.wait_for(pending, 0.15) is None
        assert time.monotonic() - started < 0.15
        assert not media.recovery_expired
    assert "recovery_grace_expired" not in capsys.readouterr().out


async def test_malformed_media_during_grace_stays_fatal(deadlines):
    async def upstream(ws):
        await ws.send(json.dumps(START))
        await asyncio.sleep(0.04)
        await ws.send(json.dumps({**MEDIA, "payload": "invalid-private-content"}))
        await ws.wait_closed()

    async with connected(upstream) as (_, media):
        with pytest.raises(EvolutionError, match="invalid_response"):
            await media.receive()
        assert media._closed and not media.recovery_expired


async def test_cancellation_during_grace_leaves_no_receive_tasks(deadlines):
    async def upstream(ws):
        await ws.send(json.dumps(START))
        await ws.wait_closed()

    async with connected(upstream) as (_, media):
        pending = asyncio.create_task(media.receive())
        await asyncio.sleep(0.03)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not any(task.get_name().startswith("vasa-media-") for task in asyncio.all_tasks())


def test_timing_filter_rejects_secret_suffix_and_unbounded_values():
    assert classify("voice | CALL_MEDIA=receive_recovered_ms=12000") == [
        "CALL_MEDIA=receive_recovered_ms=12000"
    ]
    assert classify("CALL_MEDIA=receive_recovered_ms=12000secret") == []
    assert classify("CALL_MEDIA=receive_recovered_ms=1234567890123") == []
    assert classify("CALL_MEDIA=receive_recovered_ms=nan") == []
