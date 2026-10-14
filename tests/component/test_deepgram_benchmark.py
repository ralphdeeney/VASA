"""Aura benchmark wiring uses synthetic audio and never live API credentials."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.benchmark_deepgram_vps as deepgram
import scripts.benchmark_speechify_vps as shared
from vasa.contracts.models import AudioFrame


def test_aura_default_profile() -> None:
    args = deepgram.parser().parse_args([])
    assert args.model == "aura-2-thalia-en"
    assert args.requests == 30
    assert args.mode == "both"
    assert args.scope == "vps"
    assert args.cpus == [0, 1]
    assert not args.with_stt
    assert not hasattr(args, "voice_id")
    assert args.output == Path("docs/tts-evaluation/deepgram-aura-2-vps/vps")
    assert deepgram.metadata(args)["container"] == "none"
    assert deepgram.metadata(args)["sample_rate"] == 16000
    assert "speechify_api_version" not in deepgram.metadata(args)


def test_direct_filename_help_without_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    result = subprocess.run(
        [sys.executable, "scripts/benchmark_deepgram_vps.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert "--model" in result.stdout
    assert "--voice-id" not in result.stdout
    assert "--api-key" not in result.stdout


async def test_missing_aura_key_ignores_speechify_key_before_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setenv("SPEECHIFY_API_KEY", "not-the-aura-key")
    output = tmp_path / "absent"
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
        await deepgram.run(argparse.Namespace(output=output))
    assert not output.exists()


async def test_mock_aura_modes_one_client_warmups_and_safe_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    instances = []
    texts = []
    active = 0

    class Provider:
        def __init__(self, key, *, model, observer):
            assert key == "private-aura-test-key"
            assert model == "aura-2-thalia-en"
            self.observer = observer
            instances.append(self)

        async def synthesize(self, text):
            nonlocal active
            active += 1
            assert active == 1
            texts.append(text)
            first = None
            complete = False
            try:
                await asyncio.sleep(0.01)
                first = 0.01
                yield AudioFrame(
                    pcm=b"\x01\x00" * 960, sample_rate=16000, sequence=0, timestamp_ns=0
                )
                complete = True
            finally:
                active -= 1
                self.observer(
                    {
                        "outcome": "complete" if complete else "cancelled",
                        "first_byte_seconds": first,
                        "first_playable_seconds": first,
                        "audio_seconds": 0.06 if first is not None else 0,
                        "full_response_seconds": 0.01,
                        "connect_tcp_count": int(len(texts) == 1),
                        "tls_count": int(len(texts) == 1),
                        "requested_model": model,
                        "response_model": None,
                        "response_model_uuid": None,
                        "request_id": None,
                    }
                )

        async def aclose(self):
            assert active == 0

    # Model value is intentionally fixed trusted benchmark configuration.
    model = "aura-2-thalia-en"
    monkeypatch.setenv("DEEPGRAM_API_KEY", "private-aura-test-key")
    monkeypatch.setattr(deepgram, "DeepgramTTS", Provider)
    monkeypatch.setattr(shared, "system_information", lambda: {})
    monkeypatch.setattr(shared, "container_snapshot", lambda: {"available": False})
    monkeypatch.setattr(shared.os, "sched_getaffinity", lambda _: {0, 1})
    monkeypatch.setattr(shared.os, "sched_setaffinity", lambda *_: None)
    args = deepgram.parser().parse_args(
        ["--scope", "component-smoke", "--requests", "20", "--output", str(tmp_path)]
    )
    assert await deepgram.run(args) == 0
    record = json.loads((tmp_path / "measurements.json").read_text())
    assert record["candidate"] == "deepgram"
    assert record["model"] == model
    assert record["actual_vps"] is False
    assert len(record["warmups"]) == 2
    assert len(record["requests"]) == 40
    assert {row["mode"] for row in record["requests"]} == {"direct", "buffered"}
    assert len(instances) == 1
    assert len(texts) == len(set(texts))
    assert all(probe["frames_after_cancel"] == 0 for probe in record["cancellation"])
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["connection_evidence"]["connect_tcp_events"] == 1
    assert summary["production_default_changed"] is False
    assert summary["human_listening"] == "pending"
    evidence = await asyncio.to_thread(
        lambda: "".join(file.read_text() for file in tmp_path.glob("*.json"))
    )
    assert "private-aura-test-key" not in evidence
    assert len(await asyncio.to_thread(lambda: list(tmp_path.glob("*.wav")))) == 60


async def test_failed_aura_warmup_redacts_vendor_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Provider:
        def __init__(self, key, *, model, observer):
            self.observer = observer

        async def synthesize(self, text):
            self.observer({"outcome": "failed", "http_status": 401})
            raise RuntimeError("private-aura-test-key sensitive vendor response")
            yield  # pragma: no cover

        async def aclose(self):
            pass

    monkeypatch.setenv("DEEPGRAM_API_KEY", "private-aura-test-key")
    monkeypatch.setattr(deepgram, "DeepgramTTS", Provider)
    monkeypatch.setattr(shared, "system_information", lambda: {})
    monkeypatch.setattr(shared, "container_snapshot", lambda: {"available": False})
    monkeypatch.setattr(shared.os, "sched_getaffinity", lambda _: {0, 1})
    monkeypatch.setattr(shared.os, "sched_setaffinity", lambda *_: None)
    args = deepgram.parser().parse_args(
        ["--scope", "component-smoke", "--requests", "20", "--output", str(tmp_path)]
    )
    assert await deepgram.run(args) == 1
    text = (tmp_path / "measurements.json").read_text()
    record = json.loads(text)
    assert record["failure_type"] == "RuntimeError"
    assert record["warmups"][0]["http_requests"][0]["http_status"] == 401
    assert record["requests"] == []
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("*.wav")))
    assert "private-aura-test-key" not in text
    assert "sensitive vendor" not in text
