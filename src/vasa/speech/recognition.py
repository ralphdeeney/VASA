import asyncio
import importlib
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from vasa.contracts.models import AudioFrame
from vasa.speech.models import ASR_FILES, NativeWorker, verify_files


class SherpaSTT:
    def __init__(self, model_dir: Path, *, num_threads: int = 2, max_streams: int = 10) -> None:
        if not 1 <= num_threads <= 8 or not 1 <= max_streams <= 10:
            raise ValueError("Invalid CPU speech worker limits")
        verify_files(model_dir, ASR_FILES)
        native = importlib.import_module("sherpa_onnx")
        self._recognizer = native.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(model_dir / "joiner-epoch-99-avg-1.int8.onnx"),
            num_threads=num_threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=False,
            model_type="zipformer",
            provider="cpu",
        )
        self._worker = NativeWorker("vasa-stt")
        self._slots = asyncio.Semaphore(max_streams)
        self._closed = False

    async def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]:
        if self._closed:
            raise RuntimeError("Speech provider is closed")
        async with self._slots:
            if self._closed:
                raise RuntimeError("Speech provider is closed")
            stream = self._recognizer.create_stream()
            # This streaming encoder needs initial acoustic context; zero-padding
            # warms a new utterance without delaying capture or fabricating speech.
            await self._worker.run(
                lambda: stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
            )
            samples_seen = 0
            last = ""

            def decode() -> str:
                while self._recognizer.is_ready(stream):
                    self._recognizer.decode_stream(stream)
                return str(self._recognizer.get_result(stream)).strip()

            async for frame in frames:
                if frame.sample_rate != 16000 or frame.channels != 1:
                    raise ValueError("STT requires 16000 Hz mono PCM16")
                samples_seen += len(frame.pcm) // 2
                if samples_seen > 30 * 16000:
                    raise ValueError("STT utterance exceeds 30 seconds")
                samples = np.frombuffer(frame.pcm, dtype="<i2").astype(np.float32) * np.float32(
                    1 / 32768
                )

                def accept(audio: NDArray[np.float32] = samples) -> str:
                    stream.accept_waveform(16000, audio)
                    return decode()

                text = await self._worker.run(accept)
                if text and text != last:
                    last = text
                    yield text
            if samples_seen:

                def finish() -> str:
                    # Online encoders need a finite tail to flush their final context.
                    stream.accept_waveform(16000, np.zeros(4800, dtype=np.float32))
                    stream.input_finished()
                    return decode()

                final = await self._worker.run(finish)
                if final:
                    yield final  # explicit final cumulative text, even if unchanged

    async def aclose(self) -> None:
        self._closed = True
        await self._worker.aclose()
        self._recognizer = None
