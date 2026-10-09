"""Pinned Kitten Micro CPU candidate with complete-segment callback delivery.

Shares the existing bounded ownership, framing and cancellation implementation;
native inference is not preemptible within an acoustic segment. No speech is
cached by default. Voice 1 is the upstream Bella voice.
"""

import hashlib
import importlib
from collections.abc import Collection
from pathlib import Path
from typing import Any

from vasa.speech.kokoro import KokoroInt8TTS
from vasa.speech.models import ESPEAK_TREE_SHA256, sha256_file, verify_files

KITTEN_ARCHIVE_ROOT = "kitten-micro-en-v0_8"
KITTEN_ARCHIVE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    "kitten-micro-en-v0_8.tar.bz2"
)
KITTEN_ARCHIVE_SHA256 = "85faaea7511ca9d1d2f251fed0a4553bdf0d1ee046102fa60ddd8046c751f76f"

KITTEN_MICRO_FILES = {
    "model.onnx": "7cf07fcc77f3823c55fc9fb49594cfa421861a6eee9d63640cce708a174103f8",
    "voices.bin": "12ad10f1fcce8a458b5cf79769b8edd4ba0e11e9fb6532fd192c3500b2b37a5d",
    "tokens.txt": "934a4188addc7665dd3410256bb622169242357fbb99d840d9351209b486dabb",
    "LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}


def verify_kitten_micro(directory: Path) -> None:
    if directory.is_symlink() or any(parent.is_symlink() for parent in directory.parents):
        raise RuntimeError("Kitten model directory must not use symlinks")
    try:
        verify_files(directory, KITTEN_MICRO_FILES)
    except RuntimeError:
        raise RuntimeError(
            "Kitten Micro model missing or invalid; run scripts/prepare_speech.py --kitten-micro"
        ) from None
    resources = directory / "espeak-ng-data"
    if not resources.is_dir() or resources.is_symlink():
        raise RuntimeError("Kitten phonemizer data missing or invalid")
    digest = hashlib.sha256()
    for path in sorted(resources.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Kitten phonemizer data invalid")
        if path.is_file():
            digest.update(path.relative_to(resources).as_posix().encode() + b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    if digest.hexdigest() != ESPEAK_TREE_SHA256:
        raise RuntimeError("Kitten phonemizer data invalid")


class KittenMicroTTS(KokoroInt8TTS):
    """One preloaded Micro 0.8 model; bounded output and tracked native cleanup."""

    _worker_name = "vasa-kitten-micro"
    _speaker_id = 1

    def __init__(
        self,
        model_dir: Path,
        *,
        num_threads: int = 1,
        max_streams: int = 10,
        queue_frames: int = 8,
        cache_bytes: int = 0,
        cache_phrases: Collection[str] | None = None,
    ) -> None:
        super().__init__(
            model_dir,
            num_threads=num_threads,
            max_streams=max_streams,
            queue_frames=queue_frames,
            cache_bytes=cache_bytes,
            cache_phrases=cache_phrases,
        )

    def _verify_assets(self, model_dir: Path) -> None:
        verify_kitten_micro(model_dir)

    def _create_model(self, model_dir: Path, num_threads: int) -> Any:
        native = importlib.import_module("sherpa_onnx")
        kitten = native.OfflineTtsKittenModelConfig(
            model=str(model_dir / "model.onnx"),
            voices=str(model_dir / "voices.bin"),
            tokens=str(model_dir / "tokens.txt"),
            data_dir=str(model_dir / "espeak-ng-data"),
            length_scale=1.0,
        )
        return native.OfflineTts(
            native.OfflineTtsConfig(
                model=native.OfflineTtsModelConfig(
                    kitten=kitten, num_threads=num_threads, provider="cpu"
                ),
                max_num_sentences=1,
            )
        )
