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
    KOKORO_ARCHIVE_ROOT,
    KOKORO_ARCHIVE_SHA256,
    KOKORO_URL,
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


def extract_archive(
    archive: Path, destination: Path, *, expected_root: str = TTS_ARCHIVE_ROOT
) -> None:
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
                or path.parts[0] != expected_root
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


def prepare_tts_assets(root: Path) -> None:
    from vasa.speech.kokoro import verify_kokoro_int8
    from vasa.speech.models import verify_tts

    for group, archive_root, url, expected, verify in [
        ("piper", TTS_ARCHIVE_ROOT, TTS_URL, TTS_ARCHIVE_SHA256, verify_tts),
        ("kokoro-int8", KOKORO_ARCHIVE_ROOT, KOKORO_URL, KOKORO_ARCHIVE_SHA256, verify_kokoro_int8),
    ]:
        target = root / group
        ensure_plain_directory(target)
        if target.exists():
            verify(target)
            continue
        with tempfile.TemporaryDirectory(prefix="tts-prepare-", dir=root) as temporary:
            staging = Path(temporary)
            cached = Path(".local/tts-evaluation/archives") / (archive_root + ".tar.bz2")
            if cached.is_file() and not cached.is_symlink() and sha256_file(cached) == expected:
                archive = cached
            else:
                archive = staging / "model.tar.bz2"
                download(url, archive, expected)
            extract_archive(archive, staging / "extracted", expected_root=archive_root)
            extracted = staging / "extracted" / archive_root
            verify(extracted)
            extracted.rename(target)


def prepare_kitten_assets(root: Path) -> None:
    """Publish optional Micro assets atomically; never replace an invalid cache."""
    from vasa.speech.kitten import (
        KITTEN_ARCHIVE_ROOT,
        KITTEN_ARCHIVE_SHA256,
        KITTEN_ARCHIVE_URL,
        verify_kitten_micro,
    )

    ensure_plain_directory(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "kitten-micro"
    ensure_plain_directory(target)
    if target.exists():
        verify_kitten_micro(target)
        return
    with tempfile.TemporaryDirectory(prefix="kitten-prepare-", dir=root) as temporary:
        staging = Path(temporary)
        cached = Path(".local/tts-evaluation/archives") / (KITTEN_ARCHIVE_ROOT + ".tar.bz2")
        if cached.is_file() and not cached.is_symlink():
            if sha256_file(cached) != KITTEN_ARCHIVE_SHA256:
                raise RuntimeError("Pinned Kitten archive mismatch; preserve and inspect cache")
            archive = cached
        else:
            archive = staging / "model.tar.bz2"
            download(KITTEN_ARCHIVE_URL, archive, KITTEN_ARCHIVE_SHA256)
        extract_archive(archive, staging / "extracted", expected_root=KITTEN_ARCHIVE_ROOT)
        extracted = staging / "extracted" / KITTEN_ARCHIVE_ROOT
        verify_kitten_micro(extracted)
        extracted.rename(target)


def manifest() -> dict[str, object]:
    from vasa.speech.kokoro import KOKORO_INT8_FILES

    return {
        "default_provider": "kokoro-int8",
        "asr": {
            "source": ASR_BASE,
            "commit": ASR_COMMIT,
            "sha256": ASR_FILES,
            "license": "Apache-2.0 model; LibriSpeech public-domain recordings",
        },
        "tts": {
            "provider": "piper",
            "source": TTS_URL,
            "archive_sha256": TTS_ARCHIVE_SHA256,
            "sha256": TTS_FILES,
            "espeak_tree_sha256": ESPEAK_TREE_SHA256,
            "model_card": "piper/MODEL_CARD",
            "dataset_license": "LibriTTS-R CC BY 4.0; see model card",
            "phonemizer_license": "espeak-ng GPL-3.0-or-later",
        },
        "kokoro-int8": {
            "source": KOKORO_URL,
            "archive_sha256": KOKORO_ARCHIVE_SHA256,
            "sha256": KOKORO_INT8_FILES,
            "espeak_tree_sha256": ESPEAK_TREE_SHA256,
            "license": "Apache-2.0 model; eSpeak phonemizer GPL-3.0-or-later",
        },
        "fixtures": {
            "source": ASR_BASE + "test_wavs/",
            "sha256": FIXTURE_FILES,
            "license": "LibriSpeech recordings from public-domain audiobooks",
        },
    }


def prepare(root: Path) -> SpeechModels:
    ensure_plain_directory(root)
    models = SpeechModels(root)
    if root.exists():
        # Validate every component before downloading or mutating any cache file.
        for component in ("asr", "fixtures", "piper", "kokoro-int8"):
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
        prepare_tts_assets(root)
        models.verify()
        metadata_path = root / "manifest.json"
        metadata = manifest()
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
        prepare_tts_assets(staging)
        (staging / "manifest.json").write_text(json.dumps(manifest(), indent=2) + "\n")
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
    parser.add_argument("--kitten-micro", action="store_true", help="Include optional Micro 0.8")
    args = parser.parse_args()
    if args.verify_only:
        SpeechModels(args.directory).verify()
    else:
        prepare(args.directory)
    if args.kitten_micro:
        if args.verify_only:
            from vasa.speech.kitten import verify_kitten_micro

            verify_kitten_micro(args.directory / "kitten-micro")
        else:
            prepare_kitten_assets(args.directory)
    print("Verified CPU speech assets are ready.")


if __name__ == "__main__":
    main()
