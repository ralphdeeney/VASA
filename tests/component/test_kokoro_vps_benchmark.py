import struct
from pathlib import Path

import pytest

from scripts.benchmark_kokoro_int8_vps import (
    cancellation,
    response,
    segments,
    validate_scope,
    word_error_rate,
)
from vasa.contracts.models import AudioFrame


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
