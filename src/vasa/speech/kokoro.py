"""Opt-in, pinned Kokoro INT8; cancellation detaches native cleanup from playback."""

import asyncio
import concurrent.futures
import hashlib
import importlib
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Collection
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
    text_chunks(text)  # Validate before splitting, including pathological inputs.
    chunks: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        sentence_start = len(chunks)
        clauses = re.split(r"(?<=[;,])\s+", sentence) if len(sentence) > 120 else [sentence]
        meaningful_clauses: list[str] = []
        prefix = ""
        for clause in clauses:
            prefix = (prefix + " " + clause).strip()
            if len(prefix.split()) >= 5:
                meaningful_clauses.append(prefix)
                prefix = ""
        if prefix:
            if meaningful_clauses:
                meaningful_clauses[-1] += " " + prefix
            else:
                meaningful_clauses.append(prefix)
        for clause in meaningful_clauses:
            words = re.findall(r"\S+", clause)
            current = ""
            for word in words:
                for offset in range(0, len(word), 120):
                    part = word[offset : offset + 120]
                    if current and len(current) + len(part) + 1 > 120:
                        chunks.append(current)
                        current = ""
                    current = (current + " " + part).strip()
            if current:
                if (
                    len(current.split()) < 5
                    and len(chunks) > sentence_start
                    and len(chunks[-1]) + len(current) + 1 <= 120
                ):
                    chunks[-1] += " " + current
                else:
                    chunks.append(current)
    return chunks


GENERIC_CACHE_PHRASES = frozenset({"Certainly, I can help.", "One moment, please.", "Thank you."})


