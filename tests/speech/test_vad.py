"""Injected classifiers verify segmentation only; native checks use silence and real speech."""

import hashlib
import os
import wave
from collections import deque
from pathlib import Path

import pytest

from vasa.contracts.models import AudioFrame
from vasa.speech.vad import StreamingVAD, VadConfig

FIXTURE_SHA256 = "6bc58a4efdf20daac252b6b1502632601a71efe0308f6757dc1eda34891a7e4f"


def audio_frame(sequence: int, *, pcm: bytes = b"\0" * 1920) -> AudioFrame:
    return AudioFrame(
        pcm=pcm, sample_rate=16000, sequence=sequence, timestamp_ns=sequence * 60000000
    )


class ClassifiedWindows:
    """Deterministic component evidence, never a substitute for native speech detection."""

    def __init__(self, decisions: list[bool]) -> None:
        self.decisions = deque(decisions)
        self.windows: list[bytes] = []

    def __call__(self, pcm: bytes, sample_rate: int) -> bool:
        assert sample_rate == 16000 and len(pcm) == 960
        self.windows.append(pcm)
        return self.decisions.popleft()


def test_native_silence_never_starts_or_finishes_an_utterance() -> None:
    vad = StreamingVAD()
    for index in range(1000):
        observation = vad.process(audio_frame(index))
        assert not observation.speech and not observation.started and not observation.ended
        assert observation.segment is None
    assert vad.finish() is None


def test_component_splits_verified_frame_into_two_distinct_supported_30ms_windows() -> None:
    classifier = ClassifiedWindows([True, True])
    pcm = b"\x01\0" * 480 + b"\x02\0" * 480
    vad = StreamingVAD(classify=classifier)
    assert vad.process(audio_frame(0, pcm=pcm)).started
    assert classifier.windows == [pcm[:960], pcm[960:]]


def test_one_voiced_window_is_insufficient_and_silence_resets_start_evidence() -> None:
    classifier = ClassifiedWindows([True, False, False, False, False, True, False, False])
    vad = StreamingVAD(classify=classifier)
    for index in range(4):
        observation = vad.process(audio_frame(index))
        assert not observation.started and observation.segment is None
    assert vad.finish() is None


def test_cross_frame_voice_evidence_is_retained_even_without_preroll() -> None:
    classifier = ClassifiedWindows([False, True, True, False])
    vad = StreamingVAD(VadConfig(preroll_ms=0), classify=classifier)
    assert not vad.process(audio_frame(0)).started
    assert vad.process(audio_frame(1)).started
    segment = vad.finish()
    assert segment is not None
    assert [frame.sequence for frame in segment] == [0, 1]


def test_endpoint_includes_bounded_preroll_and_exact_trailing_silent_frames() -> None:
    classifier = ClassifiedWindows([False] * 20 + [True, True] + [False] * 10)
    vad = StreamingVAD(classify=classifier)
    for index in range(10):
        assert not vad.process(audio_frame(index)).started
    started = vad.process(audio_frame(10))
    assert started.started and started.speech and not started.ended
    for index in range(11, 15):
        assert not vad.process(audio_frame(index)).ended
    ended = vad.process(audio_frame(15))
    assert ended.ended and not ended.started and not ended.speech
    assert ended.segment is not None
    assert [frame.sequence for frame in ended.segment] == list(range(8, 16))
    assert vad.finish() is None


def test_speech_after_short_pause_resets_endpoint_timer() -> None:
    classifier = ClassifiedWindows([True] * 2 + [False] * 8 + [True] * 2 + [False] * 10)
    vad = StreamingVAD(classify=classifier)
    observations = [vad.process(audio_frame(index)) for index in range(11)]
    assert observations[0].started
    assert not any(observation.ended for observation in observations[:-1])
    assert observations[-1].ended
    assert observations[-1].segment is not None
    assert len(observations[-1].segment) == 11


def test_continuous_voice_forces_endpoint_within_20_seconds_without_buffer_growth() -> None:
    vad = StreamingVAD(classify=lambda pcm, rate: True)
    for index in range(332):
        assert not vad.process(audio_frame(index)).ended
    observation = vad.process(audio_frame(332))
    assert observation.ended and observation.segment is not None
    assert len(observation.segment) == 333
    assert len(observation.segment) * 0.06 <= 20
    # A new input frame supplies new evidence; the finished segment cannot mix with it.
    assert vad.process(audio_frame(333)).started
    next_segment = vad.finish()
    assert next_segment is not None and [frame.sequence for frame in next_segment] == [333]


