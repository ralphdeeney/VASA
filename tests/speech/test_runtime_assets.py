"""Tiny checksum fixtures exercise selection; native model pins remain unchanged."""

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_speech
from vasa.speech import kitten, kokoro, models


@pytest.fixture
def assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blob = b"checksum fixture, not a native model"
    hashes = {"model.onnx": hashlib.sha256(blob).hexdigest()}
    monkeypatch.setattr(models, "ASR_FILES", hashes)
    monkeypatch.setattr(models, "TTS_FILES", hashes)
    monkeypatch.setattr(kokoro, "KOKORO_INT8_FILES", hashes)
    monkeypatch.setattr(kitten, "KITTEN_MICRO_FILES", hashes)
    empty_tree = hashlib.sha256().hexdigest()
    for module in (models, kokoro, kitten):
        monkeypatch.setattr(module, "ESPEAK_TREE_SHA256", empty_tree)

    def no_download(*args, **kwargs):
        pytest.fail("Runtime verification must never download or prepare models")

    monkeypatch.setattr(prepare_speech, "download", no_download)
    monkeypatch.setattr(prepare_speech.urllib.request, "urlopen", no_download)
    bundle = models.SpeechModels(tmp_path / "speech")
    bundle.stt_dir.mkdir(parents=True)
    (bundle.stt_dir / "model.onnx").write_bytes(blob)

    def local(provider: str, directory: Path | None = None) -> Path:
        path = (
            directory
            or {
                "piper": bundle.tts_dir,
                "kokoro-int8": bundle.kokoro_dir,
                "kitten-micro": bundle.kitten_dir,
            }[provider]
        )
        path.mkdir(parents=True)
        (path / "model.onnx").write_bytes(blob)
        (path / "espeak-ng-data").mkdir()
        return path

    return SimpleNamespace(bundle=bundle, local=local, blob=blob)


@pytest.mark.parametrize("provider", ["deepgram", "speechify"])
def test_cloud_runtime_requires_only_asr_and_is_read_only(assets, provider) -> None:
    before = set(assets.bundle.root.rglob("*"))
    assets.bundle.verify_runtime(provider)
    assert set(assets.bundle.root.rglob("*")) == before
    assert not assets.bundle.tts_dir.exists() and not assets.bundle.kokoro_dir.exists()
    assert not assets.bundle.kitten_dir.exists() and not assets.bundle.fixture_dir.exists()
    with pytest.raises(RuntimeError, match="missing or invalid"):
        assets.bundle.verify()  # Full provisioning verification is still strict.


@pytest.mark.parametrize("provider", ["piper", "kokoro-int8", "kitten-micro"])
def test_local_runtime_refuses_missing_selected_tts(assets, provider) -> None:
    with pytest.raises(RuntimeError, match="missing or invalid"):
        assets.bundle.verify_runtime(provider)


@pytest.mark.parametrize("provider", ["piper", "kokoro-int8", "kitten-micro"])
def test_local_runtime_needs_only_its_own_tts_and_preserves_checksums(assets, provider) -> None:
    path = assets.local(provider)
    assets.bundle.verify_runtime(provider)
    (path / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="missing or invalid"):
        assets.bundle.verify_runtime(provider)
    (path / "model.onnx").write_bytes(assets.blob)
    (path / "espeak-ng-data/rogue").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="phonemizer data invalid"):
        assets.bundle.verify_runtime(provider)


@pytest.mark.parametrize("provider", models.TTS_PROVIDERS)
@pytest.mark.parametrize("invalid", ["missing", "tampered", "symlink"])
def test_every_runtime_provider_requires_checksum_valid_asr(assets, provider, invalid) -> None:
    path = assets.bundle.stt_dir / "model.onnx"
    path.unlink()
    if invalid == "tampered":
        path.write_bytes(b"wrong")
    elif invalid == "symlink":
        original = assets.bundle.root / "original"
        original.write_bytes(assets.blob)
        path.symlink_to(original)
    with pytest.raises(RuntimeError, match="Speech model missing or invalid"):
        assets.bundle.verify_runtime(provider)


@pytest.mark.parametrize("provider", ["piper", "kokoro-int8", "kitten-micro"])
def test_selected_local_tts_symlink_is_rejected(assets, provider) -> None:
    path = assets.local(provider) / "model.onnx"
    path.unlink()
    original = assets.bundle.root / "original"
    original.write_bytes(assets.blob)
    path.symlink_to(original)
    with pytest.raises(RuntimeError, match="missing or invalid"):
        assets.bundle.verify_runtime(provider)


@pytest.mark.parametrize("provider", ["kokoro-int8", "kitten-micro"])
def test_runtime_honors_configured_local_tts_directory(assets, tmp_path, provider) -> None:
    custom = assets.local(provider, tmp_path / "custom")
    kwargs = {"kokoro_dir" if provider == "kokoro-int8" else "kitten_dir": custom}
    assets.bundle.verify_runtime(provider, **kwargs)
    with pytest.raises(RuntimeError, match="missing or invalid"):
        assets.bundle.verify_runtime(provider)  # The default location is absent.


def test_full_bundle_still_requires_asr_piper_kokoro_and_fixtures(assets, monkeypatch) -> None:
    assets.local("piper")
    assets.local("kokoro-int8")
    assets.bundle.fixture_dir.mkdir()
    (assets.bundle.fixture_dir / "test.wav").write_bytes(b"fixture")
    monkeypatch.setattr(
        models, "FIXTURE_FILES", {"test.wav": hashlib.sha256(b"fixture").hexdigest()}
    )
    assets.bundle.verify()
    (assets.bundle.fixture_dir / "test.wav").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="missing or invalid"):
        assets.bundle.verify()
    assets.bundle.verify_runtime("deepgram")  # Fixtures are not a runtime dependency.


@pytest.mark.parametrize("provider", ["deepgram", "speechify"])
def test_runtime_cli_verifies_without_preparing_any_bundle(assets, monkeypatch, capsys, provider):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_speech.py",
            "--directory",
            str(assets.bundle.root),
            "--verify-runtime",
            "--tts-provider",
            provider,
        ],
    )
    monkeypatch.setattr(prepare_speech, "prepare", lambda *_: pytest.fail("Unexpected preparation"))
    prepare_speech.main()
    assert "Verified runtime speech assets" in capsys.readouterr().out
    assert not assets.bundle.tts_dir.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--verify-runtime"],
        ["--tts-provider", "deepgram"],
        ["--verify-runtime", "--tts-provider", "deepgram", "--kitten-micro"],
        ["--verify-runtime", "--verify-only", "--tts-provider", "deepgram"],
        ["--verify-runtime", "--tts-provider", "unknown"],
    ],
)
def test_cli_refuses_ambiguous_or_unknown_runtime_selection(monkeypatch, arguments) -> None:
    monkeypatch.setattr(sys, "argv", ["prepare_speech.py", *arguments])
    with pytest.raises(SystemExit) as error:
        prepare_speech.main()
    assert error.value.code == 2


def test_runtime_refuses_unknown_provider_without_download(assets) -> None:
    with pytest.raises(ValueError, match="Unsupported trusted TTS provider"):
        assets.bundle.verify_runtime("tenant-chosen-model")
