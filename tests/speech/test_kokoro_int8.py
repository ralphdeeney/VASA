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
from vasa.speech import kokoro


def fake_provider(
    monkeypatch: pytest.MonkeyPatch, generate: Callable[..., Any], *, streams: int = 2
) -> tuple[kokoro.KokoroInt8TTS, list[dict[str, Any]]]:
    original_import = kokoro.importlib.import_module
    configs: list[dict[str, Any]] = []

    def model_config(**kwargs: Any) -> dict[str, Any]:
        configs.append(kwargs)
        return kwargs

    native = SimpleNamespace(
        OfflineTtsKokoroModelConfig=lambda **kw: kw,
        OfflineTtsModelConfig=model_config,
        OfflineTtsConfig=lambda **kw: kw,
        OfflineTts=lambda _: SimpleNamespace(generate=generate),
    )
    monkeypatch.setattr(kokoro, "verify_kokoro_int8", lambda _: None)
    monkeypatch.setattr(
        kokoro.importlib,
        "import_module",
        lambda name: native if name == "sherpa_onnx" else original_import(name),
    )
    return kokoro.KokoroInt8TTS(Path("unused"), max_streams=streams), configs


async def test_frame_format_chunk_order_and_model_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    texts: list[str] = []

    def generate(text: str, **_: Any) -> SimpleNamespace:
        texts.append(text)
        return SimpleNamespace(sample_rate=24000, samples=np.full(2400, 0.2, np.float32))

    provider, configs = fake_provider(monkeypatch, generate)
    try:
        first = [frame async for frame in provider.synthesize("Yes, I can help. Tomorrow works.")]
        second = [frame async for frame in provider.synthesize("Welcome.")]
        assert texts == ["Yes, I can help.", "Tomorrow works.", "Welcome."]
        assert len(configs) == 1 and configs[0]["num_threads"] == 1
        assert len(first) == 4 and len(second) == 2
        assert [frame.sequence for frame in first] == list(range(4))
        assert all(len(frame.pcm) == 1920 and frame.sample_rate == 16000 for frame in first)
        assert any(first[0].pcm) and first[1].pcm[-640:] == bytes(640)
    finally:
        await provider.aclose()


async def test_barge_in_detaches_consumer_but_retains_native_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = threading.Event(), threading.Event()
    callback_results: list[int] = []

    def generate(_: str, **kwargs: Any) -> SimpleNamespace:
        entered.set()
        assert release.wait(5)
        callback_results.append(kwargs["callback"](np.zeros(1, np.float32), 1.0))
        return SimpleNamespace(sample_rate=16000, samples=np.ones(960, np.float32))

    provider, _ = fake_provider(monkeypatch, generate)
    output = cast(AsyncGenerator[AudioFrame, None], provider.synthesize("Hello."))
    pending = asyncio.create_task(anext(output))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 0.2)
        assert len(provider._pending) == 1 and provider._slot.locked()
        replacement = cast(AsyncGenerator[AudioFrame, None], provider.synthesize("Again."))
        waiting = asyncio.create_task(anext(replacement))
        await asyncio.sleep(0.03)
        assert not waiting.done() and len(provider._pending) == 1
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiting, 0.2)
        await replacement.aclose()
        closer = asyncio.create_task(provider.aclose())
        await asyncio.sleep(0)
        closer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closer
        release.set()
        await provider.aclose()
        await provider.aclose()
        assert callback_results == [0]
        assert not provider._pending and not provider._slot.locked()
        assert provider._model is None
    finally:
        release.set()
        await output.aclose()
        await provider.aclose()


async def test_stalled_outputs_remain_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def generate(_: str, **__: Any) -> SimpleNamespace:
        return SimpleNamespace(sample_rate=16000, samples=np.ones(1920, np.float32))

    provider, _ = fake_provider(monkeypatch, generate, streams=1)
    first = cast(AsyncGenerator[AudioFrame, None], provider.synthesize("First."))
    second = cast(AsyncGenerator[AudioFrame, None], provider.synthesize("Second."))
    pending: asyncio.Task[AudioFrame] | None = None
    try:
        assert len((await anext(first)).pcm) == 1920
        pending = asyncio.create_task(anext(second))
        await asyncio.sleep(0.03)
        assert not pending.done() and not provider._pending
        await first.aclose()
        assert len((await asyncio.wait_for(pending, 1)).pcm) == 1920
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await first.aclose()
        await second.aclose()
        await provider.aclose()


@pytest.mark.parametrize("field", ["num_threads", "max_streams"])
@pytest.mark.parametrize("value", [0, 11, True, 1.5])
def test_worker_limits_rejected_before_model_load(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="worker limits"):
        kokoro.KokoroInt8TTS(Path("missing"), **{field: value})


def test_chunk_validation_and_bounds() -> None:
    chunks = kokoro.kokoro_chunks("A" * 480 + "; another clause, and a sentence.")
    assert all(0 < len(chunk) <= 240 for chunk in chunks)
    assert chunks[-1].endswith("another clause, and a sentence.")
    for invalid in [" ", "A" * 2001, "Hello\x00"]:
        with pytest.raises(ValueError):
            kokoro.kokoro_chunks(invalid)


def test_short_acknowledgement_stays_whole_and_long_clauses_are_meaningful() -> None:
    assert kokoro.kokoro_chunks("Certainly, I can help.") == ["Certainly, I can help."]
    sentence = (
        "Please tell me which day works best for your appointment, "
        "and whether you prefer the morning or afternoon, "
        "so that our team can find an available time and confirm the details with you."
    )
    chunks = kokoro.kokoro_chunks(sentence)
    assert len(chunks) == 3
    assert all(len(chunk.split()) >= 5 and len(chunk) <= 240 for chunk in chunks)
    assert " ".join(chunks) == sentence


def test_corrupt_assets_and_phonemizer_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model.int8.onnx"
    model.write_bytes(b"verified")
    monkeypatch.setattr(
        kokoro, "KOKORO_INT8_FILES", {model.name: hashlib.sha256(b"verified").hexdigest()}
    )
    data = tmp_path / "espeak-ng-data"
    data.mkdir()
    monkeypatch.setattr(kokoro, "ESPEAK_TREE_SHA256", hashlib.sha256().hexdigest())
    kokoro.verify_kokoro_int8(tmp_path)
    model.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="invalid"):
        kokoro.verify_kokoro_int8(tmp_path)
    model.write_bytes(b"verified")
    (data / "rogue").write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="invalid"):
        kokoro.verify_kokoro_int8(tmp_path)
    (data / "rogue").unlink()
    (data / "link").symlink_to(model)
    with pytest.raises(RuntimeError, match="invalid"):
        kokoro.verify_kokoro_int8(tmp_path)


@pytest.mark.parametrize("samples", [[], [float("nan")], [[0.1]]])
async def test_invalid_native_output_fails(
    monkeypatch: pytest.MonkeyPatch, samples: list[Any]
) -> None:
    provider, _ = fake_provider(
        monkeypatch, lambda *args, **kwargs: SimpleNamespace(sample_rate=16000, samples=samples)
    )
    try:
        with pytest.raises(RuntimeError, match="Invalid native"):
            await anext(provider.synthesize("Hello."))
    finally:
        await provider.aclose()
