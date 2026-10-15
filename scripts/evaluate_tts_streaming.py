"""Evaluation-only TTS streaming on a shared two-CPU affinity; production untouched."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import resource
import subprocess
import sys
import threading
import time
import wave
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import resample_poly

from vasa.contracts.models import AudioFrame
from vasa.speech.recognition import SherpaSTT

CASES = {
    "short": "Certainly, I can help.",
    "sentence": "Your appointment is confirmed for tomorrow morning at ten o'clock.",
    "long": (
        "I can help you arrange an appointment. "
        "Please tell me which day works best for you "
        "and whether you prefer the morning or afternoon. "
        "Once I have checked the available times, "
        "I will read the details back so you can confirm them. "
        "If your plans change, you can contact our team to reschedule."
    ),
    "legacy": "Hello. Your appointment is confirmed for tomorrow morning.",
}
CANDIDATES = ["official-v10", "official-v11", "sherpa-kokoro", "piper"]
ROOT = Path(".local/tts-evaluation/models")
OFFICIAL = Path(".local/kokoro-streaming-official")


def pcm16(samples: Any, rate: int) -> bytes:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
        raise ValueError("invalid native waveform")
    if rate != 16000:
        divisor = math.gcd(rate, 16000)
        audio = resample_poly(audio, 16000 // divisor, rate // divisor)
    return np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes()


class EvaluationTTS:
    """TTSProvider contract, emitting 60ms frames after native segment completion."""

    def __init__(self, name: str, threads: int = 2) -> None:
        self.name = name
        self.events: list[dict[str, Any]] = []
        self.started = 0.0
        self.policy = "sentence"
        if name.startswith("official"):
            import torch
            from kokoro import KModel, KPipeline

            torch.set_num_threads(threads)
            torch.set_num_interop_threads(1)
            version = "v10" if name.endswith("v10") else "v11"
            repo = "hexgrad/Kokoro-82M" + ("-v1.1-zh" if version == "v11" else "")
            model = (
                KModel(
                    repo_id=repo,
                    config=str(OFFICIAL / version / "config.json"),
                    model=str(OFFICIAL / version / "model.pth"),
                )
                .to("cpu")
                .eval()
            )
            self.model = KPipeline(lang_code="a", repo_id=repo, model=model, device="cpu")
            self.voice = str(OFFICIAL / version / "voice.pt")
            self.model.load_voice(self.voice)
        else:
            import sherpa_onnx as native

            config = native.OfflineTtsModelConfig(num_threads=threads, provider="cpu")
            if name == "sherpa-kokoro":
                directory = ROOT / "kokoro-fp32"
                config.kokoro = native.OfflineTtsKokoroModelConfig(
                    model=str(directory / "model.onnx"),
                    voices=str(directory / "voices.bin"),
                    tokens=str(directory / "tokens.txt"),
                    data_dir=str(directory / "espeak-ng-data"),
                    lexicon=str(directory / "lexicon-us-en.txt"),
                    lang="en-us",
                )
            else:
                directory = ROOT / "piper-libritts"
                config.vits = native.OfflineTtsVitsModelConfig(
                    model=str(directory / "en_US-libritts_r-medium.onnx"),
                    tokens=str(directory / "tokens.txt"),
                    data_dir=str(directory / "espeak-ng-data"),
                    noise_scale=0.0,
                    noise_scale_w=0.0,
                )
            self.model = native.OfflineTts(native.OfflineTtsConfig(model=config))

    def generate(self, text: str) -> bytes:
        if self.name.startswith("official"):
            outputs = list(self.model(text, voice=self.voice, speed=1, split_pattern=None))
            return b"".join(pcm16(item.audio.numpy(), 24000) for item in outputs)
        result = self.model.generate(text, sid=0, speed=1.0)
        return pcm16(result.samples, result.sample_rate)

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        sequence = 0
        chunks = [text] if self.policy == "whole" else re.split(r"(?<=[.!?])\s+", text)
        for index, chunk in enumerate(chunks):
            start = time.perf_counter()
            cpu = time.process_time()
            pcm = await asyncio.to_thread(self.generate, chunk)
            pcm = pcm.ljust(((len(pcm) + 1919) // 1920) * 1920, b"\0")
            ready = time.perf_counter()
            self.events.append(
                {
                    "index": index,
                    "text": chunk,
                    "start_seconds": start - self.started,
                    "ready_seconds": ready - self.started,
                    "generation_seconds": ready - start,
                    "process_cpu_seconds": time.process_time() - cpu,
                    "audio_seconds": len(pcm) / 32000,
                    "pcm": pcm,
                }
            )
            for offset in range(0, len(pcm), 1920):
                yield AudioFrame(
                    pcm[offset : offset + 1920].ljust(1920, b"\0"),
                    16000,
                    sequence,
                    time.monotonic_ns(),
                )
                sequence += 1


class STTCompetition:
    """Actual shared speech model processing paced pinned caller frames on the same CPUs."""

    def __init__(self, threads: int = 2) -> None:
        self.threads = threads
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.results: list[dict[str, Any]] = []
        self.thread = threading.Thread(target=self.run, name="eval-stt")

    def run(self) -> None:
        asyncio.run(self.loop())

    async def loop(self) -> None:
        provider = SherpaSTT(Path(".local/speech/asr"), num_threads=self.threads)
        with wave.open(".local/speech/fixtures/0.wav") as wav:
            pcm = wav.readframes(wav.getnframes())
            assert wav.getframerate() == 16000
        self.ready.set()
        try:
            while not self.stop.is_set():

                async def frames() -> AsyncIterator[AudioFrame]:
                    for offset in range(0, len(pcm), 1920):
                        if self.stop.is_set():
                            break
                        yield AudioFrame(
                            pcm[offset : offset + 1920].ljust(1920, b"\0"),
                            16000,
                            offset // 1920,
                            time.monotonic_ns(),
                        )
                        await asyncio.sleep(0.06)

                start = time.perf_counter()
                updates = [text async for text in provider.transcribe(frames())]
                self.results.append(
                    {
                        "wall_seconds": time.perf_counter() - start,
                        "text": updates[-1] if updates else "",
                    }
                )
        finally:
            await provider.aclose()


async def measure(provider: EvaluationTTS, text: str, policy: str) -> dict[str, Any]:
    provider.policy = policy
    provider.events = []
    provider.started = time.perf_counter()
    first = None
    count = 0
    async for frame in provider.synthesize(text):
        assert frame.sample_rate == 16000 and frame.sequence == count and len(frame.pcm) == 1920
        if first is None:
            first = time.perf_counter() - provider.started
        count += 1
    elapsed = time.perf_counter() - provider.started
    events = provider.events
    playback_end = 0.0
    gaps: list[float] = []
    boundaries: list[dict[str, float]] = []
    for index, event in enumerate(events):
        arrival = event["ready_seconds"]
        gap = max(0.0, arrival - playback_end) if index else 0.0
        gaps.append(gap)
        playback_end = max(playback_end, arrival) + event["audio_seconds"]
        if index:
            left = np.frombuffer(events[index - 1]["pcm"], dtype="<i2") / 32768
            right = np.frombuffer(event["pcm"], dtype="<i2") / 32768
            boundaries.append(
                {
                    "sample_step": float(abs(left[-1] - right[0])),
                    "left_100ms_rms": float(np.sqrt(np.mean(left[-1600:] ** 2))),
                    "right_100ms_rms": float(np.sqrt(np.mean(right[:1600] ** 2))),
                    "playback_underrun_seconds": gap,
                }
            )
    scheduled = playback_pcm(events)
    pcm = b"".join(event.pop("pcm") for event in events)
    duration = len(pcm) / 32000
    return {
        "first_playable_seconds": first,
        "complete_seconds": elapsed,
        "audio_seconds": duration,
        "rtf": elapsed / duration,
        "chunks": events,
        "boundaries": boundaries,
        "total_playback_underrun_seconds": sum(gaps),
        "pcm": pcm,
        "scheduled_pcm": scheduled,
    }


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)


def playback_pcm(events: list[dict[str, Any]]) -> bytes:
    """Render measured availability gaps into a listening sample after first audio."""
    result = []
    playback_end = 0.0
    for index, event in enumerate(events):
        ready = event["ready_seconds"]
        if index and ready > playback_end:
            result.append(b"\0\0" * round((ready - playback_end) * 16000))
        result.append(event["pcm"])
        playback_end = max(playback_end, ready) + event["audio_seconds"]
    return b"".join(result)


async def child(args: argparse.Namespace) -> None:
    os.sched_setaffinity(0, set(args.cpus))
    start = time.perf_counter()
    provider = EvaluationTTS(args.candidate, args.threads)
    load = time.perf_counter() - start
    competition = STTCompetition(args.threads) if args.contention else None
    if competition:
        competition.thread.start()
        if not competition.ready.wait(60):
            raise RuntimeError("STT initialization failed")
    # All candidates receive one unmeasured warmup after both models initialize.
    await measure(provider, "Hello, how can I help you today?", "sentence")
    rows = []
    try:
        for case in args.cases:
            text = CASES[case]
            for policy in args.policies:
                for iteration in range(args.iterations):
                    cpu_start = time.process_time()
                    result = await measure(provider, text, policy)
                    result["cpu_seconds"] = time.process_time() - cpu_start
                    result.update(case=case, text=text, policy=policy, iteration=iteration)
                    pcm = result.pop("pcm")
                    scheduled = result.pop("scheduled_pcm")
                    if iteration == 0:
                        mode = "stt" if args.contention else "solo"
                        filename = f"{args.candidate}-{mode}-{case}-{policy}.wav"
                        write_wav(args.output / filename, pcm)
                        write_wav(
                            args.output / filename.replace(".wav", "-playback.wav"), scheduled
                        )
                        result["wav"] = filename
                    rows.append(result)
    finally:
        if competition:
            competition.stop.set()
            await asyncio.to_thread(competition.thread.join, 30)
            if competition.thread.is_alive():
                raise RuntimeError("STT worker failed to drain")
    stats = resource.getrusage(resource.RUSAGE_SELF)
    report = {
        "candidate": args.candidate,
        "threads_per_model": args.threads,
        "contention": args.contention,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "load_seconds": load,
        "peak_rss_kib": stats.ru_maxrss,
        "rows": rows,
        "stt_utterances": competition.results if competition else [],
    }
    path = args.output / f"{args.candidate}-{'stt' if args.contention else 'solo'}.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=CANDIDATES)
    parser.add_argument("--contention", action="store_true")
    parser.add_argument("--cpus", type=int, nargs=2, default=[0, 1])
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--threads", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--cases", nargs="+", choices=list(CASES), default=["short", "sentence", "long"]
    )
    parser.add_argument(
        "--policies", nargs="+", choices=["whole", "sentence"], default=["whole", "sentence"]
    )
    parser.add_argument("--output", type=Path, default=Path("docs/tts-evaluation/streaming"))
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 10 or len(set(args.cpus)) != 2:
        parser.error("Use 1–10 iterations and two distinct CPUs")
    if not set(args.cpus) <= os.sched_getaffinity(0):
        parser.error("Selected CPUs are unavailable")
    manifest = Path("docs/tts-evaluation/streaming/artifacts.json")
    for artifact in json.loads(manifest.read_text())["files"]:
        path = Path(artifact["file"])
        if path.is_symlink():
            raise RuntimeError(f"Unexpected symlink: {path}")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != artifact["sha256"]:
                raise RuntimeError(f"Pinned evaluation artifact changed: {path}")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.candidate:
        asyncio.run(child(args))
        return
    reports = []
    for candidate in CANDIDATES:
        for contention in (False, True):
            command = [
                sys.executable,
                __file__,
                "--candidate",
                candidate,
                "--output",
                str(args.output),
                "--iterations",
                str(args.iterations),
                "--threads",
                str(args.threads),
                "--cpus",
                *map(str, args.cpus),
                "--cases",
                *args.cases,
                "--policies",
                *args.policies,
            ]
            if contention:
                command.append("--contention")
            print(f"Measuring {candidate}, STT={contention}", flush=True)
            subprocess.run(command, check=True, timeout=600)
            path = args.output / f"{candidate}-{'stt' if contention else 'solo'}.json"
            reports.append(json.loads(path.read_text()))
    manifest = {
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "host": platform.platform(),
        "python": platform.python_version(),
        "scope": "Cloud two-core affinity approximation, not the production VPS",
        "threads_per_model": args.threads,
        "reports": reports,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("torch", "kokoro", "misaki", "sherpa-onnx", "numpy", "scipy")
        },
    }
    (args.output / "measurements.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
