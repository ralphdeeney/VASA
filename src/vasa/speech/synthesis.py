import asyncio
import importlib
import math
import re
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from vasa.contracts.models import AudioFrame
from vasa.speech.models import NativeWorker, verify_tts


def text_chunks(text: str) -> list[str]:
    if not text.strip() or len(text) > 2000 or "\x00" in text:
        raise ValueError("TTS requires 1 to 2000 characters of text")
    words = re.findall(r"\S+", text)
    chunks: list[str] = []
    current = ""
    for word in words:
        # Split pathological single tokens too; generation units stay bounded.
        for offset in range(0, len(word), 240):
            part = word[offset : offset + 240]
            if len(current) + len(part) + 1 > 240:
                chunks.append(current)
                current = ""
            current = (current + " " + part).strip()
            if part.endswith((".", "!", "?")):
                chunks.append(current)
                current = ""
    if current:
        chunks.append(current)
    return chunks


class PiperTTS:
    def __init__(
        self,
        model_dir: Path,
        *,
        num_threads: int = 1,
        max_concurrency: int = 2,
        max_streams: int = 10,
    ) -> None:
        if (
            not 1 <= num_threads <= 8
            or not 1 <= max_concurrency <= 10
            or isinstance(max_streams, bool)
            or not isinstance(max_streams, int)
            or not 1 <= max_streams <= 10
        ):
            raise ValueError("Invalid CPU speech worker limits")
        verify_tts(model_dir)
        native = importlib.import_module("sherpa_onnx")
        vits = native.OfflineTtsVitsModelConfig(
            model=str(model_dir / "en_US-libritts_r-medium.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            data_dir=str(model_dir / "espeak-ng-data"),
            # Stable business-word articulation; random prosody made otherwise
            # identical phrases inconsistently intelligible in native roundtrips.
            noise_scale=0.0,
            noise_scale_w=0.0,
        )
        config = native.OfflineTtsConfig(
            model=native.OfflineTtsModelConfig(vits=vits, num_threads=num_threads, provider="cpu"),
            max_num_sentences=1,
        )
        self._model = native.OfflineTts(config)
        self._resample = importlib.import_module("scipy.signal").resample_poly
        self._worker = NativeWorker("vasa-tts")
        # Limit retained playback PCM to ten streams with chunks <=30 seconds.
        # Native admission ends when inference completes, independently of playback.
        self._streams = asyncio.Semaphore(max_streams)
        self._slots = asyncio.Semaphore(max_concurrency)
        self._closed = False

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        chunks = text_chunks(text)
        if self._closed:
            raise RuntimeError("Speech provider is closed")
        sequence = 0
        async with self._streams:
            if self._closed:
                raise RuntimeError("Speech provider is closed")
            for chunk in chunks:
                canceled = threading.Event()

                def generate(text_chunk: str = chunk, stop: threading.Event = canceled) -> bytes:
                    def callback(_: NDArray[np.float32], __: float) -> int:
                        # VITS C++ uses `should_continue = callback(...)`: 1 keeps
                        # generating, 0 stops. The pinned Python docstring reverses this.
                        return int(not stop.is_set())

                    audio = self._model.generate(text_chunk, sid=0, speed=1.0, callback=callback)
                    samples = np.asarray(audio.samples, dtype=np.float32)
                    rate = int(audio.sample_rate)
                    if (
                        samples.ndim != 1
                        or rate not in {16000, 22050, 24000, 44100, 48000}
                        or len(samples) > rate * 30
                        or not np.isfinite(samples).all()
                    ):
                        raise RuntimeError("Invalid native TTS output")
                    if rate != 16000:
                        factor = math.gcd(rate, 16000)
                        samples = np.asarray(
                            self._resample(samples, 16000 // factor, rate // factor),
                            dtype=np.float32,
                        )
                    return bytes(np.clip(samples * 32768, -32768, 32767).astype("<i2").tobytes())

                async with self._slots:
                    if self._closed:
                        raise RuntimeError("Speech provider is closed")
                    # NativeWorker retains this slot until inference has stopped,
                    # including repeated cancellation. Slow playback owns only
                    # its separate bounded stream/PCM-buffer admission.
                    pcm = await self._worker.run(generate, on_cancel=canceled.set)
                for offset in range(0, len(pcm), 1920):
                    yield AudioFrame(
                        pcm[offset : offset + 1920].ljust(1920, b"\0"),
                        16000,
                        sequence,
                        time.monotonic_ns(),
                    )
                    sequence += 1

    async def aclose(self) -> None:
        self._closed = True
        await self._worker.aclose()
        self._model = None


# Compatibility for existing native harness imports; this now synthesizes Piper.
SherpaTTS = PiperTTS
