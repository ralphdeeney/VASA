import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from vasa.speech.speechify import SpeechifyTTS


class PCMStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, block: bool = False) -> None:
        self.chunks = chunks
        self.block = block
        self.closed = False
        self.waiting = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        if self.block:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


def provider(
    stream: PCMStream, *, headers: dict[str, str] | None = None, status: int = 200
) -> tuple[SpeechifyTTS, list[dict[str, Any]], list[httpx.Request]]:
    requests: list[httpx.Request] = []
    records: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers=headers
            or {"content-type": "audio/L16;rate=16000;channels=1", "server-timing": "ttfb;dur=20"},
            stream=stream,
        )

    return (
        SpeechifyTTS(
            "secret-test-key",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            observer=records.append,
        ),
        records,
        requests,
    )


async def test_fragmented_pcm_streams_before_complete_and_contract() -> None:
    stream = PCMStream([b"\x01", b"\x00" * 1919, b"\x02\x00"], block=True)
    tts, records, requests = provider(stream)
    audio = tts.synthesize("A business sentence.")
    first = await anext(audio)
    assert len(first.pcm) == 1920 and first.pcm[0] == 1
    assert first.sample_rate == 16000 and first.channels == 1 and first.sequence == 0
    await audio.aclose()
    assert stream.closed and records[0]["outcome"] == "cancelled"
    assert requests[0].url.path == "/v1/audio/stream"
    assert requests[0].headers["speechify-version"] == "2026-09-30"
    assert json.loads(requests[0].content) == {
        "input": "A business sentence.",
        "voice_id": "geffen_32",
        "model": "simba-3.2",
        "output_format": "pcm_16000",
    }
    await tts.aclose()


async def test_even_partial_padding_preserves_original_duration() -> None:
    stream = PCMStream([b"\x01\x00" * 1000])
    tts, records, _ = provider(stream)
    frames = [frame async for frame in tts.synthesize("Thank you.")]
    assert len(frames) == 2
    assert frames[1].pcm == b"\x01\x00" * 40 + b"\0" * 1840
    assert records[0]["audio_seconds"] == 2000 / 32000
    assert records[0]["outcome"] == "complete"
    assert records[0]["conversion_seconds"] == 0
    assert records[0]["server_ttfb_seconds"] == 0.02
    await tts.aclose()


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "audio/L16;rate=24000;channels=1"},
        {"content-type": "audio/L16;rate=16000;channels=2"},
        {"content-type": "audio/mpeg"},
        {"content-type": "audio/L16;rate=16000", "content-encoding": "gzip"},
    ],
)
async def test_wrong_formats_rejected(headers: dict[str, str]) -> None:
    stream = PCMStream([b"\0" * 1920])
    tts, records, _ = provider(stream, headers=headers)
    with pytest.raises(RuntimeError, match="^Speechify synthesis failed$"):
        _ = [frame async for frame in tts.synthesize("A sentence.")]
    assert stream.closed and records[0]["outcome"] == "error"
    await tts.aclose()


@pytest.mark.parametrize("pcm", [b"", b"\0" * 3])
async def test_empty_odd_pcm_rejected(pcm: bytes) -> None:
    tts, records, _ = provider(PCMStream([pcm]))
    with pytest.raises(RuntimeError, match="Speechify synthesis failed"):
        _ = [frame async for frame in tts.synthesize("Hello.")]
    assert records[0]["outcome"] == "error"
    await tts.aclose()


async def test_http_error_body_and_header_secrets_not_recorded() -> None:
    stream = PCMStream([b"secret-test-key sensitive error"])
    tts, records, _ = provider(
        stream,
        status=401,
        headers={
            "server-timing": 'ttfb;dur=20;desc="secret-test-key", safe;dur=1;desc="private"',
        },
    )
    with pytest.raises(RuntimeError, match="^Speechify synthesis failed$") as error:
        _ = [frame async for frame in tts.synthesize("Hello.")]
    assert records[0]["http_status"] == 401 and records[0]["bytes_received"] == 0
    assert "secret-test-key" not in str(error.value) + json.dumps(records)
    assert "private" not in json.dumps(records)
    await tts.aclose()


async def test_cancel_blocked_read_closes_stream_and_releases_admission() -> None:
    stream = PCMStream([], block=True)
    tts, records, _ = provider(stream)
    audio = tts.synthesize("Please wait.")
    pending = asyncio.create_task(anext(audio))
    await stream.waiting.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stream.closed and tts._admitted == 0
    assert records[0]["outcome"] == "cancelled"
    assert records[0]["cancellation_cleanup_seconds"] is not None
    await tts.aclose()


