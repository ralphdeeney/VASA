"""Pinned CPU speech assets and bounded native work ownership."""

import asyncio
import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

ASR_COMMIT = "d42f2d9f7ca24806fb667456a18a9f1b60f70d16"
ASR_BASE = (
    "https://huggingface.co/csukuangfj/"
    "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/resolve/" + ASR_COMMIT + "/"
)
ASR_FILES = {
    "encoder-epoch-99-avg-1.int8.onnx": (
        "3810755ce7c3ab26b42a8bcf39d191308fa27fb0f53358823ba46141d03b7eb3"
    ),
    "decoder-epoch-99-avg-1.onnx": (
        "45a7f940ecfb53d89fa270ad11b88b961e53a317203eb24b1c8e95ed208b0f30"
    ),
    "joiner-epoch-99-avg-1.int8.onnx": (
        "e085d73b593cf9b0707f370dbd656d58327d3fe36d80d849202ef81df02cb01e"
    ),
    "tokens.txt": "49e3c2646595fd907228b3c6787069658f67b17377c60aeb8619c4551b2316fb",
    "README.md": "505f6b0e8a39f066a0794c4fb0b5689533d3bcd9d1dc5e5f47ccffeef1af9877",
}
FIXTURE_FILES = {
    "0.wav": "6bc58a4efdf20daac252b6b1502632601a71efe0308f6757dc1eda34891a7e4f",
    "1.wav": "5143a6ba93c4b274e2c4ac22deb75c2c48936c853f0519add1de828b6c79cc5a",
    "8k.wav": "f6f3c8b33e2534cdc154fe773ad2750f1f6a2ca5096179cdf037ae782456613e",
    "trans.txt": "b9ac44e7b794abb1a2d5faf0005e98a665971e7ac2ed15435832cc34edaa9100",
}
TTS_ARCHIVE_ROOT = "vits-piper-en_US-ljspeech-medium-int8"
TTS_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    + TTS_ARCHIVE_ROOT
    + ".tar.bz2"
)
TTS_ARCHIVE_SHA256 = "24dc3bd77dd48c291e52c297878d3437c9492f245d823d7f6a06c4bbb67f4b6b"
TTS_FILES = {
    "en_US-ljspeech-medium.onnx": (
        "206a8403baad4df7642156918a6ebe205798290d82f24d0d0119d7afa8a2738e"
    ),
    "tokens.txt": "ef3a7e4a8d1af0c9d4dc45aaae1a6242ebe24a7ed6f3d025a49eb29682784c6d",
    "MODEL_CARD": "fbee1529c89d36b3fe76d7e9f3f832dce17f44900a52d76a9bda735654766b4d",
}
ESPEAK_TREE_SHA256 = "e9c56f8c7cc79f16b1a2dc482074ed777e5b881da2a215a6f99630284dc4b3b8"
T = TypeVar("T")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_files(directory: Path, expected: dict[str, str]) -> None:
    for name, digest in expected.items():
        path = directory / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            raise RuntimeError("Speech model missing or invalid; run scripts/prepare_speech.py")


def verify_tts(directory: Path) -> None:
    verify_files(directory, TTS_FILES)
    resources = directory / "espeak-ng-data"
    if not resources.is_dir() or resources.is_symlink():
        raise RuntimeError("Speech phonemizer data missing; run scripts/prepare_speech.py")
    digest = hashlib.sha256()
    for path in sorted(resources.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Speech phonemizer data invalid")
        if path.is_file():
            digest.update(path.relative_to(resources).as_posix().encode() + b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    if digest.hexdigest() != ESPEAK_TREE_SHA256:
        raise RuntimeError("Speech phonemizer data invalid; run scripts/prepare_speech.py")


@dataclass(frozen=True, slots=True)
class SpeechModels:
    root: Path

    @property
    def stt_dir(self) -> Path:
        return self.root / "asr"

    @property
    def tts_dir(self) -> Path:
        return self.root / "tts"

    @property
    def fixture_dir(self) -> Path:
        return self.root / "fixtures"

    def verify(self) -> None:
        verify_files(self.stt_dir, ASR_FILES)
        verify_tts(self.tts_dir)
        verify_files(self.fixture_dir, FIXTURE_FILES)


class NativeWorker:
    """One native worker; admission is bounded by the owning provider semaphore."""

    def __init__(self, name: str) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._closed = False

    async def run(
        self, function: Callable[[], T], on_cancel: Callable[[], None] | None = None
    ) -> T:
        if self._closed:
            raise RuntimeError("Speech provider is closed")
        future = asyncio.get_running_loop().run_in_executor(self._executor, function)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if on_cancel is not None:
                on_cancel()
            # Native inference cannot be forcefully killed. Retain the slot and
            # all native stream references until it stops, even on repeat cancellation.
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if future.done() and not future.cancelled():
                future.exception()  # consume any native failure during cancellation
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
