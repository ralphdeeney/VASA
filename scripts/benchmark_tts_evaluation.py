"""Isolated sequential benchmark for CPU sherpa-onnx TTS candidates.

Each candidate is run in a fresh process. The harness never imports the
production worker and never runs two native models at once. ``--prepare``
downloads only the pinned release archives; ``--all`` runs candidates in
separate subprocesses and writes a JSON report plus playable WAV files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import shutil
import subprocess
import sys
import tarfile
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.request import Request, urlopen

import numpy as np

TEXT = "Hello. Your appointment is confirmed for tomorrow morning."
ARCHIVE_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
ARCHIVES: dict[str, dict[str, str]] = {
    "kokoro-fp32": {
        "archive": "kokoro-multi-lang-v1_1.tar.bz2",
        "license": (
            "Kokoro-82M model license is retained inside the archive; review before redistribution."
        ),
        "source": "https://huggingface.co/hexgrad/Kokoro-82M",
    },
    "kokoro-int8": {
        "archive": "kokoro-int8-multi-lang-v1_1.tar.bz2",
        "license": (
            "Kokoro-82M model license is retained inside the archive; review before redistribution."
        ),
        "source": "https://huggingface.co/hexgrad/Kokoro-82M",
    },
    "piper-libritts": {
        "archive": "vits-piper-en_US-libritts_r-medium.tar.bz2",
        "license": (
            "Piper model/data licensing is retained inside the archive; "
            "LibriTTS-R license is linked in the report."
        ),
        "source": "https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/libritts_r/medium",
    },
    "melotts": {
        "archive": "vits-melo-tts-zh_en.tar.bz2",
        "license": (
            "MeloTTS licensing is retained inside the archive; "
            "source project license is linked in the report."
        ),
        "source": "https://huggingface.co/myshell-ai/MeloTTS-Chinese",
    },
}


@dataclass(frozen=True)
class Candidate:
    name: str
    kind: str
    root: Path
    model: Path
    tokens: Path
    data_dir: Path | None = None
    lexicon: Path | None = None
    voices: Path | None = None
    lang: str = ""
    sid: int = 0
    sample_rate: int = 16000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    request = Request(url, headers={"User-Agent": "VASA-TTS-evaluation/1"})
    with urlopen(request, timeout=60) as response, temporary.open("xb") as target:
        if not response.geturl().startswith("https://"):
            raise RuntimeError("artifact redirect must remain HTTPS")
        shutil.copyfileobj(response, target, length=1024 * 1024)
    temporary.replace(path)
    return sha256(path)


def extract_safe(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root_name: str | None = None
    with tarfile.open(archive, "r:bz2") as source:
        members = source.getmembers()
        if len(members) > 2048:
            raise RuntimeError("candidate archive has too many members")
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise RuntimeError("unsafe candidate archive member")
            if root_name is None:
                root_name = name.parts[0]
            if name.parts[0] != root_name or not (member.isfile() or member.isdir()):
                raise RuntimeError("candidate archive has an invalid layout")
        source.extractall(destination, filter="data")
    if root_name is None:
        raise RuntimeError("empty candidate archive")
    return destination / root_name


def prepare(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "artifacts.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    manifest.setdefault("schema_version", 1)
    manifest.setdefault("artifacts", {})
    for name, spec in ARCHIVES.items():
        archive = root / "archives" / spec["archive"]
        observed = manifest["artifacts"].get(name, {}).get("sha256")
        if archive.exists():
            digest = sha256(archive)
            if observed and observed != digest:
                raise RuntimeError(f"pinned artifact changed: {name}")
        else:
            digest = download(ARCHIVE_BASE + spec["archive"], archive)
        extracted = root / "models" / name
        if not extracted.exists():
            actual_root = extract_safe(archive, root / "models")
            if actual_root != extracted:
                actual_root.rename(extracted)
        manifest["artifacts"][name] = {
            "archive": spec["archive"],
            "url": ARCHIVE_BASE + spec["archive"],
            "sha256": digest,
            "source": spec["source"],
            "license_note": spec["license"],
        }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def candidate(root: Path, name: str) -> Candidate:
    if name == "baseline":
        speech = Path(".local/speech/tts")
        return Candidate(
            name,
            "vits",
            speech,
            speech / "en_US-ljspeech-medium.onnx",
            speech / "tokens.txt",
            speech / "espeak-ng-data",
        )
    model_root = root / "models" / name
    if name.startswith("kokoro"):
        model_name = "model.int8.onnx" if name.endswith("int8") else "model.onnx"
        return Candidate(
            name,
            "kokoro",
            model_root,
            model_root / model_name,
            model_root / "tokens.txt",
            model_root / "espeak-ng-data",
            model_root / "lexicon-us-en.txt",
            model_root / "voices.bin",
            "en-us",
            0,
        )
    if name == "piper-libritts":
        return Candidate(
            name,
            "vits",
            model_root,
            model_root / "en_US-libritts_r-medium.onnx",
            model_root / "tokens.txt",
            model_root / "espeak-ng-data",
        )
    if name == "melotts":
        return Candidate(
            name,
            "vits",
            model_root,
            model_root / "model.onnx",
            model_root / "tokens.txt",
            None,
            model_root / "lexicon.txt",
            None,
            "",
            0,
            44100,
        )
    raise ValueError(f"unknown candidate: {name}")


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((pcm * 32767).astype("<i2").tobytes())


def run_one(root: Path, name: str, output: Path, iterations: int, threads: int) -> dict[str, Any]:
    import sherpa_onnx

    item = candidate(root, name)
    if not item.model.is_file() or not item.tokens.is_file():
        raise RuntimeError(f"candidate assets missing for {name}: {item.model}")
    model = sherpa_onnx.OfflineTtsModelConfig(num_threads=threads, provider="cpu")
    if item.kind == "kokoro":
        config = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(item.model),
            voices=str(item.voices),
            tokens=str(item.tokens),
            lexicon=str(item.lexicon or ""),
            data_dir=str(item.data_dir or ""),
            lang=item.lang,
        )
        model.kokoro = config
    else:
        config = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(item.model),
            tokens=str(item.tokens),
            data_dir=str(item.data_dir or ""),
            lexicon=str(item.lexicon or ""),
            noise_scale=0.0,
            noise_scale_w=0.0,
        )
        model.vits = config
    tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=1))
    samples: list[dict[str, float | int]] = []
    first_audio: np.ndarray | None = None
    start_rusage = resource.getrusage(resource.RUSAGE_SELF)
    for iteration in range(iterations):
        started = time.perf_counter()
        cpu_started = time.process_time()
        audio = tts.generate(TEXT, sid=item.sid, speed=1.0)
        elapsed = time.perf_counter() - started
        cpu_seconds = time.process_time() - cpu_started
        data = np.asarray(audio.samples, dtype=np.float32)
        rate = int(audio.sample_rate)
        if data.ndim != 1 or not data.size or not np.isfinite(data).all():
            raise RuntimeError(f"invalid audio from {name}")
        if first_audio is None:
            first_audio = data
        duration = len(data) / rate
        samples.append(
            {
                "iteration": iteration + 1,
                "first_audio_seconds": elapsed,
                "processing_seconds": elapsed,
                "cpu_seconds": cpu_seconds,
                "audio_duration_seconds": duration,
                "real_time_factor": elapsed / duration,
            }
        )
    end_rusage = resource.getrusage(resource.RUSAGE_SELF)
    write_wav(output, first_audio, int(audio.sample_rate))
    return {
        "candidate": name,
        "text": TEXT,
        "sample_rate": int(audio.sample_rate),
        "samples": samples,
        "first_audio_seconds": summarize([float(x["first_audio_seconds"]) for x in samples]),
        "real_time_factor": summarize([float(x["real_time_factor"]) for x in samples]),
        "cpu_seconds": summarize([float(x["cpu_seconds"]) for x in samples]),
        "peak_rss_kib": int(end_rusage.ru_maxrss),
        "user_cpu_seconds": end_rusage.ru_utime - start_rusage.ru_utime,
        "system_cpu_seconds": end_rusage.ru_stime - start_rusage.ru_stime,
        "model_sha256": sha256(item.model),
    }


def summarize(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "minimum": min(values),
        "maximum": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".local/tts-evaluation"))
    parser.add_argument("--output", type=Path, default=Path("docs/tts-evaluation/report.json"))
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--candidate", choices=["baseline", *ARCHIVES], default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.prepare or args.all:
        manifest = prepare(args.root)
    else:
        manifest = (
            json.loads((args.root / "artifacts.json").read_text())
            if args.root.joinpath("artifacts.json").exists()
            else {"artifacts": {}}
        )
    if args.prepare and not args.all and args.candidate is None:
        print(json.dumps(manifest, indent=2))
        return
    if args.all:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {
            "schema_version": 1,
            "measured_at_utc": datetime.now(UTC).isoformat(),
            "text": TEXT,
            "policy": (
                "Candidates run sequentially in fresh subprocesses; "
                "no competing models run together."
            ),
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "threads": args.threads,
            },
            "artifacts": manifest,
            "results": [],
        }
        for name in ["baseline", *ARCHIVES]:
            result_path = args.output.parent / f"{name}.json"
            command = [
                sys.executable,
                __file__,
                "--root",
                str(args.root),
                "--output",
                str(result_path),
                "--candidate",
                name,
                "--iterations",
                str(args.iterations),
                "--threads",
                str(args.threads),
            ]
            subprocess.run(command, check=True)
            report["results"].append(json.loads(result_path.read_text()))
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        return
    if args.candidate is None:
        parser.error("use --prepare, --candidate or --all")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = run_one(
        args.root,
        args.candidate,
        args.output.parent / f"{args.candidate}.wav",
        args.iterations,
        args.threads,
    )
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
