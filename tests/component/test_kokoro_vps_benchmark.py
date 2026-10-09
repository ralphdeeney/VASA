import struct
import sys
from pathlib import Path

import pytest

from scripts import benchmark_kokoro_int8_vps as benchmark
from scripts.benchmark_kokoro_int8_vps import (
    buffered_response,
    cancellation,
    default_model_path,
    provider_for,
    response,
    segments,
    summarize,
    validate_scope,
    word_error_rate,
)
from vasa.contracts.models import AudioFrame


def test_parent_uses_importable_module_for_fresh_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduction must work without an inherited project PYTHONPATH."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--scope",
            "cloud-smoke",
            "--condition",
            "A",
            "--candidate",
            "kitten-micro",
            "--output",
            str(tmp_path / "cloud-smoke" / "kitten"),
        ],
    )
    monkeypatch.setattr(benchmark.os, "sched_setaffinity", lambda *_: None)
    invoked: list[list[str]] = []
    monkeypatch.setattr(benchmark.subprocess, "run", lambda command, **_: invoked.append(command))
    benchmark.main()
    assert len(invoked) == 1
    assert invoked[0][:3] == [sys.executable, "-m", "scripts.benchmark_kokoro_int8_vps"]
    assert invoked[0][-1] == "--child"


def test_vps_guard_rejects_root_and_non_project_checkout() -> None:
    with pytest.raises(ValueError, match="non-root"):
        validate_scope("vps", Path("/opt/vasa"), 0, True, "A")
    with pytest.raises(ValueError, match="non-root"):
        validate_scope("vps", Path("/tmp"), 1000, True, "B")
    validate_scope("cloud-smoke", Path("/tmp"), 1000, False, "A")


def test_segmentation_preserves_sentences_and_word_error_counts_edits() -> None:
    assert segments("Certainly. Your appointment is confirmed.") == [
        "Certainly.",
        "Your appointment is confirmed.",
    ]
    assert word_error_rate("YOUR APPOINTMENT IS CONFIRMED", "YOUR APPOINTMENT CONFIRMED") == 0.25
    assert word_error_rate("ONE TWO", "ONE THREE TWO") == 0.5
    long = " ".join(["business"] * 80)
    pieces = segments(long)
    assert max(map(len, pieces)) <= 200
    assert " ".join(pieces) == long


def test_candidate_paths_and_unseen_cache_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import vasa.speech.kokoro as kokoro

    calls = []

    def fake_provider(model, **kwargs):
        calls.append((model, kwargs))
        return object()

    monkeypatch.setattr(kokoro, "KokoroInt8TTS", fake_provider)
    for candidate in ("kitten-micro", "kokoro-int8", "piper"):
        assert default_model_path(candidate) == Path(".local/speech") / candidate
    provider_for("kokoro-int8", Path("model"), disable_cache=True)
    assert calls == [(Path("model"), {"num_threads": 1, "cache_bytes": 0})]
    with pytest.raises(ValueError, match="Unknown"):
        provider_for("unknown", Path("model"))


def test_summary_excludes_incomplete_stt_and_records_percentile_sample_count() -> None:
    def stt_row(complete: bool, wall: float) -> dict:
        return {
            "completed": complete,
            "wall_seconds": wall,
            "word_error_rate": 0.1 if complete else None,
            "max_frame_processing_deadline_overrun_seconds": 0.01,
        }

    row = {
        "first_playable_seconds": 0.5,
        "real_time_factor": 0.2,
        "process_cpu_seconds": 1,
        "process_cpu_utilization_percent": 20,
        "audio_seconds": 5,
        "peak_rss_mib": 200,
        "max_chunk_starvation_seconds": 0,
        "max_frame_starvation_seconds": 0.001,
    }
    report = {
        "scope": "cloud-smoke",
        "candidate": "kitten-micro",
        "condition": "B",
        "model_load_seconds": 1,
        "rows": [dict(row, case=case) for case in ("short", "sentence", "long")],
        "cancellation": [],
        "stt_baseline": [stt_row(True, 10), stt_row(False, 100)],
        "stt_contender": [stt_row(True, 11), stt_row(False, 100)],
    }
    summary = summarize(report)
    assert summary["cases"]["sentence"]["sample_count"] == 1
    assert summary["stt"]["wall_time_degradation_ratio"] == pytest.approx(0.1)
    assert summary["stt"]["stt_contender"]["completed_runs"] == 1


@pytest.mark.asyncio
async def test_paced_response_measures_valid_audio_and_separate_compute_time() -> None:
    class Provider:
        async def synthesize(self, text: str):
            yield AudioFrame(struct.pack("<h", 100) * 960, 16000, 0, 0)

    report = await response(Provider(), "Hello. Goodbye.")
    assert report["audio_seconds"] == 0.12
    assert len(report["pcm"]) == 3840
    assert len(report["chunks"]) == 2
    assert report["paced_response_wall_seconds"] >= 0.12
    assert report["synthesis_compute_seconds"] < report["paced_response_wall_seconds"]


@pytest.mark.asyncio
async def test_cancellation_distinguishes_consumer_stop_from_native_cleanup() -> None:
    import asyncio

    class Provider:
        async def synthesize(self, text: str):
            yield AudioFrame(b"\0" * 1920, 16000, 0, 0)
            await asyncio.sleep(60)

        async def aclose(self):
            await asyncio.sleep(0.01)

    report = await cancellation(Provider(), "playback")
    assert report["frames_after_cancel"] == 0
    assert report["native_cleanup_drain_seconds"] >= 0.01


@pytest.mark.asyncio
async def test_real_runtime_starts_next_synthesis_before_previous_audio_finishes() -> None:
    class Provider:
        async def synthesize(self, text: str):
            count = 20 if text == "Hello." else 1
            for sequence in range(count):
                yield AudioFrame(struct.pack("<h", 100) * 960, 16000, sequence, 0)

    report = await buffered_response(Provider(), "Hello. Goodbye.")
    first, second = report["chunks"]
    assert second["start_seconds"] < first["playback_end_seconds"]
    assert second["playback_first_seconds"] >= first["playback_end_seconds"] - 0.005
    assert report["audio_seconds"] == 1.26
    assert len(report["pcm"]) == 21 * 1920
    assert report["max_chunk_starvation_seconds"] < 0.1
