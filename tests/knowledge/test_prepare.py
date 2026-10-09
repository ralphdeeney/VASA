import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import prepare_knowledge


def test_existing_verified_cache_avoids_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"verified model fixture"
    digest = hashlib.sha256(content).hexdigest()
    files = {
        "model.onnx": ("onnx/model.onnx", digest),
        "tokenizer.json": ("tokenizer.json", digest),
    }
    for name in files:
        (tmp_path / name).write_bytes(content)
    monkeypatch.setattr(prepare_knowledge, "MODEL_FILES", files)
    monkeypatch.setattr("vasa.knowledge.embedding.MODEL_FILES", files)
    download = Mock(side_effect=AssertionError("verified cache must not download"))
    monkeypatch.setattr(prepare_knowledge.subprocess, "run", download)
    prepare_knowledge.prepare(tmp_path)
    download.assert_not_called()
    assert "Apache-2.0" in (tmp_path / "NOTICE.txt").read_text()


def test_corrupt_cache_fails_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "model.onnx").write_bytes(b"corrupt")
    download = Mock(side_effect=AssertionError("corrupt cache must fail"))
    monkeypatch.setattr(prepare_knowledge.subprocess, "run", download)
    with pytest.raises(RuntimeError, match="checksum"):
        prepare_knowledge.prepare(tmp_path)
    download.assert_not_called()


def test_setup_rejects_symlink_ancestor_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlinks"):
        prepare_knowledge.prepare(link / "cache")
    assert not (target / "cache").exists()
