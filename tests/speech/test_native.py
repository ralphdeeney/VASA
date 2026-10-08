import asyncio
import hashlib
import importlib
import io
import math
import tarfile
import threading
import time
import wave
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import pytest_asyncio

from scripts.prepare_speech import extract_archive, prepare
from vasa.contracts.models import AudioFrame
from vasa.speech import SherpaSTT, SherpaTTS, SpeechModels
from vasa.speech.models import NativeWorker, verify_files
from vasa.speech.synthesis import text_chunks

MODEL_ROOT = Path(".local/speech")


def wav_pcm(path: Path) -> bytes:
    with wave.open(str(path)) as source:
        assert source.getnchannels() == 1 and source.getsampwidth() == 2
        rate = source.getframerate()
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
            np.float32
        )
    if rate != 16000:
        factor = math.gcd(rate, 16000)
        audio = importlib.import_module("scipy.signal").resample_poly(
            audio, 16000 // factor, rate // factor
        )
    return bytes(np.clip(audio, -32768, 32767).astype("<i2").tobytes())


async def pcm_frames(pcm: bytes) -> AsyncIterator[AudioFrame]:
    for offset in range(0, len(pcm), 1920):
        yield AudioFrame(pcm[offset : offset + 1920].ljust(1920, b"\0"), 16000, offset // 1920, 0)


def word_errors(reference: str, hypothesis: str) -> int:
    left, right = reference.lower().split(), hypothesis.lower().split()
    row = list(range(len(right) + 1))
    for index, word in enumerate(left, 1):
        next_row = [index]
        for column, candidate in enumerate(right, 1):
            next_row.append(
                min(row[column] + 1, next_row[-1] + 1, row[column - 1] + int(word != candidate))
            )
        row = next_row
    return row[-1]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def providers() -> AsyncIterator[tuple[SherpaSTT, SherpaTTS]]:
    models = SpeechModels(MODEL_ROOT)
    models.verify()  # Missing models are an actionable failure; never silently skipped.
    stt, tts = SherpaSTT(models.stt_dir), SherpaTTS(models.tts_dir)
    yield stt, tts
    await stt.aclose()
    await tts.aclose()


@pytest.mark.speech_native
async def test_real_streaming_stt_three_independent_fixtures_aggregate_wer(
    providers: tuple[SherpaSTT, SherpaTTS],
) -> None:
    # Acceptance threshold defined before this test's first run: aggregate WER <= 0.15.
    # Audio/transcripts are independently authored upstream LibriSpeech fixtures,
    # not synthesized by the TTS under test. 8 kHz input exercises actual resampling.
    stt, _ = providers
    models = SpeechModels(MODEL_ROOT)
    references = {}
    for line in (models.fixture_dir / "trans.txt").read_text().splitlines():
        name, text = line.split(" ", 1)
        references[name] = text
    errors = words = 0
    for name in ["0.wav", "1.wav", "8k.wav"]:
        started = time.perf_counter()
        updates = [
            text async for text in stt.transcribe(pcm_frames(wav_pcm(models.fixture_dir / name)))
        ]
        assert len(updates) >= 2
        assert updates[-1]
        count = word_errors(references[name], updates[-1])
        errors += count
        words += len(references[name].split())
        print(
            f"native_stt fixture={name} elapsed={time.perf_counter() - started:.4f}s "
            f"updates={len(updates)} word_errors={count}"
        )
    print(f"native_stt aggregate_wer={errors / words:.4f} words={words}")
    assert errors / words <= 0.15


@pytest.mark.speech_native
async def test_real_tts_audio_format_and_supplemental_recognition(
    providers: tuple[SherpaSTT, SherpaTTS],
) -> None:
    stt, tts = providers
    text = "Hello. Your appointment is confirmed for tomorrow morning."
    started = time.perf_counter()
    frames = [frame async for frame in tts.synthesize(text)]
    elapsed = time.perf_counter() - started
    assert frames and 1 <= len(frames) * 0.06 <= 15
    assert [frame.sequence for frame in frames] == list(range(len(frames)))
    assert all(
        len(frame.pcm) == 1920 and frame.sample_rate == 16000 and frame.channels == 1
        for frame in frames
    )
    pcm = b"".join(frame.pcm for frame in frames)
    repeated = b"".join([frame.pcm async for frame in tts.synthesize(text)])
    assert repeated == pcm  # Production articulation must not depend on random prosody.
    assert np.max(np.abs(np.frombuffer(pcm, dtype="<i2").astype(np.int32))) > 1000
    updates = [text async for text in stt.transcribe(pcm_frames(pcm))]
    assert "appointment" in updates[-1].lower()
    # This BPE model may spell the same spoken word as "to morrow".
    assert "tomorrow" in updates[-1].lower().replace(" ", "")
    print(
        f"native_tts elapsed={elapsed:.4f}s audio_duration={len(frames) * 0.06:.2f}s "
        f"frames={len(frames)} supplemental_text={updates[-1]}"
    )


@pytest.mark.speech_native
async def test_per_utterance_stt_streams_do_not_share_text(
    providers: tuple[SherpaSTT, SherpaTTS],
) -> None:
    stt, _ = providers

    async def recognize(name: str) -> list[str]:
        return [
            text
            async for text in stt.transcribe(pcm_frames(wav_pcm(MODEL_ROOT / "fixtures" / name)))
        ]

    first, second = await asyncio.gather(recognize("0.wav"), recognize("8k.wav"))
    assert "yellow" in first[-1].lower() and "hester" not in first[-1].lower()
    assert "hester" in second[-1].lower() and "yellow" not in second[-1].lower()


@pytest.mark.speech_native
async def test_canceled_tts_generator_releases_slot_for_next_utterance(
    providers: tuple[SherpaSTT, SherpaTTS],
) -> None:
    _, tts = providers
    output = tts.synthesize("Welcome to our business. " * 30)
    first = await anext(output)
    assert len(first.pcm) == 1920
    await output.aclose()
    next_frames = [frame async for frame in tts.synthesize("Hello again.")]
    assert next_frames


@pytest.mark.speech_native
async def test_cancel_running_native_tts_then_generate_next_utterance(
    providers: tuple[SherpaSTT, SherpaTTS],
) -> None:
    _, tts = providers
    output = tts.synthesize("Your appointment is confirmed for tomorrow morning. " * 4)
    task = asyncio.create_task(anext(output))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)
    await output.aclose()
    recovered = tts.synthesize("Hello again.")
    try:
        assert len((await asyncio.wait_for(anext(recovered), 10)).pcm) == 1920
    finally:
        await recovered.aclose()


