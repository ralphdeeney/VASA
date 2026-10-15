import asyncio
import base64
import binascii
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from vasa.contracts.models import AudioFrame
from vasa.evolution.models import MAX_BODY_BYTES, EvolutionError

READ_TIMEOUT_SECONDS = 10.0
# Existing one-second continuity threshold; a healthy frame is 60 ms.
GAP_OBSERVE_SECONDS = 1.0
# Two pinned meowcaller 12-second relay-connect budgets, not an asserted retry protocol.
RECOVERY_TIMEOUT_SECONDS = 24.0
FRAME_BYTES = 1920


@dataclass(slots=True)
class CallLifecycle:
    remote_terminated: bool = False
    terminated: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def terminate(self) -> None:
        self.remote_terminated = True
        self.terminated.set()


def parse_message(raw: str | bytes) -> dict[str, Any]:
    if len(raw) > MAX_BODY_BYTES:
        raise EvolutionError("invalid_response")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise EvolutionError("invalid_response") from None
    if not isinstance(result, dict) or not isinstance(result.get("event"), str):
        raise EvolutionError("invalid_response")
    return result


def decode_frame(message: dict[str, Any], sequence: int) -> AudioFrame:
    payload = message.get("payload")
    if message.get("track") != "inbound" or not isinstance(payload, str):
        raise EvolutionError("invalid_response")
    if len(payload) != 2560:
        raise EvolutionError("invalid_response")
    try:
        pcm = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        raise EvolutionError("invalid_response") from None
    if len(pcm) != FRAME_BYTES:
        raise EvolutionError("invalid_response")
    # Upstream has no timestamps/sequences. These are local receive metadata.
    return AudioFrame(pcm, 16000, sequence, time.monotonic_ns())


class MediaStream:
    def __init__(
        self, connection: ClientConnection, call_id: str, lifecycle: CallLifecycle | None = None
    ) -> None:
        self._connection = connection
        self._call_id = call_id
        self._pending: deque[AudioFrame] = deque()
        self._sequence = 0
        self._closed = False
        self._send_lock = asyncio.Lock()
        self._lifecycle = lifecycle or CallLifecycle()
        self.upstream_stopped = False
        self._last_frame_at: float | None = None
        self.recovery_expired = False

    @property
    def remote_terminated(self) -> bool:
        return self._lifecycle.remote_terminated

    async def _read(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(READ_TIMEOUT_SECONDS):
                raw = await self._connection.recv()
        except TimeoutError:
            print("CALL_MEDIA=read_timeout", flush=True)
            raise EvolutionError("unavailable") from None
        except (ConnectionClosed, OSError):
            print("CALL_MEDIA=read_closed", flush=True)
            raise EvolutionError("unavailable") from None
        return parse_message(raw)

    async def start(self) -> None:
        # One deadline for the entire handshake, including any raced media.
        try:
            async with asyncio.timeout(READ_TIMEOUT_SECONDS):
                while True:
                    message = await self._read()
                    event = message["event"]
                    if event == "start":
                        video = message.get("video", False)
                        if (
                            message.get("callId") != self._call_id
                            or type(message.get("sampleRate")) is not int
                            or message["sampleRate"] != 16000
                            or type(video) is not bool
                            or video
                        ):
                            raise EvolutionError("invalid_response")
                        self._last_frame_at = time.monotonic()
                        return
                    if event != "media" or len(self._pending) >= 4:
                        raise EvolutionError("invalid_response")
                    self._pending.append(decode_frame(message, self._sequence))
                    self._sequence += 1
        except TimeoutError:
            raise EvolutionError("unavailable") from None

    async def _read_active(self) -> dict[str, Any] | None:
        if self.remote_terminated:
            return None
        since = self._last_frame_at if self._last_frame_at is not None else time.monotonic()
        gap_deadline = since + GAP_OBSERVE_SECONDS
        deadline = since + RECOVERY_TIMEOUT_SECONDS
        reader = asyncio.create_task(self._connection.recv(), name="vasa-media-receive")
        terminated = asyncio.create_task(
            self._lifecycle.terminated.wait(), name="vasa-media-terminate"
        )
        observed = False
        try:
            while True:
                now = time.monotonic()
                if not observed and now >= gap_deadline:
                    observed = True
                    print("CALL_MEDIA=receive_gap_started", flush=True)
                if now >= deadline:
                    self.recovery_expired = True
                    print("CALL_MEDIA=recovery_grace_expired", flush=True)
                    raise EvolutionError("unavailable")
                wake = deadline if observed else gap_deadline
                done, _ = await asyncio.wait(
                    (reader, terminated),
                    timeout=max(0, wake - now),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reader in done:
                    return parse_message(reader.result())
                if terminated in done:
                    return None
                # Keep the SAME recv pending through the observation threshold.
                # No socket close/cancel/reopen occurs while awaiting recovery.
        except (ConnectionClosed, OSError):
            print("CALL_MEDIA=read_closed", flush=True)
            raise EvolutionError("unavailable") from None
        finally:
            for task in (reader, terminated):
                if not task.done():
                    task.cancel()
            await asyncio.gather(reader, terminated, return_exceptions=True)

    async def receive(self) -> AudioFrame | None:
        if self._closed:
            return None
        if self.remote_terminated:
            await self.close()
            return None
        if self._pending:
            return self._pending.popleft()
        try:
            message = await self._read_active()
            if message is None:
                await self.close()
                return None
            if message["event"] == "stop":
                # The pinned bridge closes on OnEnd and always hangs up when its
                # read loop exits. Do not issue a second control request for stop.
                self.upstream_stopped = True
                print("CALL_MEDIA=upstream_stop", flush=True)
                await self.close()
                return None
            if message["event"] != "media":
                raise EvolutionError("invalid_response")
            frame = decode_frame(message, self._sequence)
            self._sequence += 1
            now = time.monotonic()
            if self._last_frame_at is not None and now - self._last_frame_at >= GAP_OBSERVE_SECONDS:
                # Observed media continuity, not a claim about WhatsApp subtype 3.
                print("CALL_MEDIA=receive_gap\nCALL_MEDIA=receive_recovered", flush=True)
                elapsed_ms = min(999999, max(0, int((now - self._last_frame_at) * 1000)))
                print(f"CALL_MEDIA=receive_recovered_ms={elapsed_ms}", flush=True)
            self._last_frame_at = now
            return frame
        except EvolutionError as error:
            await self.close()
            if error.code == "unavailable" and self.remote_terminated:
                # A verified terminate is authoritative even if socket shutdown
                # wins the race with the bridge's best-effort stop envelope.
                return None
            raise

    async def send(self, frame: AudioFrame) -> None:
        if frame.sample_rate != 16000 or frame.channels != 1 or len(frame.pcm) != FRAME_BYTES:
            raise ValueError("Evolution audio requires 960 mono PCM16 samples at 16000 Hz")
        if self._closed:
            raise EvolutionError("unavailable")
        message = {
            "event": "media",
            "track": "outbound",
            "payload": base64.b64encode(frame.pcm).decode("ascii"),
        }
        try:
            async with self._send_lock, asyncio.timeout(READ_TIMEOUT_SECONDS):
                await self._connection.send(json.dumps(message))
        except (TimeoutError, ConnectionClosed, OSError):
            await self.close()
            raise EvolutionError("unavailable") from None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending.clear()
        try:
            async with asyncio.timeout(3):
                await self._connection.close()
        except (TimeoutError, ConnectionClosed, OSError):
            pass
