"""Per-call CPU-native VAD and bounded turn segmentation for verified 60 ms media."""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import webrtcvad  # type: ignore[import-untyped]

from vasa.contracts.models import AudioFrame

FRAME_MS = 60
WINDOW_MS = 30
WINDOW_BYTES = 960


@dataclass(frozen=True, slots=True)
class VadConfig:
    aggressiveness: int = 2
    start_ms: int = 60
    end_silence_ms: int = 300
    preroll_ms: int = 120
    max_utterance_seconds: float = 20.0

    def __post_init__(self) -> None:
        integers = (self.aggressiveness, self.start_ms, self.end_silence_ms, self.preroll_ms)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in integers):
            raise ValueError("VAD timing and aggressiveness must be integers")
        if not 0 <= self.aggressiveness <= 3:
            raise ValueError("VAD aggressiveness must be between zero and three")
        if not 30 <= self.start_ms <= 1000 or self.start_ms % WINDOW_MS:
            raise ValueError("VAD start evidence must use 30 ms units, up to one second")
        if not 60 <= self.end_silence_ms <= 5000 or self.end_silence_ms % FRAME_MS:
            raise ValueError("VAD endpoint silence must use 60 ms units, up to five seconds")
        if not 0 <= self.preroll_ms <= 1000 or self.preroll_ms % FRAME_MS:
            raise ValueError("VAD preroll must use 60 ms units, up to one second")
        if (
            isinstance(self.max_utterance_seconds, bool)
            or not math.isfinite(self.max_utterance_seconds)
            or not 0.06 <= self.max_utterance_seconds <= 20
        ):
            raise ValueError("VAD utterances must be bounded between 60 ms and 20 seconds")
        if math.floor(self.max_utterance_seconds * 1000 / FRAME_MS) * FRAME_MS < self.start_ms:
            raise ValueError("VAD start evidence exceeds the utterance bound")


@dataclass(frozen=True, slots=True)
class VadResult:
    started: bool = False
    ended: bool = False
    speech: bool = False
    segment: list[AudioFrame] | None = None


class StreamingVAD:
    """One instance per call. Finished segments own their lists; no shared audio history."""

    def __init__(
        self,
        config: VadConfig | None = None,
        *,
        classify: Callable[[bytes, int], bool] | None = None,
    ) -> None:
        self.config = config or VadConfig()
        self._injected_classifier = classify
        self._classify: Callable[[bytes, int], bool] = (
            classify
            if classify is not None
            else webrtcvad.Vad(self.config.aggressiveness).is_speech
        )
        self._preroll_frames = self.config.preroll_ms // FRAME_MS
        self._max_frames = math.floor(self.config.max_utterance_seconds * 1000 / FRAME_MS)
        candidate_frames = math.ceil(self.config.start_ms / FRAME_MS) + 1
        self._idle: deque[tuple[int, AudioFrame]] = deque(
            maxlen=self._preroll_frames + candidate_frames
        )
        self._segment: list[AudioFrame] | None = None
        self._frame_number = 0
        self._voiced_ms = 0
        self._candidate_start: int | None = None
        self._silence_ms = 0

    def _reset(self) -> None:
        self._idle.clear()
        self._segment = None
        self._voiced_ms = 0
        self._candidate_start = None
        self._silence_ms = 0
        self._frame_number = 0
        if self._injected_classifier is None:
            # Native hangover belongs to the completed turn, never the next turn.
            self._classify = webrtcvad.Vad(self.config.aggressiveness).is_speech

    def process(self, frame: AudioFrame) -> VadResult:
        if frame.sample_rate != 16000 or frame.channels != 1 or len(frame.pcm) != 1920:
            raise ValueError("VAD requires verified mono 16 kHz PCM16 60 ms frames")
        windows = (
            self._classify(frame.pcm[:WINDOW_BYTES], frame.sample_rate),
            self._classify(frame.pcm[WINDOW_BYTES:], frame.sample_rate),
        )
        speech = any(windows)
        started = False
        self._frame_number += 1
        if self._segment is not None:
            self._segment.append(frame)
        else:
            self._idle.append((self._frame_number, frame))
            for voiced in windows:
                if not voiced:
                    self._voiced_ms = 0
                    self._candidate_start = None
                    continue
                if self._voiced_ms == 0:
                    self._candidate_start = self._frame_number
                self._voiced_ms += WINDOW_MS
                if self._voiced_ms >= self.config.start_ms:
                    assert self._candidate_start is not None
                    oldest = self._candidate_start - self._preroll_frames
                    self._segment = [item for number, item in self._idle if number >= oldest]
                    self._idle.clear()
                    started = True
                    break
        if self._segment is None:
            return VadResult(speech=speech)
        self._silence_ms = 0 if speech else self._silence_ms + FRAME_MS
        if self._silence_ms >= self.config.end_silence_ms or len(self._segment) >= self._max_frames:
            # A tiny configured bound can exclude preceding preroll, while keeping the new voice.
            segment = self._segment[-self._max_frames :]
            self._reset()
            return VadResult(started=started, ended=True, speech=speech, segment=segment)
        return VadResult(started=started, speech=speech)

    def finish(self) -> list[AudioFrame] | None:
        """Drain started speech once on stream completion; incomplete evidence is discarded."""
        segment = list(self._segment) if self._segment is not None else None
        self._reset()
        return segment
