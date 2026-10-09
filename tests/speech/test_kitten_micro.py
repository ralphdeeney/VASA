import asyncio
import hashlib
import threading
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from vasa.contracts.models import AudioFrame
from vasa.speech import kitten


def fake_provider(
    monkeypatch: pytest.MonkeyPatch, generate: Callable[..., Any], **options: Any
) -> tuple[kitten.KittenMicroTTS, list[dict[str, Any]]]:
    original_import = kitten.importlib.import_module
    configs: list[dict[str, Any]] = []

    def model_config(**kwargs: Any) -> dict[str, Any]:
        configs.append(kwargs)
        return kwargs

    native = SimpleNamespace(
        OfflineTtsKittenModelConfig=lambda **kw: kw,
        OfflineTtsModelConfig=model_config,
        OfflineTtsConfig=lambda **kw: kw,
        OfflineTts=lambda _: SimpleNamespace(generate=generate, sample_rate=24000),
    )
    monkeypatch.setattr(kitten, "verify_kitten_micro", lambda _: None)
    monkeypatch.setattr(
        kitten.importlib,
        "import_module",
        lambda name: native if name == "sherpa_onnx" else original_import(name),
    )
    return kitten.KittenMicroTTS(Path("unused"), **options), configs


async def test_preload_once_cpu_threads_voice_and_audio_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, int]] = []

    def generate(text: str, **kwargs: Any) -> SimpleNamespace:
        requests.append((text, kwargs["sid"]))
        return SimpleNamespace(sample_rate=24000, samples=np.full(2400, 0.2, np.float32))

    provider, configs = fake_provider(monkeypatch, generate)
    try:
        frames = [frame async for frame in provider.synthesize("Welcome. Tomorrow works.")]
        for text in ["Thank you.", "Thank you.", "Your booking is private."]:
            async for _ in provider.synthesize(text):
                pass
        assert len(configs) == 1
        assert configs[0]["provider"] == "cpu" and configs[0]["num_threads"] == 1
        assert configs[0]["kitten"]["length_scale"] == 1.0
        assert configs[0]["kitten"]["model"] == "unused/model.onnx"
        assert all(sid == 1 for _, sid in requests)
        assert [text for text, _ in requests].count("Thank you.") == 2
        assert len(frames) == 4
        assert [frame.sequence for frame in frames] == list(range(4))
        assert all(frame.sample_rate == 16000 and len(frame.pcm) == 1920 for frame in frames)
        assert any(frames[0].pcm)
        assert not provider._cache and provider._cache_size == 0
    finally:
        await provider.aclose()


async def test_segment_callback_forwarded_once_and_cancellation_retains_native_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    segment_delivered = threading.Event()
    callbacks: list[int] = []

    def generate(_: str, **kwargs: Any) -> SimpleNamespace:
        callbacks.append(kwargs["callback"](np.full(1440, 0.1, np.float32), 0.5))
        segment_delivered.set()
        assert release.wait(3)
        callbacks.append(kwargs["callback"](np.full(1440, 0.9, np.float32), 1.0))
        return SimpleNamespace(sample_rate=24000, samples=np.full(2880, 0.8, np.float32))

    provider, _ = fake_provider(monkeypatch, generate)
    stream = cast(AsyncGenerator[AudioFrame, None], provider.synthesize("Hello."))
    try:
        first = await asyncio.wait_for(anext(stream), 1)
        assert 3000 < int(np.frombuffer(first.pcm, dtype="<i2")[100]) < 4000
        assert await asyncio.to_thread(segment_delivered.wait, 1)
        assert provider._slot.locked() and len(provider._pending) == 1
        await asyncio.wait_for(stream.aclose(), 0.2)
        assert provider._slot.locked() and len(provider._pending) == 1
        release.set()
        await asyncio.wait_for(provider.aclose(), 1)
        assert callbacks == [1, 0]
        assert provider._model is None and not provider._pending
        assert not provider._slot.locked()
    finally:
        release.set()
        await stream.aclose()
        await provider.aclose()


async def test_bounded_callback_output_unblocks_when_consumer_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted: list[int] = []
    finished = threading.Event()

    def generate(_: str, **kwargs: Any) -> SimpleNamespace:
        for _ in range(100):
            result = kwargs["callback"](np.ones(1440, np.float32), 0.5)
            accepted.append(result)
            if result == 0:
                break
        finished.set()
        return SimpleNamespace(sample_rate=24000, samples=np.ones(1440, np.float32))

    provider, _ = fake_provider(monkeypatch, generate, queue_frames=2)
    stream = cast(AsyncGenerator[AudioFrame, None], provider.synthesize("Private speech."))
    try:
        await anext(stream)
        await asyncio.sleep(0.1)
        assert not finished.is_set() and len(accepted) <= 3
        await asyncio.wait_for(stream.aclose(), 0.2)
        await asyncio.wait_for(provider.aclose(), 1)
        assert finished.is_set() and accepted[-1] == 0
        assert not provider._cache
    finally:
        await stream.aclose()
        await provider.aclose()


def test_pinned_assets_and_phonemizer_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"verified")
    monkeypatch.setattr(
        kitten, "KITTEN_MICRO_FILES", {model.name: hashlib.sha256(b"verified").hexdigest()}
    )
    resources = tmp_path / "espeak-ng-data"
    resources.mkdir()
    monkeypatch.setattr(kitten, "ESPEAK_TREE_SHA256", hashlib.sha256().hexdigest())
    kitten.verify_kitten_micro(tmp_path)
    model.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="model missing or invalid"):
        kitten.verify_kitten_micro(tmp_path)
    model.write_bytes(b"verified")
    (resources / "extra").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="phonemizer data invalid"):
        kitten.verify_kitten_micro(tmp_path)
    (resources / "extra").unlink()
    (resources / "link").symlink_to(model)
    with pytest.raises(RuntimeError, match="phonemizer data invalid"):
        kitten.verify_kitten_micro(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("num_threads", 0), ("num_threads", True), ("max_streams", 11), ("queue_frames", 65)],
)
def test_invalid_limits_rejected_before_native_load(field: str, value: int) -> None:
    with pytest.raises(ValueError):
        kitten.KittenMicroTTS(Path("missing"), **{field: value})


def test_shared_cache_cannot_accept_tenant_or_generated_text() -> None:
    with pytest.raises(ValueError, match="server-owned"):
        kitten.KittenMicroTTS(Path("missing"), cache_phrases=["Your private account balance."])
