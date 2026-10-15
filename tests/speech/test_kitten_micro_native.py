from pathlib import Path

import numpy as np
import pytest

from vasa.speech import KittenMicroTTS


@pytest.mark.speech_native
async def test_real_micro_reuses_model_and_emits_vasa_audio_without_speech_cache() -> None:
    provider = KittenMicroTTS(Path(".local/speech/kitten-micro"))
    model = provider._model
    try:
        for text in (
            "Your appointment is confirmed for tomorrow morning at ten o'clock.",
            "Thank you. Please contact our team if your plans change.",
        ):
            frames = [frame async for frame in provider.synthesize(text)]
            assert frames and provider._model is model
            assert [frame.sequence for frame in frames] == list(range(len(frames)))
            assert all(
                frame.sample_rate == 16000 and frame.channels == 1 and len(frame.pcm) == 1920
                for frame in frames
            )
            samples = np.frombuffer(b"".join(frame.pcm for frame in frames), dtype="<i2")
            assert np.max(np.abs(samples.astype(np.int32))) > 1000
            assert not provider._cache
    finally:
        await provider.aclose()
    assert provider._model is None and not provider._pending
