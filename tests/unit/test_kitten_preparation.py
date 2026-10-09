from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.prepare_speech import prepare_kitten_assets
from vasa.config import Settings
from vasa.speech.kitten import KITTEN_ARCHIVE_ROOT


def test_kitten_trusted_selection_preserves_kokoro_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VASA_TTS_PROVIDER", raising=False)
    assert Settings(_env_file=None).tts_provider == "kokoro-int8"
    monkeypatch.setenv("VASA_TTS_PROVIDER", "kitten-micro")
    settings = Settings(_env_file=None)
    assert settings.tts_provider == "kitten-micro"
    assert settings.kitten_num_threads == 1
    assert settings.kitten_model_dir == Path(".local/speech/kitten-micro")
    monkeypatch.setenv("VASA_KITTEN_NUM_THREADS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_kitten_corrupt_cached_archive_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    archive = Path(".local/tts-evaluation/archives") / (KITTEN_ARCHIVE_ROOT + ".tar.bz2")
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"invalid immutable archive")
    with pytest.raises(RuntimeError, match="Pinned Kitten archive mismatch"):
        prepare_kitten_assets(Path("speech"))
    assert archive.read_bytes() == b"invalid immutable archive"
    assert not Path("speech/kitten-micro").exists()


def test_kitten_invalid_existing_model_is_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "speech"
    target = root / "kitten-micro"
    target.mkdir(parents=True)
    marker = target / "model.onnx"
    marker.write_bytes(b"corrupt model")
    with pytest.raises(RuntimeError, match="missing or invalid"):
        prepare_kitten_assets(root)
    assert marker.read_bytes() == b"corrupt model"


def test_kitten_preparation_rejects_symlink_ancestor(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    link = tmp_path / "link"
    link.symlink_to(destination, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic links"):
        prepare_kitten_assets(link / "speech")