async def test_audio_limit_and_admission_are_bounded() -> None:
    stream = PCMStream([b"\0" * 32002])
    tts, _, _ = provider(stream)
    tts._max_bytes = 32000
    with pytest.raises(RuntimeError):
        _ = [frame async for frame in tts.synthesize("Hello.")]
    tts._admitted = 10
    with pytest.raises(RuntimeError, match="busy"):
        await anext(tts.synthesize("Hello."))
    tts._admitted = 0
    await tts.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await anext(tts.synthesize("Hello."))


async def test_timeout_and_missing_timing() -> None:
    stream = PCMStream([], block=True)
    tts, records, _ = provider(stream, headers={"content-type": "audio/pcm;rate=16000"})
    tts._deadline = 0.02
    with pytest.raises(RuntimeError, match="Speechify synthesis failed"):
        await anext(tts.synthesize("Hello."))
    assert stream.closed
    assert records[0]["server_ttfb_seconds"] is None
    assert records[0]["local_network_overhead_estimate_seconds"] is None
    await tts.aclose()


async def test_repeated_cancellation_and_shutdown_drain_owned_cleanup() -> None:
    closing = asyncio.Event()
    release = asyncio.Event()

    class SlowClose(PCMStream):
        async def aclose(self) -> None:
            closing.set()
            await release.wait()
            self.closed = True

    stream = SlowClose([], block=True)
    tts, records, _ = provider(stream)
    audio = tts.synthesize("A cancellable sentence.")
    consuming = asyncio.create_task(anext(audio))
    await stream.waiting.wait()
    consuming.cancel()
    await closing.wait()
    consuming.cancel()
    shutdown = asyncio.create_task(tts.aclose())
    await asyncio.sleep(0)
    shutdown.cancel()
    await asyncio.sleep(0)
    assert not consuming.done() and not shutdown.done() and not stream.closed
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await consuming
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    assert stream.closed and not tts._cleanup_tasks and tts._admitted == 0
    assert records[0]["outcome"] == "cancelled"
    await tts.aclose()


async def test_cancel_before_headers_releases_waiting_request() -> None:
    waiting = asyncio.Event()
    cancelled = asyncio.Event()
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        waiting.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("Unreachable")

    tts = SpeechifyTTS(
        "test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        observer=records.append,
    )
    consuming = asyncio.create_task(anext(tts.synthesize("Before headers.")))
    await waiting.wait()
    consuming.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consuming
    assert cancelled.is_set() and tts._admitted == 0
    assert records[0]["first_byte_seconds"] is None
    await tts.aclose()


async def test_shutdown_discards_prepared_pcm_and_quoted_format_is_valid() -> None:
    stream = PCMStream([b"\0" * 3840])
    tts, records, _ = provider(
        stream,
        headers={
            "content-type": 'audio/L16;RATE="16000";CHANNELS="1"',
        },
    )
    audio = tts.synthesize("A buffered sentence.")
    assert len((await anext(audio)).pcm) == 1920
    await tts.aclose()
    with pytest.raises(RuntimeError, match="Speechify synthesis failed"):
        await anext(audio)
    assert records[0]["outcome"] == "error"


async def test_bounded_arrival_history_does_not_truncate_max_gap_metric() -> None:
    tts, records, _ = provider(PCMStream([b"\0\0"] * 300))
    _ = [frame async for frame in tts.synthesize("Hello.")]
    assert len(records[0]["body_arrival_gaps"]) == 256
    assert records[0]["body_arrival_gaps_truncated"] is True
    assert records[0]["max_body_arrival_gap_seconds"] >= max(records[0]["body_arrival_gaps"])
    assert records[0]["max_stream_read_wait_seconds"] > 0
    await tts.aclose()


async def test_shutdown_closes_client_even_when_response_cleanup_fails() -> None:
    class FailedClose(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b""

        async def aclose(self) -> None:
            raise RuntimeError("private upstream detail")

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    tts = SpeechifyTTS("local-test-only", client=client)
    tts._responses.add(httpx.Response(200, stream=FailedClose()))
    with pytest.raises(RuntimeError, match="Speechify stream cleanup failed"):
        await tts.aclose()
    assert client.is_closed


async def test_tls_trace_counts_proxy_tunnels_without_recording_trace_details() -> None:
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        trace = request.extensions["trace"]
        await trace("connection.connect_tcp.started", {"private": "secret-test-key"})
        await trace("proxy.start_tls.started", {"private": "secret-test-key"})
        return httpx.Response(
            200,
            headers={"content-type": "audio/L16;rate=16000;channels=1"},
            stream=PCMStream([b"\0" * 1920]),
        )

    tts = SpeechifyTTS(
        "secret-test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        observer=records.append,
    )
    try:
        assert len([frame async for frame in tts.synthesize("Hello.")]) == 1
        assert records[0]["connect_tcp_count"] == records[0]["tls_count"] == 1
        assert "secret-test-key" not in json.dumps(records)
    finally:
        await tts.aclose()
