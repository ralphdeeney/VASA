import json
import time

import pytest
from websockets.asyncio.server import serve

from tests.component.test_media import ADMIN, INSTANCE, MEDIA, PCM, START, STREAM
from tests.voice_worker.test_worker import Registry, Runtime, Transport, identity
from vasa.contracts.models import AudioFrame
from vasa.evolution import EvolutionCalls, EvolutionError
from vasa.evolution.stream import CallLifecycle
from vasa.voice_worker import handle_call

PRIVATE = "private-node-relay-token-must-not-log"


def event(client, name, *, call="ABC123", instance="tenant-1", token=None, queue=None):
    return json.dumps(
        {
            "queue": queue or f"{instance}.{name}".lower(),
            "payload": json.dumps(
                {
                    "instanceId": instance,
                    "instanceToken": token or client.token_for_instance(instance),
                    "event": name,
                    "data": {"CallID": call, "Reason": PRIVATE, "Data": PRIVATE},
                }
            ),
        }
    )


async def test_observed_sequence_keeps_media_live_until_stop(capsys):
    received = []

    async def upstream(ws):
        await ws.send(json.dumps(START))
        await ws.send(json.dumps(MEDIA))
        received.append(await ws.recv())
        await ws.send(json.dumps(MEDIA))
        received.append(await ws.recv())
        await ws.send(json.dumps({"event": "stop", "reason": PRIVATE}))
        await ws.wait_closed()

    async with serve(upstream, "127.0.0.1", 0) as server:
        client = EvolutionCalls(
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", ADMIN, STREAM, INSTANCE
        )
        try:
            async with client.open_media("tenant-1", "ABC123") as media:
                assert await media.receive() is not None
                # The pinned Evolution dispatcher does not forward transport;
                # these unknown notifications must not change VASA media state.
                for name in ("CallRelayLatency", "CallTransport", "CallTransport"):
                    assert client.parse_event(event(client, name), "tenant-1") is None
                assert not media.remote_terminated and not media.upstream_stopped
                await media.send(AudioFrame(PCM, 16000, 0, 0))
                media._last_frame_at = time.monotonic() - 2
                assert await media.receive() is not None
                await media.send(AudioFrame(PCM, 16000, 1, 0))
                # Authenticated terminate is authoritative, duplicate is idempotent.
                for _ in range(2):
                    client.parse_event(event(client, "CallTerminate"), "tenant-1")
                assert media.remote_terminated
                assert await media.receive() is None
                assert media.upstream_stopped
                await media.close()
            assert not client._media_lifecycles
        finally:
            await client.aclose()
    assert len(received) == 2
    output = capsys.readouterr().out
    assert output.count("CALL_LIFECYCLE=remote_terminate") == 1
    assert "CALL_MEDIA=receive_recovered" in output
    assert PRIVATE not in output


@pytest.mark.parametrize("change", ["foreign_instance", "foreign_call", "bad_token", "bad_queue"])
async def test_remote_terminate_is_authenticated_and_call_scoped(change, capsys):
    client = EvolutionCalls("http://127.0.0.1:1", ADMIN, STREAM, INSTANCE)
    lifecycle = CallLifecycle()
    client._media_lifecycles[("tenant-1", "ABC123")] = lifecycle
    kwargs = (
        {"instance": "other"}
        if change == "foreign_instance"
        else {"call": "OTHER"}
        if change == "foreign_call"
        else {"token": PRIVATE}
        if change == "bad_token"
        else {"queue": "tenant-1.calloffer"}
    )
    try:
        if change in {"foreign_call"}:
            client.parse_event(event(client, "CallTerminate", **kwargs), "tenant-1")
        else:
            with pytest.raises(EvolutionError):
                client.parse_event(event(client, "CallTerminate", **kwargs), "tenant-1")
        assert not lifecycle.remote_terminated
        assert PRIVATE not in capsys.readouterr().out
    finally:
        await client.aclose()


@pytest.mark.parametrize("source", ["remote_terminated", "upstream_stopped"])
async def test_remote_end_skips_duplicate_hangup_and_preserves_cleanup(source, capsys):
    context, incoming = identity()
    client = Transport(failure="hangup")
    setattr(client, source, True)
    registry = Registry()
    result = await handle_call(client, registry, context, incoming.instance_id, incoming, Runtime())
    assert result["error"] is None
    assert result["hangup_acknowledged"] is False
    assert result["hangup_required"] is False
    assert not any(call[0] == "hangup" for call in client.calls)
    assert client.closed and len(registry.deleted) == 1
    assert PRIVATE not in capsys.readouterr().out


async def test_authoritative_remote_terminate_racing_hangup_failure():
    class Race(Transport):
        async def hangup(self, instance, call):
            self.remote_terminated = True
            raise RuntimeError(PRIVATE)

    context, incoming = identity()
    client = Race()
    result = await handle_call(
        client, Registry(), context, incoming.instance_id, incoming, Runtime()
    )
    assert result["error"] is None
    assert result["termination_source"] == "remote_terminate"
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("terminated", [False, True])
async def test_socket_shutdown_without_stop_requires_authoritative_terminate(terminated):
    async def upstream(ws):
        await ws.send(json.dumps(START))
        await ws.recv()
        await ws.close()

    async with serve(upstream, "127.0.0.1", 0) as server:
        client = EvolutionCalls(
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", ADMIN, STREAM, INSTANCE
        )
        try:
            async with client.open_media("tenant-1", "ABC123") as media:
                if terminated:
                    client.parse_event(event(client, "CallTerminate"), "tenant-1")
                await media.send(AudioFrame(PCM, 16000, 0, 0))
                if terminated:
                    assert await media.receive() is None
                else:
                    with pytest.raises(EvolutionError, match="unavailable"):
                        await media.receive()
        finally:
            await client.aclose()