def test_short_bound_can_start_and_finish_same_frame_without_retaining_extra_preroll() -> None:
    classifier = ClassifiedWindows([False] * 4 + [True] * 2)
    vad = StreamingVAD(VadConfig(max_utterance_seconds=0.06), classify=classifier)
    assert not vad.process(audio_frame(0)).started
    assert not vad.process(audio_frame(1)).started
    observation = vad.process(audio_frame(2))
    assert observation.started and observation.ended and observation.speech
    assert observation.segment is not None
    assert [frame.sequence for frame in observation.segment] == [2]
    assert vad.finish() is None


def test_endpoint_reset_requires_new_evidence_and_owns_finished_segment_list() -> None:
    classifier = ClassifiedWindows([True] * 2 + [False] * 14 + [True] * 2)
    vad = StreamingVAD(classify=classifier)
    previous = None
    for index in range(6):
        observation = vad.process(audio_frame(index))
        if observation.ended:
            previous = observation.segment
    assert previous is not None
    previous.clear()
    for index in range(6, 8):
        observation = vad.process(audio_frame(index))
        assert not observation.started and not observation.ended
    assert vad.process(audio_frame(8)).started
    current = vad.finish()
    assert current is not None and [frame.sequence for frame in current] == [6, 7, 8]
    assert vad.finish() is None


def test_separate_calls_do_not_share_utterance_or_candidate_audio() -> None:
    speaking_call = StreamingVAD(classify=lambda pcm, rate: True)
    silent_call = StreamingVAD(classify=lambda pcm, rate: False)
    assert speaking_call.process(audio_frame(100)).started
    assert not silent_call.process(audio_frame(200)).started
    assert silent_call.finish() is None
    segment = speaking_call.finish()
    assert segment is not None and [frame.sequence for frame in segment] == [100]


@pytest.mark.parametrize(
    "configuration",
    [
        {"aggressiveness": 4},
        {"aggressiveness": True},
        {"start_ms": 45},
        {"end_silence_ms": 0},
        {"end_silence_ms": 90},
        {"preroll_ms": -60},
        {"max_utterance_seconds": float("inf")},
        {"max_utterance_seconds": 21},
        {"max_utterance_seconds": 0.01},
        {"start_ms": 120, "max_utterance_seconds": 0.06},
    ],
)
def test_invalid_or_unbounded_configurations_are_rejected(configuration: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        VadConfig(**configuration)


@pytest.mark.parametrize(
    "frame",
    [
        AudioFrame(pcm=b"\0" * 1920, sample_rate=8000, sequence=0, timestamp_ns=0),
        AudioFrame(pcm=b"\0" * 960, sample_rate=16000, sequence=0, timestamp_ns=0),
    ],
)
def test_wrong_media_format_is_rejected_before_classification(frame: AudioFrame) -> None:
    classifier = ClassifiedWindows([])
    vad = StreamingVAD(classify=classifier)
    with pytest.raises(ValueError, match="16 kHz"):
        vad.process(frame)
    assert classifier.windows == []
    assert vad.finish() is None


def test_native_vad_detects_pinned_real_speech_and_endpoints_after_silence() -> None:
    path = Path(os.environ.get("VASA_SPEECH_FIXTURE", ".local/speech/fixtures/0.wav"))
    if not path.is_file():
        pytest.fail(
            "Pinned real speech fixture is missing; run the speech-model preparation script. "
            "VASA_SPEECH_FIXTURE can identify the verified 16 kHz fixture.",
            pytrace=False,
        )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256
    with wave.open(str(path), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        pcm = audio.readframes(audio.getnframes())
    pcm += b"\0" * (-len(pcm) % 1920)
    vad = StreamingVAD()
    starts = 0
    segments = []
    chunks = [pcm[offset : offset + 1920] for offset in range(0, len(pcm), 1920)]
    chunks.extend([b"\0" * 1920] * 30)
    for sequence, chunk in enumerate(chunks):
        observation = vad.process(audio_frame(sequence, pcm=chunk))
        starts += int(observation.started)
        if observation.segment is not None:
            segments.append(observation.segment)
    assert starts >= 1 and len(segments) >= 1
    assert any(frame.pcm != b"\0" * 1920 for segment in segments for frame in segment)
    assert all(len(segment) * 0.06 <= 20 for segment in segments)
    assert vad.finish() is None, "appended real silence must end every detected utterance"
