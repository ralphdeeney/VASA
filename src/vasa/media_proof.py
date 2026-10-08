"""Manual real-call gate: receive live caller audio and return a known diagnostic recording."""

import argparse
import asyncio
import json
import math
import struct
import time
import wave
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vasa.config import Settings
from vasa.contracts.models import AudioFrame, CallSession, CallState, TenantContext
from vasa.contracts.providers import EvolutionClient
from vasa.control.models import User, WhatsAppInstance
from vasa.evolution.client import EvolutionCalls
from vasa.evolution.models import EvolutionError, IncomingCall
from vasa.storage.cache import CallRegistry
from vasa.storage.database import Database


def diagnostic_recording(path: Path) -> None:
    """A fixed three-tone WAV for transport acceptance, not synthesized conversation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples: list[int] = []
    for frequency in (440, 660, 880):
        samples.extend(
            int(4000 * math.sin(2 * math.pi * frequency * i / 16000)) for i in range(4800)
        )
        samples.extend([0] * 1600)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def recording_frames(path: Path) -> list[AudioFrame]:
    with wave.open(str(path), "rb") as recording:
        if (
            recording.getnchannels() != 1
            or recording.getsampwidth() != 2
            or recording.getframerate() != 16000
            or recording.getcomptype() != "NONE"
            or not 0 < recording.getnframes() <= 160000
        ):
            raise ValueError("Recording must be mono PCM16 at 16000 Hz and at most 10 seconds")
        pcm = recording.readframes(recording.getnframes())
    frames = []
    for offset in range(0, len(pcm), 1920):
        frames.append(
            AudioFrame(pcm[offset : offset + 1920].ljust(1920, b"\0"), 16000, offset // 1920, 0)
        )
    return frames


async def prove_call(
    client: EvolutionClient,
    registry: CallRegistry,
    context: TenantContext,
    instance_id: str,
    incoming: IncomingCall,
    frames: list[AudioFrame],
    *,
    report_path: Path,
) -> dict[str, object]:
    if incoming.instance_id != instance_id:
        raise ValueError("Call does not belong to the selected instance")
    if (
        not frames
        or len(frames) > 167
        or any(frame.sample_rate != 16000 or len(frame.pcm) != 1920 for frame in frames)
    ):
        raise ValueError("Invalid bounded diagnostic recording")
    session = CallSession(uuid4(), context.tenant_id, instance_id, incoming.call_id)
    started = time.monotonic()
    report: dict[str, object] = {
        "session_id": str(session.id),
        "received_frames": 0,
        "sent_frames": 0,
        "state_transitions": [],
        "caller_heard_response": None,
        "acceptance": "pending_human_confirmation",
        "error": None,
        "audio_recorded": False,
    }
    transitions: list[dict[str, object]] = []
    received = sent = 0
    reader: asyncio.Task[None] | None = None

    async def state(value: CallState) -> None:
        nonlocal session
        session = replace(session, state=value)
        transitions.append(
            {"state": value.value, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}
        )
        await registry.put(session)

    try:
        async with asyncio.timeout(45):
            await state(CallState.RINGING)
            await state(CallState.ANSWERING)
            await client.answer(instance_id, incoming.call_id, incoming.caller_jid)
            await state(CallState.CONNECTED)
            async with client.open_media(instance_id, incoming.call_id) as stream:
                await state(CallState.LISTENING)
                # No output until at least one actual caller frame reaches VASA.
                first = await stream.receive()
                if first is None:
                    raise EvolutionError("unavailable")
                received = 1
                report["first_inbound_elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)

                async def receive_rest() -> None:
                    nonlocal received
                    while await stream.receive() is not None:
                        received += 1

                reader = asyncio.create_task(receive_rest())
                playback_start = time.monotonic()
                for index, frame in enumerate(frames):
                    if reader.done():
                        await reader
                        raise EvolutionError("unavailable")
                    await asyncio.sleep(max(0, playback_start + index * 0.06 - time.monotonic()))
                    await stream.send(frame)
                    sent += 1
                report["output_sent_elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
                # Let the caller hear the recording and hang up; do not wait forever.
                try:
                    await asyncio.wait_for(asyncio.shield(reader), timeout=10)
                except TimeoutError:
                    pass
            await state(CallState.ENDING)
    except (EvolutionError, TimeoutError) as error:
        report["error"] = error.code if isinstance(error, EvolutionError) else "timeout"
        report["acceptance"] = "failed"
        transitions.append({"state": CallState.ERROR.value})
        raise
    except RedisError:
        report["error"] = "cache_unavailable"
        report["acceptance"] = "failed"
        transitions.append({"state": CallState.ERROR.value})
        raise
    except asyncio.CancelledError:
        report["error"] = "cancelled"
        report["acceptance"] = "failed"
        raise
    finally:
        if reader is not None:
            reader.cancel()
            with suppress(asyncio.CancelledError, EvolutionError):
                await reader
        # Closing the upstream media stream also hangs up; explicitly attempt cleanup.
        try:
            await client.hangup(instance_id, incoming.call_id)
        except EvolutionError:
            report["hangup_acknowledged"] = False
        else:
            report["hangup_acknowledged"] = True
        try:
            async with asyncio.timeout(5):
                await registry.delete(context, session.id)
        finally:
            transitions.append(
                {
                    "state": CallState.ENDED.value,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
            report.update(received_frames=received, sent_frames=sent, state_transitions=transitions)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(report_path.write_text, json.dumps(report, indent=2) + "\n")
    return report


async def run(email: str, instance: UUID, audio: Path | None) -> None:
    settings = Settings()
    database = Database(settings.database_url.get_secret_value())
    cache = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_timeout=3, socket_connect_timeout=3
    )
    client = EvolutionCalls(
        settings.evolution_base_url,
        settings.evolution_admin_key.get_secret_value(),
        settings.evolution_stream_key.get_secret_value(),
        settings.evolution_instance_key.get_secret_value(),
    )
    try:
        async with database.session() as session:
            user = await session.scalar(select(User).where(User.email == email.strip().lower()))
            if user is None:
                raise ValueError("Unknown local user")
            mapping = await session.scalar(
                select(WhatsAppInstance).where(
                    WhatsAppInstance.id == instance, WhatsAppInstance.tenant_id == user.tenant_id
                )
            )
            if mapping is None:
                raise ValueError("Unknown instance for this user")
            context = TenantContext(user.tenant_id, user.id)
            external_id = mapping.external_id
        status = await client.status(external_id)
        if not status.connected or not status.logged_in:
            raise ValueError("WhatsApp pairing must complete first")
        if audio is None:
            audio = Path(".local/media-proof.wav")
            if not audio.exists():
                await asyncio.to_thread(diagnostic_recording, audio)
        frames = await asyncio.to_thread(recording_frames, audio)
        print("Waiting up to 120 seconds for one real inbound WhatsApp call.")
        print("Say a few words; listen for three rising tones, then hang up.")
        async with asyncio.timeout(120):
            async for incoming in client.events(external_id):
                path = Path(f".local/media-proof-{uuid4()}.json")
                report = await prove_call(
                    client,
                    CallRegistry(cache),
                    context,
                    external_id,
                    incoming,
                    frames,
                    report_path=path,
                )
                print(f"Received {report['received_frames']} frames; sent {report['sent_frames']}.")
                print(f"Report: {path}; hearing the response still needs human confirmation.")
                return
        raise EvolutionError("unavailable")
    finally:
        await client.aclose()
        await cache.aclose()
        await database.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--instance", required=True, type=UUID)
    parser.add_argument("--audio", type=Path)
    options = parser.parse_args()
    try:
        asyncio.run(run(options.email, options.instance, options.audio))
    except (EvolutionError, TimeoutError) as error:
        code = error.code if isinstance(error, EvolutionError) else "timeout"
        parser.exit(1, f"Media acceptance is blocked or failed: {code}.\n")
    except ValueError:
        parser.exit(
            1, "Check the local user, paired instance, service keys and recording format.\n"
        )
    except (OSError, RedisError, SQLAlchemyError):
        parser.exit(1, "Required local service or diagnostic recording is unavailable.\n")


if __name__ == "__main__":
    main()
