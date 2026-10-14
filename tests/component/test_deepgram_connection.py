"""Real loopback TCP evidence, not live vendor/VPS performance evidence."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from vasa.speech.deepgram import DeepgramTTS


async def test_completed_http_streams_reuse_one_real_tcp_connection() -> None:
    connections = 0
    received: list[dict[str, Any]] = []
    peers: set[asyncio.StreamWriter] = set()
    tasks: set[asyncio.Task[None]] = set()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal connections
        connections += 1
        peers.add(writer)
        task = asyncio.current_task()
        assert task is not None
        tasks.add(task)
        try:
            while True:
                header = await reader.readuntil(b"\r\n\r\n")
                lines = header.decode().split("\r\n")
                assert (
                    lines[0] == "POST /v1/speak?model=aura-2-thalia-en&encoding=linear16"
                    "&sample_rate=16000&container=none HTTP/1.1"
                )
                values = dict(line.lower().split(": ", 1) for line in lines[1:] if ": " in line)
                received.append(json.loads(await reader.readexactly(int(values["content-length"]))))
                pcm = b"\x01\x00" * 1000
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: audio/L16;rate=16000;channels=1\r\n"
                    b"Content-Length: 2000\r\nServer-Timing: ttfb;dur=1\r\n\r\n" + pcm
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            peers.discard(writer)
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    records: list[dict[str, Any]] = []
    client = httpx.AsyncClient(trust_env=False, limits=httpx.Limits(max_connections=1))
    tts = DeepgramTTS(
        "local-test-only",
        client=client,
        base_url=f"http://127.0.0.1:{port}",
        observer=records.append,
    )
    try:
        for index in range(3):
            frames = [frame async for frame in tts.synthesize(f"Business response {index}.")]
            assert len(frames) == 2
        assert connections == 1
        assert len(received) == 3 and len({item["text"] for item in received}) == 3
        assert [record["connect_tcp_count"] for record in records] == [1, 0, 0]
        assert len({record["connection_id"] for record in records}) == 1
        assert all(record["tls_count"] == 0 for record in records)
    finally:
        await tts.aclose()
        server.close()
        await server.wait_closed()
        for writer in tuple(peers):
            writer.close()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tuple(tasks)), 2)


async def test_cancel_stream_closes_real_tcp_peer_before_response_finishes() -> None:
    peer_closed = asyncio.Event()
    waiting = asyncio.Event()
    tasks: set[asyncio.Task[None]] = set()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        tasks.add(task)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in header.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            await reader.readexactly(length)
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: audio/L16;rate=16000;channels=1\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n780\r\n" + b"\0" * 1920 + b"\r\n"
            )
            await writer.drain()
            waiting.set()
            assert await reader.read() == b""
            peer_closed.set()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    tts = DeepgramTTS(
        "local-test-only",
        client=httpx.AsyncClient(trust_env=False),
        base_url=f"http://127.0.0.1:{port}",
    )
    try:
        audio = tts.synthesize("A sentence still arriving.")
        first = await asyncio.wait_for(anext(audio), 2)
        assert len(first.pcm) == 1920
        await waiting.wait()
        read = asyncio.create_task(anext(audio))
        await asyncio.sleep(0)
        read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await read
        await asyncio.wait_for(peer_closed.wait(), 2)
    finally:
        await tts.aclose()
        server.close()
        await server.wait_closed()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tuple(tasks)), 2)
