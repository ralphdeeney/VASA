import asyncio
import json
from typing import Any

import httpx
import pytest

from tests.speech.test_speechify import PCMStream
from vasa.speech.deepgram import DeepgramTTS


def provider(
    stream: PCMStream, *, headers: dict[str, str] | None = None, status: int = 200
) -> tuple[DeepgramTTS, list[dict[str, Any]], list[httpx.Request]]:
    records: list[dict[str, Any]] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers=headers
            or {
                "content-type": "audio/l16;rate=16000",
                "dg-model-name": "aura-2-thalia-en",
                "dg-request-id": "request_123",
                "dg-model-uuid": "model_123",
            },
            stream=stream,
        )

    return (
        DeepgramTTS(
            "test-secret",
            observer=records.append,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
        records,
        requests,
    )


async def test_protocol_fragmented_pcm_padding_and_metadata() -> None:
    tts, records, requests = provider(PCMStream([b"\x01", b"\x00" * 1919, b"\x02\x00"]))
    frames = [frame async for frame in tts.synthesize("Hello customer.")]
    assert len(frames) == 2 and frames[0].pcm[0] == 1
    assert frames[1].pcm == b"\x02\x00" + b"\0" * 1918
    assert frames[0].sample_rate == 16000 and frames[0].channels == 1
    request = requests[0]
    assert request.url.path == "/v1/speak"
    assert dict(request.url.params) == {
        "model": "aura-2-thalia-en",
        "encoding": "linear16",
        "sample_rate": "16000",
        "container": "none",
    }
    assert request.headers["authorization"] == "Token test-secret"
    assert "speechify-version" not in request.headers
    assert json.loads(request.content) == {"text": "Hello customer."}
    assert records[0]["response_model"] == "aura-2-thalia-en"
    assert records[0]["request_id"] == "request_123"
    assert records[0]["conversion_seconds"] == 0
    await tts.aclose()


async def test_missing_server_metadata_remains_unknown() -> None:
    tts, records, _ = provider(
        PCMStream([b"\0" * 1920]), headers={"content-type": "audio/l16;rate=16000"}
    )
    assert len([f async for f in tts.synthesize("Hello.")]) == 1
    assert records[0]["requested_model"] == "aura-2-thalia-en"
    assert records[0]["response_model"] is None and records[0]["request_id"] is None
    await tts.aclose()


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "audio/l16;rate=24000"},
        {"content-type": "audio/l16;rate=16000;channels=2"},
        {"content-type": "audio/wav"},
        {"content-type": "audio/l16;rate=16000", "dg-model-name": "aura-2-other-en"},
    ],
)
async def test_incompatible_audio_or_model_rejected(headers: dict[str, str]) -> None:
    stream = PCMStream([b"\0" * 1920])
    tts, records, _ = provider(stream, headers=headers)
    with pytest.raises(RuntimeError, match="^Deepgram synthesis failed$"):
        _ = [frame async for frame in tts.synthesize("Hello.")]
    assert stream.closed and records[0]["bytes_received"] == 0
    await tts.aclose()


async def test_errors_and_metadata_do_not_disclose_secret() -> None:
    tts, records, _ = provider(
        PCMStream([b"test-secret private"]),
        status=401,
        headers={
            "dg-request-id": "test-secret",
            "dg-model-uuid": "private description",
            "server-timing": 'ttfb;dur=1;desc="test-secret"',
        },
    )
    with pytest.raises(RuntimeError, match="^Deepgram synthesis failed$") as error:
        await anext(tts.synthesize("Hello."))
    assert "test-secret" not in str(error.value) + json.dumps(records)
    assert records[0]["request_id"] is None and records[0]["response_model_uuid"] is None
    await tts.aclose()


async def test_cancel_pending_body_closes_http_stream() -> None:
    stream = PCMStream([], block=True)
    tts, records, _ = provider(stream)
    pending = asyncio.create_task(anext(tts.synthesize("Hello.")))
    await stream.waiting.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stream.closed and tts._admitted == 0
    assert records[0]["outcome"] == "cancelled"
    await tts.aclose()


@pytest.mark.parametrize(
    "model", ["aura-thalia-en", "aura-2-thalia-es", "aura-2-thalia-en?x=1", ""]
)
def test_model_is_trusted_english_aura_2_slug(model: str) -> None:
    with pytest.raises(ValueError, match="Deepgram"):
        DeepgramTTS("test-secret", model=model)


@pytest.mark.parametrize("pcm", [b"", b"\0" * 3, b"\0" * 32002])
async def test_empty_odd_or_excessive_audio_is_rejected(pcm: bytes) -> None:
    stream = PCMStream([pcm])
    tts, records, _ = provider(stream)
    tts._max_bytes = 32000
    with pytest.raises(RuntimeError, match="^Deepgram synthesis failed$"):
        _ = [frame async for frame in tts.synthesize("Hello.")]
    assert stream.closed and records[0]["outcome"] == "error"
    await tts.aclose()


async def test_cancel_before_headers_releases_owned_request() -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    records: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("Unreachable")

    tts = DeepgramTTS(
        "test-secret",
        observer=records.append,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    consuming = asyncio.create_task(anext(tts.synthesize("A pending sentence.")))
    await entered.wait()
    consuming.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consuming
    assert cancelled.is_set() and tts._admitted == 0
    assert records[0]["first_byte_seconds"] is None
    await tts.aclose()


async def test_repeated_cancellation_preserves_cleanup_ownership() -> None:
    closing = asyncio.Event()
    release = asyncio.Event()

    class SlowClose(PCMStream):
        async def aclose(self) -> None:
            closing.set()
            await release.wait()
            self.closed = True

    stream = SlowClose([], block=True)
    tts, _, _ = provider(stream)
    consuming = asyncio.create_task(anext(tts.synthesize("A pending sentence.")))
    await stream.waiting.wait()
    consuming.cancel()
    await closing.wait()
    consuming.cancel()
    shutdown = asyncio.create_task(tts.aclose())
    await asyncio.sleep(0)
    shutdown.cancel()
    await asyncio.sleep(0)
    assert not consuming.done() and not shutdown.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await consuming
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    assert stream.closed and not tts._cleanup_tasks and tts._admitted == 0
    await tts.aclose()
