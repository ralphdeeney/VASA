import asyncio
import json
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from vasa.contracts.models import AudioFrame, CallState, TenantContext
from vasa.evolution.models import EvolutionError, IncomingCall
from vasa.media_proof import diagnostic_recording, prove_call, recording_frames


def test_diagnostic_recording_is_bounded_pcm(tmp_path: Path) -> None:
    path = tmp_path / "probe.wav"
    diagnostic_recording(path)
    with wave.open(str(path)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
    frames = recording_frames(path)
    assert len(frames) == 20
    assert all(len(frame.pcm) == 1920 for frame in frames)
    assert len({frame.pcm for frame in frames}) > 1


def test_rejects_wrong_recording_format(tmp_path: Path) -> None:
    path = tmp_path / "wrong.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0" * 1920)
    with pytest.raises(ValueError):
        recording_frames(path)


class Registry:
    def __init__(self):
        self.states = []
        self.deleted = []

    async def put(self, call):
        self.states.append(call.state)

    async def delete(self, context, call_id):
        self.deleted.append((context, call_id))


class Client:
    def __init__(self, failure=False):
        self.failure = failure
        self.answered = []
        self.hung_up = []
        self.closed = False
        self.sent = []
        self.receives = 0
        self.finished = asyncio.Event()

    async def answer(self, *args):
        self.answered.append(args)
        if self.failure:
            raise EvolutionError("license_required")

    async def hangup(self, *args):
        self.hung_up.append(args)

    @asynccontextmanager
    async def open_media(self, *args):
        try:
            yield self
        finally:
            self.closed = True

    async def receive(self):
        self.receives += 1
        if self.receives == 1:
            return AudioFrame(b"\x01\x00" * 960, 16000, 0, 0)
        await self.finished.wait()
        return None

    async def send(self, frame):
        assert self.receives >= 1, "caller audio must arrive before output"
        self.sent.append(frame)
        self.finished.set()


async def test_probe_reports_component_evidence_without_claiming_human_acceptance(tmp_path: Path):
    context = TenantContext(uuid4(), uuid4())
    incoming = IncomingCall("instance", "call", "123@s.whatsapp.net")
    client, registry = Client(), Registry()
    report_path = tmp_path / "report.json"
    report = await prove_call(
        client,
        registry,
        context,
        "instance",
        incoming,
        [AudioFrame(b"\0" * 1920, 16000, 0, 0)],
        report_path=report_path,
    )
    assert report["received_frames"] == report["sent_frames"] == 1
    assert report["caller_heard_response"] is None
    assert report["acceptance"] == "pending_human_confirmation"
    assert report["audio_recorded"] is False
    assert client.closed and client.hung_up
    assert registry.states == [
        CallState.RINGING,
        CallState.ANSWERING,
        CallState.CONNECTED,
        CallState.LISTENING,
        CallState.ENDING,
    ]
    assert len(registry.deleted) == 1
    assert json.loads(report_path.read_text())["state_transitions"][-1]["state"] == "ENDED"


async def test_failed_answer_still_cleans_call_state_and_preserves_failure_evidence(tmp_path: Path):
    context = TenantContext(uuid4(), uuid4())
    client, registry = Client(failure=True), Registry()
    path = tmp_path / "report.json"
    with pytest.raises(EvolutionError, match="license_required"):
        await prove_call(
            client,
            registry,
            context,
            "instance",
            IncomingCall("instance", "call", "123@s.whatsapp.net"),
            [AudioFrame(b"\0" * 1920, 16000, 0, 0)],
            report_path=path,
        )
    report = json.loads(path.read_text())
    assert report["acceptance"] == "failed"
    assert report["error"] == "license_required"
    assert report["sent_frames"] == report["received_frames"] == 0
    assert len(registry.deleted) == len(client.hung_up) == 1
    assert client.sent == []


async def test_foreign_instance_rejected_before_any_call_operation(tmp_path: Path):
    client, registry = Client(), Registry()
    with pytest.raises(ValueError):
        await prove_call(
            client,
            registry,
            TenantContext(uuid4(), uuid4()),
            "owned",
            IncomingCall("foreign", "call", "123@s.whatsapp.net"),
            [AudioFrame(b"\0" * 1920, 16000, 0, 0)],
            report_path=tmp_path / "report.json",
        )
    assert not client.answered and not client.hung_up and not registry.states


async def test_cancellation_closes_media_and_cleans_session(tmp_path: Path):
    entered = asyncio.Event()

    class WaitingClient(Client):
        async def receive(self):
            self.receives += 1
            entered.set()
            await asyncio.Event().wait()

    client, registry = WaitingClient(), Registry()
    path = tmp_path / "cancelled.json"
    task = asyncio.create_task(
        prove_call(
            client,
            registry,
            TenantContext(uuid4(), uuid4()),
            "instance",
            IncomingCall("instance", "call", "123@s.whatsapp.net"),
            [AudioFrame(b"\0" * 1920, 16000, 0, 0)],
            report_path=path,
        )
    )
    async with asyncio.timeout(2):
        await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.closed and len(client.hung_up) == len(registry.deleted) == 1
    assert json.loads(path.read_text())["error"] == "cancelled"
