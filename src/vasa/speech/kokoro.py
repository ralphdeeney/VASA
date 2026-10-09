"""Opt-in, pinned Kokoro INT8; cancellation detaches native cleanup from playback."""

import asyncio
import hashlib
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
from vasa.speech.models import ESPEAK_TREE_SHA256, NativeWorker, sha256_file, verify_files
from vasa.speech.synthesis import text_chunks

KOKORO_INT8_FILES = {
    "model.int8.onnx": "bda15858163726a492d02a9a727bc263551b86ac77f90812c4b30ff41d380e26",
    "voices.bin": "e64a5a581d8c2a350d848f51c3121657cd83aa07ed6109172177345874a7244c",
    "tokens.txt": "931ab2df2400cd65d580a22402024c2347ced8ae9ea300e545144b1aacc48e14",
    "lexicon-us-en.txt": "7daaab53a181be9885b853a8582bf1838186317e5dadacbcef9c426d6fa0da14",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}


def verify_kokoro_int8(directory: Path) -> None:
    if directory.is_symlink() or any(parent.is_symlink() for parent in directory.parents):
        raise RuntimeError("Kokoro model directory must not use symlinks")
    try:
        verify_files(directory, KOKORO_INT8_FILES)
    except RuntimeError:
        raise RuntimeError(
            "Kokoro model missing or invalid; run scripts/prepare_kokoro_int8.py"
        ) from None
    resources = directory / "espeak-ng-data"
    if not resources.is_dir() or resources.is_symlink():
        raise RuntimeError("Kokoro phonemizer data missing or invalid")
    digest = hashlib.sha256()
    for path in sorted(resources.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Kokoro phonemizer data invalid")
        if path.is_file():
            digest.update(path.relative_to(resources).as_posix().encode() + b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    if digest.hexdigest() != ESPEAK_TREE_SHA256:
        raise RuntimeError("Kokoro phonemizer data invalid")


def kokoro_chunks(text: str) -> list[str]:
    # Keep short utterances intact: tiny fragments hurt Kokoro prosody and can
    # make first-audio numbers misleading. Clauses help only on long sentences.
    text_chunks(text)
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if len(sentence) <= 160:
            chunks.extend(chunk for chunk in text_chunks(sentence) if chunk)
            continue
        clauses = re.split(r"(?<=[;,])\s+", sentence)
        current = ""
        meaningful: list[str] = []
        for clause in clauses:
            current = (current + " " + clause).strip()
            if len(current.split()) >= 5:
                meaningful.append(current)
                current = ""
        if current:
            if meaningful:
                meaningful[-1] += " " + current
            else:
                meaningful.append(current)
        for clause in meaningful:
            chunks.extend(chunk for chunk in text_chunks(clause) if chunk)
    return chunks


class KokoroInt8TTS:
    def __init__(self, model_dir: Path, *, num_threads: int = 1, max_streams: int = 10) -> None:
        for limit, maximum in ((num_threads, 8), (max_streams, 10)):
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
                raise ValueError("Invalid CPU speech worker limits")
        started = time.monotonic()
        verify_kokoro_int8(model_dir)
        native = importlib.import_module("sherpa_onnx")
        kokoro = native.OfflineTtsKokoroModelConfig(
            model=str(model_dir / "model.int8.onnx"),
            voices=str(model_dir / "voices.bin"),
            tokens=str(model_dir / "tokens.txt"),
            data_dir=str(model_dir / "espeak-ng-data"),
            lexicon=str(model_dir / "lexicon-us-en.txt"),
            lang="en-us",
        )
        self._model = native.OfflineTts(
            native.OfflineTtsConfig(
                model=native.OfflineTtsModelConfig(
                    kokoro=kokoro, num_threads=num_threads, provider="cpu"
                ),
                max_num_sentences=1,
            )
        )
        self._resample = importlib.import_module("scipy.signal").resample_poly
        self.load_seconds = time.monotonic() - started
        self._worker = NativeWorker("vasa-kokoro-int8")
        self._streams = asyncio.Semaphore(max_streams)
        self._slot = asyncio.Semaphore(1)
        self._pending: set[asyncio.Task[bytes]] = set()
        self._stops: set[threading.Event] = set()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    def _generate(self, text: str, stop: threading.Event) -> bytes:
        if stop.is_set():
            return b""

        def callback(_: NDArray[np.float32], __: float) -> int:
            return int(not stop.is_set())

        audio = self._model.generate(text, sid=0, speed=1.0, callback=callback)
        # Kokoro calls back after full segment synthesis. Never retain canceled PCM.
        if stop.is_set():
            return b""
        samples = np.asarray(audio.samples, dtype=np.float32)
        rate = int(audio.sample_rate)
        if (
            samples.ndim != 1
            or rate not in {16000, 22050, 24000, 44100, 48000}
            or not 0 < len(samples) <= rate * 30
            or not np.isfinite(samples).all()
        ):
            raise RuntimeError("Invalid native Kokoro output")
        if rate != 16000:
            divisor = math.gcd(rate, 16000)
            samples = np.asarray(
                self._resample(samples, 16000 // divisor, rate // divisor), dtype=np.float32
            )
        return bytes(np.clip(samples * 32768, -32768, 32767).astype("<i2").tobytes())

    async def _owned_generate(self, text: str, stop: threading.Event) -> bytes:
        try:
            return await self._worker.run(lambda: self._generate(text, stop), on_cancel=stop.set)
        finally:
            self._slot.release()
            self._stops.discard(stop)

    def _finished(self, task: asyncio.Task[bytes]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()  # Detached cancellation must not leak native exceptions.

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        chunks = kokoro_chunks(text)
        if self._closed:
            raise RuntimeError("Speech provider is closed")
        sequence = 0
        async with self._streams:
            for chunk in chunks:
                await self._slot.acquire()
                if self._closed:
                    self._slot.release()
                    raise RuntimeError("Speech provider is closed")
                stop = threading.Event()
                self._stops.add(stop)
                task = asyncio.create_task(self._owned_generate(chunk, stop))
                self._pending.add(task)
                task.add_done_callback(self._finished)
                try:
                    pcm = await asyncio.shield(task)
                except asyncio.CancelledError:
                    stop.set()
                    # The consumer exits now; one tracked native task owns admission
                    # until the non-preemptible segment finishes. No executor backlog.
                    raise
                for offset in range(0, len(pcm), 1920):
                    await asyncio.sleep(0)
                    if self._closed:
                        raise RuntimeError("Speech provider is closed")
                    yield AudioFrame(
                        pcm[offset : offset + 1920].ljust(1920, b"\0"),
                        16000,
                        sequence,
                        time.monotonic_ns(),
                    )
                    sequence += 1

    async def _close(self) -> None:
        for stop in self._stops:
            stop.set()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        await self._worker.aclose()
        self._model = None

    async def aclose(self) -> None:
        self._closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)
