"""Optional Simba streaming adapter; no speech is cached or retained across calls.

Protocol: https://docs.speechify.ai/build/api-reference/v1/audio/stream
PCM/version: https://docs.speechify.ai/build/guides/concepts/audio-formats
https://docs.speechify.ai/build/guides/concepts/api-versioning
The pinned API version defines pcm_16000 as little-endian mono signed PCM16.
"""

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable
from email.message import Message
from typing import Any

import httpx

from vasa.contracts.models import AudioFrame
from vasa.speech.synthesis import text_chunks

Observer = Callable[[dict[str, Any]], None]


async def _finish_cleanup(awaitable: Any) -> None:
    """Finish owned network cleanup even under repeated consumer cancellation."""
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


def _timing(value: str, secret: str) -> tuple[str | None, float | None]:
    # Retain only bounded numeric durations; vendor descriptions can contain secrets.
    safe: list[str] = []
    ttfb = None
    for entry in value[:2048].split(",")[:32]:
        match = re.fullmatch(
            r"\s*([A-Za-z][A-Za-z0-9_-]{0,31})\s*;\s*"
            r"dur=([0-9]{1,9}(?:\.[0-9]{1,6})?)(?:\s*;.*)?\s*",
            entry,
        )
        if match and secret not in match.group(0):
            name, duration = match.groups()
            safe.append(f"{name};dur={duration}")
            if name.lower() == "ttfb":
                ttfb = float(duration) / 1000
    return ", ".join(safe) or None, ttfb


