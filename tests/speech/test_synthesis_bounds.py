"""Real native generation admission is independent of slow output consumption."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest

from vasa.contracts.models import AudioFrame
from vasa.speech import SherpaTTS


@pytest.mark.speech_native
async def test_stalled_playback_does_not_hold_native_slots_and_streams_stay_bounded() -> None:
    tts = SherpaTTS(Path(".local/speech/piper"), max_concurrency=2, max_streams=3)
    outputs = [
        cast(
            AsyncGenerator[AudioFrame, None],
            tts.synthesize("Hello. Your appointment is confirmed."),
        )
        for _ in range(4)
    ]
    pending: asyncio.Future[AudioFrame] | None = None
    try:
        # Three actual native utterances generate first audio even though the
        # previous generators remain paused at their first frame.
        for output in outputs[:3]:
            first = await asyncio.wait_for(anext(output), 10)
            assert len(first.pcm) == 1920 and first.sample_rate == 16000
        assert tts._streams.locked()
        assert not tts._slots.locked()
        pending = asyncio.ensure_future(anext(outputs[3]))
        await asyncio.sleep(0.05)
        assert not pending.done()  # Fourth PCM buffer cannot be admitted.
        pending.cancel()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await outputs[0].aclose()
        replacement = cast(AsyncGenerator[AudioFrame, None], tts.synthesize("Hello again."))
        try:
            assert len((await asyncio.wait_for(anext(replacement), 10)).pcm) == 1920
        finally:
            await replacement.aclose()
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        for output in outputs:
            await output.aclose()
        await tts.aclose()
    assert not tts._streams.locked()
    assert not tts._slots.locked()


@pytest.mark.parametrize("limit", [0, 11, True, 1.5])
def test_invalid_stream_limit_fails_before_model_access(limit: int) -> None:
    with pytest.raises(ValueError, match="worker limits"):
        SherpaTTS(Path("missing-model"), max_streams=limit)
