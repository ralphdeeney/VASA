"""Pinned sentence-transformers MiniLM ONNX inference on CPU only."""

import hashlib
import threading
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from tokenizers import Tokenizer

MODEL_COMMIT = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_BASE = f"https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{MODEL_COMMIT}"
MODEL_FILES = {
    "model.onnx": (
        "onnx/model.onnx",
        "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    ),
}
IDENTITY = f"all-MiniLM-L6-v2:{MODEL_COMMIT}:onnx-mean-l2-v1"
DEFAULT_MODEL_DIR = Path(".local/knowledge")


def reject_symlinks(path: Path) -> None:
    """Check lexical ancestors before resolving or opening any cache path."""
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            raise RuntimeError("Knowledge model cache cannot contain symlinks")


def verify_artifact(file: Path, expected: str) -> None:
    reject_symlinks(file)
    if not file.is_file() or file.stat().st_size > 100 * 1024 * 1024:
        raise RuntimeError(
            "Knowledge model missing; run uv run python scripts/prepare_knowledge.py"
        )
    digest = hashlib.sha256()
    with file.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise RuntimeError("Knowledge model checksum mismatch; rerun scripts/prepare_knowledge.py")


def verify_model(directory: Path) -> None:
    reject_symlinks(directory)
    for name, (_, expected) in MODEL_FILES.items():
        verify_artifact(directory / name, expected)


class CPUEmbedder:
    """Lazy shared model, serialized bounded batches; callers must offload CPU work."""

    dimension = 384
    identity = IDENTITY

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR, *, num_threads: int = 2) -> None:
        if not 1 <= num_threads <= 8:
            raise ValueError("Knowledge thread limit is 1..8")
        self.model_dir = model_dir
        self.num_threads = num_threads
        self._lock = threading.Lock()
        self._session: Any = None
        self._tokenizer: Tokenizer | None = None

    def _load(self) -> None:
        if self._session is not None:
            return
        verify_model(self.model_dir)
        options = ort.SessionOptions()
        options.intra_op_num_threads = self.num_threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self._session = ort.InferenceSession(
            str(self.model_dir / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=256)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or not 1 <= len(texts) <= 512:
            raise ValueError("Embedding batch limit is 1..512")
        if any(not isinstance(text, str) or not text.strip() or len(text) > 4096 for text in texts):
            raise ValueError("Embedding text limit is 1..4096 characters")
        with self._lock:
            self._load()
            assert self._tokenizer is not None
            results: list[list[float]] = []
            for start in range(0, len(texts), 16):
                tokens = self._tokenizer.encode_batch(texts[start : start + 16])
                inputs = {
                    "input_ids": np.array([item.ids for item in tokens], dtype=np.int64),
                    "attention_mask": np.array(
                        [item.attention_mask for item in tokens], dtype=np.int64
                    ),
                    "token_type_ids": np.array([item.type_ids for item in tokens], dtype=np.int64),
                }
                expected = {item.name for item in self._session.get_inputs()}
                hidden = np.asarray(
                    self._session.run(None, {k: v for k, v in inputs.items() if k in expected})[0]
                )
                mask = inputs["attention_mask"][..., None]
                vectors = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                if vectors.shape != (len(tokens), self.dimension) or not np.isfinite(vectors).all():
                    raise RuntimeError("Invalid knowledge embedding model output")
                if np.any(norms <= 1e-12):
                    raise RuntimeError("Empty knowledge embedding")
                results.extend((vectors / norms).astype(np.float32).tolist())
            return results
