from pathlib import Path

import pytest

from vasa.knowledge.embedding import IDENTITY, CPUEmbedder, verify_model


def test_missing_model_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="prepare_knowledge"):
        CPUEmbedder(tmp_path).embed(["hello"])


def test_checksum_rejects_corruption(tmp_path: Path) -> None:
    (tmp_path / "model.onnx").write_bytes(b"not a model")
    with pytest.raises(RuntimeError, match="checksum"):
        verify_model(tmp_path)


@pytest.mark.parametrize("texts", [[], [""], ["x" * 4097], ["x"] * 513])
def test_embedding_limits_before_model_loading(texts: list[str]) -> None:
    with pytest.raises(ValueError):
        CPUEmbedder().embed(texts)


def test_versioned_identity_and_dimension() -> None:
    assert CPUEmbedder.dimension == 384
    assert CPUEmbedder.identity == IDENTITY
    assert "onnx-mean-l2-v1" in IDENTITY


@pytest.mark.parametrize("kind", ["directory", "ancestor", "artifact", "dangling"])
def test_model_cache_rejects_symlinks(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "target"
    target.mkdir()
    model = target / "model.onnx"
    model.write_bytes(b"model")
    cache = tmp_path / "cache"
    if kind == "directory":
        cache.symlink_to(target, target_is_directory=True)
    elif kind == "ancestor":
        cache.symlink_to(target, target_is_directory=True)
        cache = cache / "nested"
    else:
        cache.mkdir()
        (cache / "model.onnx").symlink_to(model if kind == "artifact" else tmp_path / "missing")
    with pytest.raises(RuntimeError, match="symlinks"):
        verify_model(cache)