class SpeechifyTTS:
    """One pooled client, sequential streams, bounded PCM carry and admission.

    An injected client transfers ownership to this provider and is closed at shutdown.
    """

    _default_origin = "https://api.speechify.ai"
    _path = "/v1/audio/stream"
    _provider_label = "Speechify"

    def __init__(
        self,
        api_key: str,
        *,
        voice_id: str = "geffen_32",
        client: httpx.AsyncClient | None = None,
        observer: Observer | None = None,
        base_url: str = "https://api.speechify.ai",
        request_timeout: float = 60.0,
        max_audio_seconds: int = 120,
        max_streams: int = 10,
    ) -> None:
        if not api_key or len(api_key) > 4096 or any(c.isspace() for c in api_key):
            raise ValueError(f"Invalid {self._provider_label} credential")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", voice_id):
            raise ValueError(f"Invalid {self._provider_label} voice")
        if not 0 < request_timeout <= 180 or not 1 <= max_audio_seconds <= 180:
            raise ValueError(f"Invalid {self._provider_label} bounds")
        if isinstance(max_streams, bool) or not 1 <= max_streams <= 10:
            raise ValueError(f"Invalid {self._provider_label} admission bound")
        if base_url != self._default_origin and client is None:
            raise ValueError(
                f"Custom {self._provider_label} origin requires an injected test client"
            )
        self._client = client or httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=1, max_keepalive_connections=1, keepalive_expiry=120
            ),
            timeout=httpx.Timeout(15, connect=10, pool=10),
            follow_redirects=False,
        )
        self._key = api_key
        self._voice = voice_id
        self._url = base_url.rstrip("/") + self._path
        self._observer = observer
        self._deadline = request_timeout
        self._max_bytes = max_audio_seconds * 32000
        self._max_streams = max_streams
        self._admitted = 0
        self._slot = asyncio.Lock()
        self._responses: set[httpx.Response] = set()
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    def _build_request(self, text: str, trace: Any) -> httpx.Request:
        return self._client.build_request(
            "POST",
            self._url,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Accept": "audio/pcm",
                "Speechify-Version": "2026-09-30",
                "Accept-Encoding": "identity",
            },
            json={
                "input": text,
                "voice_id": self._voice,
                "model": "simba-3.2",
                "output_format": "pcm_16000",
            },
            extensions={"trace": trace},
        )

    def _response_metadata(self, response: httpx.Response, metrics: dict[str, Any]) -> None:
        metrics["server_timing"], metrics["server_ttfb_seconds"] = _timing(
            response.headers.get("server-timing", ""), self._key
        )

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        text_chunks(text)
        if self._closed:
            raise RuntimeError(f"{self._provider_label} provider closed")
        if self._admitted >= self._max_streams:
            raise RuntimeError(f"{self._provider_label} provider busy")
        self._admitted += 1
        response: httpx.Response | None = None
        acquired = False
        started = time.monotonic()
        metrics: dict[str, Any] = {
            "first_byte_seconds": None,
            "first_playable_seconds": None,
            "full_response_seconds": None,
            "audio_seconds": 0.0,
            "bytes_received": 0,
            "http_status": None,
            "server_timing": None,
            "server_ttfb_seconds": None,
            "local_network_overhead_estimate_seconds": None,
            "network_overhead_negative": False,
            "max_read_wait_seconds": 0.0,
            "max_stream_read_wait_seconds": 0.0,
            "body_arrival_gaps": [],
            "body_arrival_gaps_truncated": False,
            "max_body_arrival_gap_seconds": 0.0,
            "conversion_seconds": 0.0,
            "framing_seconds": 0.0,
            "connect_tcp_count": 0,
            "tls_count": 0,
            "connection_id": None,
            "outcome": "error",
            "cancellation_cleanup_seconds": None,
        }

        async def trace(event: str, info: dict[str, Any]) -> None:
            if event.endswith(".connect_tcp.started"):
                metrics["connect_tcp_count"] += 1
            elif event.endswith(".start_tls.started"):
                metrics["tls_count"] += 1

        def remaining() -> float:
            value = self._deadline - (time.monotonic() - started)
            if value <= 0:
                raise TimeoutError
            return value

        try:
            await asyncio.wait_for(self._slot.acquire(), timeout=min(10, remaining()))
            acquired = True
            if self._closed:
                raise RuntimeError(f"{self._provider_label} provider closed")
            request = self._build_request(text, trace)
            response = await asyncio.wait_for(self._client.send(request, stream=True), remaining())
            self._responses.add(response)
            if self._closed:
                raise RuntimeError(f"{self._provider_label} provider closed")
            metrics["http_status"] = response.status_code
            self._response_metadata(response, metrics)
            network = response.extensions.get("network_stream")
            if network is not None:
                metrics["connection_id"] = id(network)
            if response.status_code != 200:
                raise RuntimeError(f"{self._provider_label} HTTP failure")
            content_type = Message()
            content_type["content-type"] = response.headers.get("content-type", "")
            if (
                content_type.get_content_type() not in {"audio/l16", "audio/pcm"}
                or content_type.get_param("rate") != "16000"
                or content_type.get_param("channels", "1") != "1"
                or response.headers.get("content-encoding", "identity").lower() != "identity"
            ):
                raise RuntimeError(f"{self._provider_label} PCM format mismatch")
            carry = bytearray()
            sequence = 0
            previous_byte: float | None = None
            iterator = response.aiter_raw(chunk_size=None).__aiter__()
            while True:
                before_read = time.monotonic()
                try:
                    chunk = await asyncio.wait_for(anext(iterator), remaining())
                except StopAsyncIteration:
                    break
                now = time.monotonic()
                metrics["max_read_wait_seconds"] = max(
                    metrics["max_read_wait_seconds"], now - before_read
                )
                if previous_byte is not None:
                    metrics["max_stream_read_wait_seconds"] = max(
                        metrics["max_stream_read_wait_seconds"], now - before_read
                    )
                if not chunk:
                    continue
                if previous_byte is not None:
                    gap = now - previous_byte
                    metrics["max_body_arrival_gap_seconds"] = max(
                        metrics["max_body_arrival_gap_seconds"], gap
                    )
                    if len(metrics["body_arrival_gaps"]) < 256:
                        metrics["body_arrival_gaps"].append(gap)
                    else:
                        metrics["body_arrival_gaps_truncated"] = True
                previous_byte = now
                if metrics["first_byte_seconds"] is None:
                    metrics["first_byte_seconds"] = now - started
                metrics["bytes_received"] += len(chunk)
                metrics["audio_seconds"] = metrics["bytes_received"] / 32000
                if metrics["bytes_received"] > self._max_bytes:
                    raise RuntimeError(f"{self._provider_label} audio limit exceeded")
                carry.extend(chunk)
                while len(carry) >= 1920:
                    if self._closed:
                        raise RuntimeError(f"{self._provider_label} provider closed")
                    framing_start = time.monotonic()
                    frame = AudioFrame(bytes(carry[:1920]), 16000, sequence, sequence * 60_000_000)
                    del carry[:1920]
                    sequence += 1
                    metrics["framing_seconds"] += time.monotonic() - framing_start
                    if metrics["first_playable_seconds"] is None:
                        metrics["first_playable_seconds"] = time.monotonic() - started
                    yield frame
            metrics["full_response_seconds"] = time.monotonic() - started
            if not metrics["bytes_received"] or len(carry) % 2:
                raise RuntimeError(f"{self._provider_label} invalid PCM length")
            if carry:
                if self._closed:
                    raise RuntimeError(f"{self._provider_label} provider closed")
                framing_start = time.monotonic()
                frame = AudioFrame(
                    bytes(carry).ljust(1920, b"\0"), 16000, sequence, sequence * 60_000_000
                )
                metrics["framing_seconds"] += time.monotonic() - framing_start
                if metrics["first_playable_seconds"] is None:
                    metrics["first_playable_seconds"] = time.monotonic() - started
                yield frame
            metrics["outcome"] = "complete"
        except (asyncio.CancelledError, GeneratorExit):
            metrics["outcome"] = "cancelled"
            raise
        except Exception:
            raise RuntimeError(f"{self._provider_label} synthesis failed") from None
        finally:
            cleanup_started = time.monotonic()
            try:
                if response is not None:
                    await self._close_response(response)
            finally:
                if response is not None:
                    self._responses.discard(response)
                if acquired:
                    self._slot.release()
                self._admitted -= 1
                if metrics["outcome"] == "cancelled":
                    metrics["cancellation_cleanup_seconds"] = time.monotonic() - cleanup_started
                server_ttfb = metrics["server_ttfb_seconds"]
                if server_ttfb is not None and metrics["first_playable_seconds"] is not None:
                    estimate = metrics["first_playable_seconds"] - server_ttfb
                    metrics["local_network_overhead_estimate_seconds"] = estimate
                    metrics["network_overhead_negative"] = estimate < 0
                if self._observer is not None:
                    self._observer(metrics)

    async def _close_response(self, response: httpx.Response) -> None:
        async def bounded_close() -> None:
            try:
                await asyncio.wait_for(response.aclose(), 5)
            except Exception:
                raise RuntimeError(f"{self._provider_label} stream cleanup failed") from None

        task = asyncio.create_task(bounded_close())
        self._cleanup_tasks.add(task)
        try:
            await _finish_cleanup(asyncio.shield(task))
        finally:
            self._cleanup_tasks.discard(task)

    async def _close(self) -> None:
        try:
            for response in tuple(self._responses):
                await self._close_response(response)
            if self._cleanup_tasks:
                await asyncio.gather(*tuple(self._cleanup_tasks))
        finally:
            try:
                await asyncio.wait_for(self._client.aclose(), 5)
            except Exception:
                raise RuntimeError(f"{self._provider_label} client cleanup failed") from None

    async def aclose(self) -> None:
        self._closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await _finish_cleanup(asyncio.shield(self._close_task))
