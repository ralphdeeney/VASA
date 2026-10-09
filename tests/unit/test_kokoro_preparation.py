from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts import prepare_kokoro_int8 as preparation
from vasa.config import Settings


def test_default_and_environment_candidate_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VASA_TTS_PROVIDER", raising=False)
    assert Settings(_env_file=None).tts_provider == "ljspeech"
    monkeypatch.setenv("VASA_TTS_PROVIDER", "kokoro-int8")
    candidate = Settings(_env_file=None)
    assert candidate.tts_provider == "kokoro-int8"
    assert candidate.kokoro_num_threads == 1
    monkeypatch.setenv("VASA_KOKORO_NUM_THREADS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_changed_cached_archive_is_preserved_and_never_extracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename, _ = preparation.ARCHIVES["kokoro-int8"]
    archive = tmp_path / "archives" / filename
    archive.parent.mkdir()
    archive.write_bytes(b"corrupt cached download")

    def forbidden(*args: object) -> None:
        pytest.fail("Unverified cached archive must not be downloaded over or extracted")

    monkeypatch.setattr(preparation, "download", forbidden)
    monkeypatch.setattr(preparation, "extract_safe", forbidden)
    with pytest.raises(RuntimeError, match="Pinned archive mismatch"):
        preparation.prepare(tmp_path)
    assert archive.read_bytes() == b"corrupt cached download"
    assert not (tmp_path / "models").exists()


def test_symlink_cache_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlinks"):
        preparation.prepare(link)
