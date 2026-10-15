"""Capacity measurement guards; native evidence is produced by the executable harness."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from scripts.benchmark_capacity import POLICY, run_call, validate_frame
from vasa.contracts.models import AudioFrame


class ScriptedSTT:
    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        async for frame in frames:
            validate_frame(frame)
        yield "fixture accepted"

    async def aclose(self) -> None:
        pass


class ScriptedTTS:
    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        yield AudioFrame(bytes(1920), 16000, 0, 0)

    async def aclose(self) -> None:
        pass


async def test_measurement_preserves_pacing_and_separates_finalization() -> None:
    sample = await run_call(ScriptedSTT(), ScriptedTTS(), bytes(3840), frame_seconds=0.001)
    assert sample["inbound_frames"] == 12
    assert sample["outbound_frames"] == 1
    assert sample["stt_finalization_seconds"] >= 0.009
    assert (
        sample["synthetic_fixture_end_to_first_audio_seconds"] >= sample["stt_finalization_seconds"]
    )
    assert sample["vad_endpoints"] == 0
    assert sample["vad_final_endpoint_after_fixture_seconds"] is None


@pytest.mark.parametrize("size,rate", [(960, 16000), (1920, 8000)])
def test_invalid_native_frames_cannot_be_counted_successful(size: int, rate: int) -> None:
    with pytest.raises(RuntimeError, match="invalid PCM"):
        validate_frame(AudioFrame(bytes(size), rate, 0, 0))


async def test_canceled_measurement_releases_async_generators() -> None:
    task = asyncio.create_task(
        run_call(ScriptedSTT(), ScriptedTTS(), bytes(1920 * 100), frame_seconds=0.01)
    )
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_capacity_policy_declares_bounds_before_execution() -> None:
    assert POLICY["concurrency"] == 10
    assert POLICY["rounds"] >= 3
    assert POLICY["frame_seconds"] == 0.06
    assert POLICY["turn_deadline_seconds"] == 120
    assert POLICY["cancellation_deadline_seconds"] == 10
