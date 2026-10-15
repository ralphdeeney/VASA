import struct

import numpy as np
import pytest

from scripts.evaluate_tts_streaming import EvaluationTTS, measure, pcm16, playback_pcm


def test_playback_render_preserves_audio_and_only_adds_measured_underrun() -> None:
    first = struct.pack("<h", 1000) * 1600
    second = struct.pack("<h", -2000) * 1600
    events = [
        {"ready_seconds": 0.4, "audio_seconds": 0.1, "pcm": first},
        {"ready_seconds": 0.7, "audio_seconds": 0.1, "pcm": second},
    ]
    assert playback_pcm(events) == first + b"\0\0" * 3200 + second
    events[1]["ready_seconds"] = 0.45
    assert playback_pcm(events) == first + second


def test_contract_conversion_checks_native_samples_and_resamples_duration() -> None:
    converted = pcm16(np.ones(2400, dtype=np.float32) * 0.1, 24000)
    assert len(converted) == 3200
    for samples in (np.array([np.nan]), np.array([]), np.ones((2, 3))):
        with pytest.raises(ValueError, match="invalid native waveform"):
            pcm16(samples, 24000)


@pytest.mark.asyncio
async def test_provider_streams_each_sentence_as_ordered_contract_frames() -> None:
    class Stub(EvaluationTTS):
        def __init__(self) -> None:
            self.policy = "sentence"
            self.texts: list[str] = []

        def generate(self, text: str) -> bytes:
            self.texts.append(text)
            return struct.pack("<h", 100) * 1600

    provider = Stub()
    report = await measure(provider, "Hello. How can I help?", "sentence")
    assert provider.texts == ["Hello.", "How can I help?"]
    assert len(report["chunks"]) == 2
    assert len(report["pcm"]) == 7680
    assert report["first_playable_seconds"] <= report["complete_seconds"]
