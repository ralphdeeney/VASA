"""Benchmark methodology checks using in-memory PCM, never live Speechify credentials."""

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmark_speechify_vps import (
    benchmark_text,
    cancellation_probe,
    direct_response,
    load_baseline,
    parser,
    percentile,
    run,
    summary_rows,
)
from vasa.contracts.models import AudioFrame
from vasa.runtime.conversation import _chunks


def test_unseen_varied_balanced_categories() -> None:
    entries = [benchmark_text(index) for index in range(60)]
    assert len({text for _, text in entries}) == 60
    assert [category for category, _ in entries].count("sentence") == 20
    assert all(text.count(".") == 4 for category, text in entries if category == "long")
    chunks = [chunk for _, text in entries for chunk in _chunks(text, final=True)[0]]
    assert len(set(chunks)) == len(chunks)


def test_percentiles_and_failed_denominator() -> None:
    assert percentile([], 0.95) is None
    assert percentile([1, 3], 0.5) == 2
    assert percentile([1, 3], 0.95) == pytest.approx(2.9)
    rows = [
        {
            "mode": "direct",
            "category": "sentence",
            "outcome": "complete",
            "first_playable_seconds": 0.2,
            "max_frame_starvation_seconds": 0,
            "effective_rtf": 0.1,
            "process_cpu_seconds": 0.01,
            "peak_rss_mib": 50,
        },
        {"mode": "direct", "category": "sentence", "outcome": "failed"},
    ]
    result = summary_rows(rows)["direct/sentence"]
    assert result["attempts"] == 2
    assert result["failed"] == 1
    assert result["first_playable_p90_seconds"] == 0.2


def test_baseline_rejects_cloud_and_wrong_candidate(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"scope": "cloud-smoke", "actual_vps": False}))
    with pytest.raises(ValueError, match="actual_vps"):
        load_baseline(path, "piper")
    path.write_text(json.dumps({"scope": "vps", "actual_vps": True, "candidate": "kokoro-int8"}))
    with pytest.raises(ValueError, match="wrong candidate"):
        load_baseline(path, "piper")
    assert load_baseline(path, "kokoro-int8") is not None


def test_default_methodology() -> None:
    args = parser().parse_args([])
    assert args.requests == 30
    assert args.mode == "both"
    assert args.scope == "vps"
    assert args.cpus == [0, 1]
    assert args.with_stt is False
    assert parser().parse_args(["--with-stt"]).with_stt is True


def test_direct_filename_help_without_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_speechify_vps.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    assert "--requests" in completed.stdout


async def test_missing_key_fails_before_creating_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SPEECHIFY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="privately"):
        await run(argparse.Namespace(output=tmp_path / "absent"))
    assert not (tmp_path / "absent").exists()


async def test_direct_stream_frames_and_cancellation() -> None:
    import asyncio

    class Provider:
        closed = 0

        async def synthesize(self, text: str):
            try:
                while True:
                    yield AudioFrame(
                        pcm=b"\x01\x00" * 960, sample_rate=16000, sequence=0, timestamp_ns=0
                    )
                    await asyncio.sleep(0.01)
            finally:
                self.closed += 1

    provider = Provider()
    result = await cancellation_probe(provider, True)
    assert result["frames_before_cancel"] == 1
    assert result["frames_after_cancel"] == 0
    assert provider.closed == 1

    class FiniteProvider:
        async def synthesize(self, text: str):
            yield AudioFrame(pcm=b"\x01\x00" * 960, sample_rate=16000, sequence=0, timestamp_ns=0)
            yield AudioFrame(pcm=b"\x02\x00" * 960, sample_rate=16000, sequence=1, timestamp_ns=0)

    direct = await direct_response(FiniteProvider(), "Synthetic benchmark text.")
    assert direct["audio_seconds"] == 0.12
    assert len(direct["pcm"]) == 3840