class KokoroInt8TTS:
    def __init__(
        self,
        model_dir: Path,
        *,
        num_threads: int = 1,
        max_streams: int = 10,
        queue_frames: int = 8,
        cache_bytes: int = 2 * 1024 * 1024,
        cache_phrases: Collection[str] | None = None,
    ) -> None:
        for limit, maximum in ((num_threads, 8), (max_streams, 10)):
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
                raise ValueError("Invalid CPU speech worker limits")
        if (
            isinstance(queue_frames, bool)
            or not isinstance(queue_frames, int)
            or not 1 <= queue_frames <= 64
        ):
            raise ValueError("Invalid output queue limit")
        if (
            isinstance(cache_bytes, bool)
            or not isinstance(cache_bytes, int)
            or not 0 <= cache_bytes <= 8 * 1024 * 1024
        ):
            raise ValueError("Invalid cache byte limit")
        phrases = GENERIC_CACHE_PHRASES if cache_phrases is None else frozenset(cache_phrases)
        if not phrases <= GENERIC_CACHE_PHRASES:
            raise ValueError("Only server-owned generic acknowledgement phrases may be cached")
        self._queue_frames = queue_frames
        self._cache_limit = cache_bytes
        self._cache_phrases = phrases
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_size = 0
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

    def _pcm(self, samples: NDArray[np.float32], rate: int) -> bytes:
        samples = np.asarray(samples, dtype=np.float32)
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

    def _generate(self, text: str, stop: threading.Event, emit: Callable[[bytes], bool]) -> bytes:
        carry = bytearray()
        retained = bytearray()
        callback_seen = False
        retain = text in self._cache_phrases and self._cache_limit > 0

        def consume(pcm: bytes) -> bool:
            nonlocal retain
            if retain:
                if len(retained) + len(pcm) <= self._cache_limit:
                    retained.extend(pcm)
                else:
                    retained.clear()
                    retain = False
            carry.extend(pcm)
            while len(carry) >= 1920:
                frame = bytes(carry[:1920])
                del carry[:1920]
                if not emit(frame):
                    return False
            return not stop.is_set()

        def callback(samples: NDArray[np.float32], _: float) -> int:
            nonlocal callback_seen
            callback_seen = True
            if stop.is_set():
                return 0
            # Sherpa 1.13.8 Kokoro invokes this after a complete acoustic
            # segment. Queue it immediately; the returned waveform duplicates it.
            return int(consume(self._pcm(samples, int(getattr(self._model, "sample_rate", 24000)))))

        if stop.is_set():
            return b""
        audio = self._model.generate(text, sid=0, speed=1.0, callback=callback)
        if stop.is_set():
            return b""
        if not callback_seen:
            consume(self._pcm(audio.samples, int(audio.sample_rate)))
        if carry and not stop.is_set():
            emit(bytes(carry).ljust(1920, b"\0"))
        return bytes(retained) if retain and not stop.is_set() else b""

    async def _owned_generate(
        self, text: str, stop: threading.Event, queue: asyncio.Queue[bytes]
    ) -> bytes:
        loop = asyncio.get_running_loop()

        def emit(frame: bytes) -> bool:
            if stop.is_set():
                return False
            future = asyncio.run_coroutine_threadsafe(queue.put(frame), loop)
            while True:
                try:
                    future.result(timeout=0.05)
                    return not stop.is_set()
                except concurrent.futures.TimeoutError:
                    if stop.is_set():
                        future.cancel()
                        return False

        try:
            result = await self._worker.run(
                lambda: self._generate(text, stop, emit), on_cancel=stop.set
            )
            if result and not stop.is_set() and not self._closed:
                previous = self._cache.pop(text, b"")
                self._cache_size -= len(previous)
                while self._cache and (
                    self._cache_size + len(result) > self._cache_limit or len(self._cache) >= 32
                ):
                    _, old = self._cache.popitem(last=False)
                    self._cache_size -= len(old)
                self._cache[text] = result
                self._cache_size += len(result)
            return result
        finally:
            self._slot.release()
            self._stops.discard(stop)

    def _finished(self, task: asyncio.Task[bytes]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        chunks = kokoro_chunks(text)
        if self._closed:
            raise RuntimeError("Speech provider is closed")
        sequence = 0
        async with self._streams:
            for chunk in chunks:
                cached = self._cache.get(chunk)
                if cached is not None:
                    self._cache.move_to_end(chunk)
                    for offset in range(0, len(cached), 1920):
                        await asyncio.sleep(0)
                        if self._closed:
                            raise RuntimeError("Speech provider is closed")
                        yield AudioFrame(
                            cached[offset : offset + 1920].ljust(1920, b"\0"),
                            16000,
                            sequence,
                            time.monotonic_ns(),
                        )
                        sequence += 1
                    continue
                await self._slot.acquire()
                if self._closed:
                    self._slot.release()
                    raise RuntimeError("Speech provider is closed")
                stop = threading.Event()
                queue: asyncio.Queue[bytes] = asyncio.Queue(self._queue_frames)
                self._stops.add(stop)
                task = asyncio.create_task(self._owned_generate(chunk, stop, queue))
                self._pending.add(task)
                task.add_done_callback(self._finished)
                getter: asyncio.Task[bytes] | None = None
                try:
                    while not task.done() or not queue.empty():
                        if queue.empty():
                            getter = asyncio.create_task(queue.get())
                            done, _ = await asyncio.wait(
                                {getter, task}, return_when=asyncio.FIRST_COMPLETED
                            )
                            if getter not in done:
                                getter.cancel()
                                await asyncio.gather(getter, return_exceptions=True)
                                getter = None
                                continue
                            pcm = getter.result()
                            getter = None
                        else:
                            pcm = queue.get_nowait()
                        if self._closed:
                            raise RuntimeError("Speech provider is closed")
                        yield AudioFrame(pcm, 16000, sequence, time.monotonic_ns())
                        sequence += 1
                    await asyncio.shield(task)
                finally:
                    # Async-generator close and barge-in both stop blocked queue
                    # producers immediately. Native task retains its slot until done.
                    stop.set()
                    if getter is not None:
                        getter.cancel()
                        await asyncio.gather(getter, return_exceptions=True)

    async def warmup(self) -> None:
        """Precompute only server-owned acknowledgements, through normal admission."""
        for phrase in sorted(self._cache_phrases):
            async for _ in self.synthesize(phrase):
                pass

    async def _close(self) -> None:
        for stop in self._stops:
            stop.set()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        await self._worker.aclose()
        self._model = None
        self._cache.clear()
        self._cache_size = 0

    async def aclose(self) -> None:
        self._closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)
