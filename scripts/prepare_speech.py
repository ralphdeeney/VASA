"""Fetch pinned, verified CPU speech models; never change expected artifact hashes."""

import argparse
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

from vasa.speech.models import (
    ASR_BASE,
    ASR_COMMIT,
    ASR_FILES,
    ESPEAK_TREE_SHA256,
    FIXTURE_FILES,
    TTS_ARCHIVE_ROOT,
    TTS_ARCHIVE_SHA256,
    TTS_FILES,
    TTS_URL,
    SpeechModels,
    sha256_file,
    verify_files,
)


def download(url: str, destination: Path, expected: str) -> None:
    if not url.startswith("https://"):
        raise ValueError("Speech artifacts require HTTPS")
    size = 0
    with urllib.request.urlopen(url, timeout=30) as response, destination.open("xb") as target:
        if not response.geturl().startswith("https://"):
            raise RuntimeError("Speech artifact redirect must preserve HTTPS")
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 150 * 1024 * 1024:
                raise RuntimeError("Speech artifact exceeds download limit")
            target.write(chunk)
    if sha256_file(destination) != expected:
        destination.unlink()
        raise RuntimeError("Speech artifact checksum mismatch")


def extract_archive(archive: Path, destination: Path) -> None:
    total = 0
    count = 0
    names: set[str] = set()
    with tarfile.open(archive, mode="r|bz2") as source:
        for member in source:
            count += 1
            path = PurePosixPath(member.name)
            if (
                count > 2048
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != TTS_ARCHIVE_ROOT
                or len(member.name) > 512
                or member.name in names
                or not (member.isfile() or member.isdir())
            ):
                raise RuntimeError("Unsafe speech archive member")
            names.add(member.name)
            total += member.size
            if member.size < 0 or total > 250 * 1024 * 1024:
                raise RuntimeError("Speech archive exceeds extraction limit")
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                content = source.extractfile(member)
                if content is None:
                    raise RuntimeError("Invalid speech archive file")
                with content, target.open("xb") as output:
                    shutil.copyfileobj(content, output)


def prepare(root: Path) -> SpeechModels:
    ensure_plain_directory(root)
    models = SpeechModels(root)
    if root.exists():
        # Validate every component before downloading or mutating any cache file.
        for component in ("asr", "fixtures", "tts"):
            ensure_plain_directory(root / component)
        # Add newly pinned components without overwriting any existing asset.
        # Corrupted existing assets remain a hard failure, never silently repaired.
        for group, files, prefix in [
            ("asr", ASR_FILES, ""),
            ("fixtures", FIXTURE_FILES, "test_wavs/"),
        ]:
            directory = root / group
            directory.mkdir(exist_ok=True)
            for name, digest in files.items():
                path = directory / name
                if path.exists() or path.is_symlink():
                    verify_files(directory, {name: digest})
                else:
                    with tempfile.TemporaryDirectory(prefix="speech-upgrade-", dir=root) as temp:
                        staged = Path(temp) / name
                        download(ASR_BASE + prefix + name, staged, digest)
                        staged.rename(path)
        models.verify()
        metadata_path = root / "manifest.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["asr"]["sha256"] = ASR_FILES
        metadata["fixtures"]["sha256"] = FIXTURE_FILES
        with tempfile.NamedTemporaryFile("w", dir=root, delete=False) as output:
            json.dump(metadata, output, indent=2)
            output.write("\n")
        Path(output.name).replace(metadata_path)
        return models
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="speech-prepare-", dir=root.parent) as temporary:
        staging = Path(temporary) / "models"
        staging.mkdir()
        for group, files, prefix in [
            ("asr", ASR_FILES, ""),
            ("fixtures", FIXTURE_FILES, "test_wavs/"),
        ]:
            directory = staging / group
            directory.mkdir()
            for name, digest in files.items():
                download(ASR_BASE + prefix + name, directory / name, digest)
        archive = Path(temporary) / "tts.tar.bz2"
        download(TTS_URL, archive, TTS_ARCHIVE_SHA256)
        extract_archive(archive, Path(temporary) / "extracted")
        shutil.move(str(Path(temporary) / "extracted" / TTS_ARCHIVE_ROOT), staging / "tts")
        manifest = {
            "asr": {
                "source": ASR_BASE,
                "commit": ASR_COMMIT,
                "sha256": ASR_FILES,
                "license": "Apache-2.0 model; LibriSpeech public-domain recordings",
            },
            "tts": {
                "source": TTS_URL,
                "release_asset_id": 276487081,
                "archive_sha256": TTS_ARCHIVE_SHA256,
                "sha256": TTS_FILES,
                "espeak_tree_sha256": ESPEAK_TREE_SHA256,
                "model_card": "tts/MODEL_CARD",
                "dataset_license": "public domain",
                "phonemizer_license": "espeak-ng GPL-3.0-or-later; bundled upstream data",
            },
            "fixtures": {
                "source": ASR_BASE + "test_wavs/",
                "sha256": FIXTURE_FILES,
                "license": "LibriSpeech recordings from public-domain audiobooks",
            },
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        SpeechModels(staging).verify()
        staging.rename(root)  # same-filesystem atomic publication of a complete verified cache
    return models


def ensure_plain_directory(path: Path) -> None:
    if ".." in path.parts:
        raise RuntimeError("Speech cache paths must not contain parent traversal")
    absolute = path.absolute()
    for ancestor in [absolute, *absolute.parents]:
        if ancestor.is_symlink():
            raise RuntimeError("Speech cache directory and ancestors must not be symbolic links")
        if ancestor.exists() and not ancestor.is_dir():
            raise RuntimeError("Speech cache path requires ordinary directories")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".local/speech"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        SpeechModels(args.directory).verify()
    else:
        prepare(args.directory)
    print("Verified CPU speech assets are ready.")


if __name__ == "__main__":
    main()