async def test_full_mock_run_warmups_reuse_modes_and_no_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    import scripts.benchmark_speechify_vps as benchmark

    constructed = []
    texts = []
    active = 0
    stt_loads = []

    class FakeSTTLoad:
        def __init__(self, model, fixture, *, num_threads):
            assert num_threads == 1
            stt_loads.append(self)
            self.error = None
            self.stop = threading.Event()
            self.ready = threading.Event()
            self.ready.set()
            self.results = []
            self.thread = SimpleNamespace(
                start=self.start, join=lambda _: None, is_alive=lambda: False
            )

        def start(self):
            self.results.append(
                {
                    "completed": True,
                    "word_error_rate": 0,
                    "max_frame_processing_deadline_overrun_seconds": 0,
                    "deadline_misses": 0,
                }
            )

    class Provider:
        def __init__(self, key, *, voice_id, observer):
            assert key == "private-test-key"
            constructed.append(self)
            self.observer = observer

        async def synthesize(self, text):
            nonlocal active
            active += 1
            assert active == 1
            texts.append(text)
            first = None
            complete = False
            try:
                await asyncio.sleep(0.02)
                first = 0.02
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
                        "full_response_seconds": 0.02,
                        "connect_tcp_count": int(len(texts) == 1),
                        "tls_count": int(len(texts) == 1),
                    }
                )

        async def aclose(self):
            assert active == 0

    monkeypatch.setenv("SPEECHIFY_API_KEY", "private-test-key")
    monkeypatch.setattr(benchmark, "SpeechifyTTS", Provider)
    monkeypatch.setattr(benchmark, "STTLoad", FakeSTTLoad)
    monkeypatch.setattr(benchmark, "system_information", lambda: {})
    monkeypatch.setattr(benchmark, "container_snapshot", lambda: {"available": False})
    monkeypatch.setattr(benchmark.os, "sched_getaffinity", lambda _: {0, 1})
    monkeypatch.setattr(benchmark.os, "sched_setaffinity", lambda *_: None)
    args = parser().parse_args(
        ["--scope", "component-smoke", "--requests", "20", "--with-stt", "--output", str(tmp_path)]
    )
    assert await run(args) == 0
    record = json.loads((tmp_path / "measurements.json").read_text())
    assert record["actual_vps"] is False
    assert len(record["warmups"]) == 2
    assert all(len(item["http_requests"]) == 1 for item in record["warmups"])
    assert len(record["requests"]) == 40
    assert {row["mode"] for row in record["requests"]} == {"direct", "buffered"}
    assert len(constructed) == 1
    assert len(texts) == len(set(texts))
    assert all(probe["frames_after_cancel"] == 0 for probe in record["cancellation"])
    assert "private-test-key" not in (tmp_path / "measurements.json").read_text()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["connection_evidence"]["connect_tcp_events"] == 1
    assert summary["statistics"]["direct/all"]["complete"] == 20
    assert summary["statistics"]["buffered/all"]["complete"] == 20
    assert len(stt_loads) == 2
    assert all(load.stop.is_set() for load in stt_loads)
    assert summary["stt"]["enabled"] is True
    assert summary["stt"]["baseline"]["complete_fixtures"] == 1
    assert summary["stt"]["contender"]["max_word_error_rate"] == 0


async def test_failed_warmup_writes_partial_evidence_without_exception_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    import scripts.benchmark_speechify_vps as benchmark

    class Provider:
        def __init__(self, key, *, voice_id, observer):
            self.observer = observer

        async def synthesize(self, text):
            self.observer({"outcome": "failed", "http_status": 429})
            raise RuntimeError("Sensitive vendor response: private-test-key")
            yield  # pragma: no cover -- async generator signature

        async def aclose(self):
            pass

    monkeypatch.setenv("SPEECHIFY_API_KEY", "private-test-key")
    monkeypatch.setattr(benchmark, "SpeechifyTTS", Provider)
    monkeypatch.setattr(benchmark, "system_information", lambda: {})
    monkeypatch.setattr(benchmark, "container_snapshot", lambda: {"available": False})
    monkeypatch.setattr(benchmark.os, "sched_getaffinity", lambda _: {0, 1})
    monkeypatch.setattr(benchmark.os, "sched_setaffinity", lambda *_: None)
    args = parser().parse_args(
        ["--scope", "component-smoke", "--requests", "20", "--output", str(tmp_path)]
    )
    assert await run(args) == 1
    text = (tmp_path / "measurements.json").read_text()
    record = json.loads(text)
    assert record["complete"] is False
    assert record["failure_type"] == "RuntimeError"
    assert len(record["warmups"]) == 1
    assert record["warmups"][0]["http_requests"][0]["http_status"] == 429
    assert record["requests"] == []
    assert not await asyncio.to_thread(lambda: list(tmp_path.glob("*.wav")))
    assert "private-test-key" not in text
    assert "Sensitive vendor" not in text
