"""Prepare immutable Kokoro INT8 and Piper comparison assets outside production."""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from scripts.benchmark_tts_evaluation import ARCHIVE_BASE, download, extract_safe, sha256
from vasa.speech.kokoro import KOKORO_INT8_FILES, verify_kokoro_int8
from vasa.speech.models import ESPEAK_TREE_SHA256, verify_files

ARCHIVES = {
    "kokoro-int8": (
        "kokoro-int8-multi-lang-v1_1.tar.bz2",
        "a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6",
    ),
    "piper-libritts": (
        "vits-piper-en_US-libritts_r-medium.tar.bz2",
        "10dc268f3e371696d721486123e2705a9fc1faa113491979fde4d88dba1f1b1c",
    ),
}
PIPER_FILES = {
    "en_US-libritts_r-medium.onnx": (
        "8cce84cee4060bc3c2194bf95d33253c48dc8ff15e197b3b7a00b334ee0017f4"
    ),
    "tokens.txt": "620e1aecf1a68fea3ba5850d137b0138fa2037c9b372dad13b95a2a215d0849a",
    "MODEL_CARD": "0ccde6927e5bb4d743f4ea39618a9387ba18cca3351220a8a9cfdbc68b30fcb9",
}


def verify_piper(directory: Path) -> None:
    verify_files(directory, PIPER_FILES)
    resources = directory / "espeak-ng-data"
    if not resources.is_dir() or resources.is_symlink():
        raise RuntimeError("Invalid Piper phonemizer resources")
    digest = hashlib.sha256()
    for path in sorted(resources.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Invalid Piper phonemizer resources")
        if path.is_file():
            digest.update(path.relative_to(resources).as_posix().encode() + b"\0")
            digest.update(bytes.fromhex(sha256(path)))
    if digest.hexdigest() != ESPEAK_TREE_SHA256:
        raise RuntimeError("Invalid Piper phonemizer resources")


def prepare(root: Path) -> dict[str, object]:
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise RuntimeError("Evaluation cache must not use symlinks")
    root.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, (filename, expected) in ARCHIVES.items():
        archive = root / "archives" / filename
        target = root / "models" / name
        for path in (archive, target):
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                raise RuntimeError("Evaluation cache must not use symlinks")
        if not archive.exists():
            download(ARCHIVE_BASE + filename, archive)
        if sha256(archive) != expected:
            raise RuntimeError(f"Pinned archive mismatch: {name}; preserve and inspect cache")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
                extracted = extract_safe(archive, Path(temporary))
                shutil.move(str(extracted), target)
        if name == "kokoro-int8":
            verify_kokoro_int8(target)
            files = KOKORO_INT8_FILES
        else:
            verify_piper(target)
            files = PIPER_FILES
        records[name] = {"url": ARCHIVE_BASE + filename, "sha256": expected, "files": files}
    return {"schema_version": 1, "artifacts": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".local/tts-evaluation"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.root), indent=2))


if __name__ == "__main__":
    main()