@pytest.mark.speech_native
async def test_native_tts_callback_preserves_multi_sentence_batches(
    providers: tuple[SherpaSTT, SherpaTTS],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tts = providers
    text = "Thank you for calling. Your appointment is confirmed for tomorrow morning."
    native = tts._model
    batches: list[tuple[int, float]] = []

    class ObserveActualModel:
        def generate(
            self, text: str, *, sid: int, speed: float, callback: Callable[[Any, float], int]
        ) -> Any:
            def observe(samples: Any, progress: float) -> int:
                batches.append((len(samples), progress))
                return callback(samples, progress)

            return native.generate(text, sid=sid, speed=speed, callback=observe)

    # Observe real VITS callbacks, without replacing inference or generated audio.
    # The configured model emits one sentence per batch. An inverted callback
    # stops after progress 0.5, before the second actual sentence can be synthesized.
    monkeypatch.setattr(tts, "_model", ObserveActualModel())
    monkeypatch.setattr("vasa.speech.synthesis.text_chunks", lambda _: [text])
    frames = [frame async for frame in tts.synthesize(text)]
    assert [progress for _, progress in batches] == [0.5, 1.0]
    samples = sum(count for count, _ in batches)
    expected_frames = math.ceil(math.ceil(samples * 16000 / 22050) / 960)
    assert len(frames) == expected_frames
    assert all(len(frame.pcm) == 1920 for frame in frames)
    stopped: list[float] = []

    def wrong_polarity(samples: Any, progress: float) -> int:
        stopped.append(progress)
        return 0

    # Actual native negative control establishes that the regression detects
    # early stopping, independently of synthesized wording or STT substitutions.
    await asyncio.to_thread(native.generate, text, sid=0, speed=1.0, callback=wrong_polarity)
    assert stopped == [0.5]


async def test_native_offload_cancellation_keeps_admission_until_inference_finishes() -> None:
    worker = NativeWorker("vasa-test-native")
    entered, release = threading.Event(), threading.Event()
    semaphore = asyncio.Semaphore(1)

    def inference() -> str:
        entered.set()
        assert release.wait(2)
        return "done"

    async def admitted() -> str:
        async with semaphore:
            return await worker.run(inference)

    task = asyncio.create_task(admitted())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and semaphore.locked()
        task.cancel()  # repeated cancellation must not release a running native model
        await asyncio.sleep(0.02)
        assert not task.done() and semaphore.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not semaphore.locked()
    finally:
        release.set()
        await worker.aclose()


async def test_closed_native_provider_rejects_new_work() -> None:
    worker = NativeWorker("vasa-test-closed")
    assert await worker.run(lambda: "first") == "first"
    await worker.aclose()
    await worker.aclose()
    with pytest.raises(RuntimeError, match="provider is closed"):
        await worker.run(lambda: "never")


def test_integrity_checks_fail_on_tampered_assets(tmp_path: Path) -> None:
    asset = tmp_path / "model.onnx"
    asset.write_bytes(b"trusted")
    expected = {"model.onnx": hashlib.sha256(b"trusted").hexdigest()}
    verify_files(tmp_path, expected)
    asset.write_bytes(b"modified")
    with pytest.raises(RuntimeError, match="missing or invalid"):
        verify_files(tmp_path, expected)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("/absolute", tarfile.REGTYPE),
        ("vits-piper-en_US-ljspeech-medium-int8/link", tarfile.SYMTYPE),
    ],
)
def test_archive_rejects_unsafe_paths_and_links(tmp_path: Path, name: str, kind: bytes) -> None:
    archive = tmp_path / "unsafe.tar.bz2"
    with tarfile.open(archive, "w:bz2") as output:
        item = tarfile.TarInfo(name)
        item.type, item.linkname = kind, "../../escape"
        item.size = 0
        output.addfile(item, io.BytesIO())
    with pytest.raises(RuntimeError, match="Unsafe speech archive"):
        extract_archive(archive, tmp_path / "extracted")
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize("text", ["", " ", "x" * 2001, "hello\x00world"])
def test_tts_rejects_unbounded_or_invalid_text(text: str) -> None:
    with pytest.raises(ValueError, match="1 to 2000"):
        text_chunks(text)


def test_tts_chunks_bound_native_work_without_dropping_normal_text() -> None:
    text = "Welcome to our business. " * 50
    chunks = text_chunks(text)
    assert all(0 < len(chunk) <= 240 for chunk in chunks)
    assert " ".join(chunks) == text.strip()


@pytest.mark.parametrize("group", ["asr", "fixtures"])
def test_prepare_refuses_symlink_component_directories(tmp_path: Path, group: str) -> None:
    cache, outside = tmp_path / "cache", tmp_path / "outside"
    cache.mkdir()
    outside.mkdir()
    (cache / group).symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="must not be symbolic links"):
        prepare(cache)
    assert not list(outside.iterdir())


def test_prepare_refuses_symlink_ancestors(tmp_path: Path) -> None:
    outside, link = tmp_path / "outside", tmp_path / "link"
    outside.mkdir()
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="must not be symbolic links"):
        prepare(link / "speech")
    assert not list(outside.iterdir())
