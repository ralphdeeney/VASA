"""Sequential, opt-in TTS benchmark. Never deploys or changes running services."""

import argparse
import asyncio
import gc
import hashlib
import importlib.metadata
import json
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
from pathlib import Path
from typing import Any

import numpy as np

from scripts.evaluate_tts_streaming import CASES, EvaluationTTS
from scripts.prepare_kokoro_int8 import verify_piper
from vasa.contracts.models import AudioFrame
from vasa.speech.models import NativeWorker
from vasa.speech.recognition import SherpaSTT


def validate_scope(scope: str, cwd: Path, uid: int, isolated: bool, condition: str) -> None:
    if scope == "vps":
        resolved = cwd.resolve()
        if uid == 0 or not resolved.is_relative_to(Path("/opt/vasa")):
            raise ValueError("VPS benchmark requires the non-root project owner under /opt/vasa")
        if resolved.stat().st_uid != uid:
            raise ValueError("VPS checkout must be owned by the executing project user")
        if condition in {"A", "B"} and not isolated:
            raise ValueError("A/B require --isolated-workload operator attestation")


def segments(text: str) -> list[str]:
    # The whole response is available at t=0: no simulated LLM generation delay.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    result = []
    for sentence in sentences:
        # Avoid tiny clauses; split only substantial responses at natural boundaries.
        parts = re.split(r"(?<=[,;:])\s+", sentence) if len(sentence) > 160 else [sentence]
        for part in parts:
            while len(part) > 200:
                boundary = part.rfind(" ", 0, 201)
                boundary = boundary if boundary > 0 else 200
                result.append(part[:boundary])
                part = part[boundary:].lstrip()
            if part:
                result.append(part)
    return result


def word_error_rate(reference: str, hypothesis: str) -> float:
    a, b = reference.upper().split(), hypothesis.upper().split()
    previous = list(range(len(b) + 1))
    for index, word in enumerate(a, 1):
        current = [index]
        for offset, other in enumerate(b, 1):
            current.append(
                min(current[-1] + 1, previous[offset] + 1, previous[offset - 1] + (word != other))
            )
        previous = current
    return previous[-1] / max(1, len(a))


def container_snapshot(required: bool = False) -> dict[str, Any]:
    try:
        listing = subprocess.run(
            [
                "docker",
                "ps",
                "--format",
                '{"ID":{{json .ID}},"Names":{{json .Names}},'
                '"Image":{{json .Image}},"Status":{{json .Status}}}',
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        containers = [json.loads(line) for line in listing.stdout.splitlines() if line]
        if required and not containers:
            raise RuntimeError("Condition C requires actual running normal-workload containers")
        stats = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return {
            "containers": containers,
            "stats": [json.loads(x) for x in stats.stdout.splitlines()],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        if required:
            raise RuntimeError(
                "Condition C requires readable Docker ps/stats; no simulation"
            ) from exc
        return {"available": False, "reason": type(exc).__name__}


def system_information() -> dict[str, Any]:
    cpuinfo = Path("/proc/cpuinfo").read_text()
    quotas = {}
    for name in ("cpu.max", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        quotas[name] = path.read_text().strip() if path.exists() else None
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_model": next(
            (
                x.split(":", 1)[1].strip()
                for x in cpuinfo.splitlines()
                if x.startswith("model name")
            ),
            "unknown",
        ),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "cgroup_limits": quotas,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("sherpa-onnx", "sherpa-onnx-core", "numpy", "scipy")
        },
    }


class RSSSampler:
    def __init__(self) -> None:
        self.samples: list[dict[str, float]] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        start = time.perf_counter()
        while not self.stop.is_set():
            line = next(
                x
                for x in Path("/proc/self/status").read_text().splitlines()
                if x.startswith("VmRSS:")
            )
            self.samples.append(
                {"seconds": time.perf_counter() - start, "rss_mib": int(line.split()[1]) / 1024}
            )
            self.stop.wait(0.05)


def current_rss_mib() -> float:
    line = next(
        line
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith("VmRSS:")
    )
    return int(line.split()[1]) / 1024


class STTLoad:
    """Real paced native STT; only fully completed fixture runs count as evidence."""

    def __init__(self, model: Path, fixture: Path) -> None:
        self.model, self.fixture = model, fixture
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.results: list[dict[str, Any]] = []
        self.error: str | None = None
        self.thread = threading.Thread(target=self.run)

    def run(self) -> None:
        try:
            asyncio.run(self.loop())
        except Exception as exc:
            self.error = repr(exc)
            self.ready.set()

    async def loop(self) -> None:
        provider = SherpaSTT(self.model, num_threads=2)
        with wave.open(str(self.fixture / "0.wav")) as source:
            if source.getframerate() != 16000 or source.getnchannels() != 1:
                raise ValueError("STT fixture must be mono 16kHz")
            pcm = source.readframes(source.getnframes())
        reference = (self.fixture / "trans.txt").read_text().splitlines()[0].split(" ", 1)[1]
        self.ready.set()
        try:
            while not self.stop.is_set():
                start = time.perf_counter()
                delays: list[float] = []
                consumed = 0

                async def frames(
                    origin: float = start, processing_delays: list[float] = delays
                ) -> AsyncIterator[AudioFrame]:
                    nonlocal consumed
                    for offset in range(0, len(pcm), 1920):
                        if self.stop.is_set():
                            return
                        deadline = origin + offset / 32000
                        await asyncio.sleep(max(0, deadline - time.perf_counter()))
                        yield AudioFrame(
                            pcm[offset : offset + 1920].ljust(1920, b"\0"),
                            16000,
                            offset // 1920,
                            time.monotonic_ns(),
                        )
                        consumed = min(offset + 1920, len(pcm))
                        processing_delays.append(max(0, time.perf_counter() - deadline - 0.06))

                texts = [text async for text in provider.transcribe(frames())]
                complete = consumed == len(pcm)
                self.results.append(
                    {
                        "completed": complete,
                        "wall_seconds": time.perf_counter() - start,
                        "text": texts[-1] if texts else "",
                        "reference": reference,
                        "word_error_rate": word_error_rate(reference, texts[-1] if texts else "")
                        if complete
                        else None,
                        "max_frame_processing_deadline_overrun_seconds": max(delays, default=0),
                        "deadline_misses": sum(value > 0.001 for value in delays),
                    }
                )
        finally:
            await provider.aclose()


async def response(provider: Any, text: str) -> dict[str, Any]:
    start, cpu = time.perf_counter(), time.process_time()
    rss_before = current_rss_mib()
    first = None
    audio = bytearray()
    playback = bytearray()
    chunks = []
    compute = 0.0
    gaps: list[float] = []
    playback_end = None
    for chunk in segments(text):
        iterator = provider.synthesize(chunk).__aiter__()
        chunk_start = time.perf_counter()
        chunk_pcm = bytearray()
        ready = None
        generation_wait = 0.0
        while True:
            wait_start = time.perf_counter()
            try:
                frame = await anext(iterator)
            except StopAsyncIteration:
                generation_wait += time.perf_counter() - wait_start
                break
            generation_wait += time.perf_counter() - wait_start
            now = time.perf_counter()
            if frame.sample_rate != 16000 or frame.channels != 1 or len(frame.pcm) != 1920:
                raise ValueError("Provider violated 16kHz mono PCM16 60ms frame contract")
            if first is None:
                first = now - start
            if ready is None:
                ready = now - start
            if playback_end is not None and now > playback_end:
                gap_seconds = now - playback_end
                gaps.append(gap_seconds)
                playback.extend(b"\0\0" * round(gap_seconds * 16000))
            playback.extend(frame.pcm)
            chunk_pcm.extend(frame.pcm)
            playback_end = now + 0.06
            await asyncio.sleep(0.06)
        compute += generation_wait
        gap = max(0, (ready or 0) - chunks[-1]["playback_end_seconds"]) if chunks else 0
        chunks.append(
            {
                "text": chunk,
                "start_seconds": chunk_start - start,
                "first_frame_seconds": ready,
                "compute_wait_seconds": generation_wait,
                "complete_seconds": time.perf_counter() - start,
                "audio_seconds": len(chunk_pcm) / 32000,
                "starvation_before_seconds": gap,
                "playback_end_seconds": (playback_end or start) - start,
            }
        )
        audio.extend(chunk_pcm)
    wall = time.perf_counter() - start
    cpu_seconds = time.process_time() - cpu
    duration = len(audio) / 32000
    return {
        "text": text,
        "first_playable_seconds": first,
        "synthesis_compute_seconds": compute,
        "paced_response_wall_seconds": wall,
        "real_time_factor": compute / duration,
        "audio_seconds": duration,
        "process_cpu_seconds": cpu_seconds,
        "process_cpu_utilization_percent": 100 * cpu_seconds / wall,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "rss_before_mib": rss_before,
        "rss_after_mib": current_rss_mib(),
        "chunks": chunks,
        "max_chunk_starvation_seconds": max(
            (x["starvation_before_seconds"] for x in chunks), default=0
        ),
        "max_frame_starvation_seconds": max(gaps, default=0),
        "total_frame_starvation_seconds": sum(gaps),
        "pcm": bytes(audio),
        "playback_pcm": bytes(playback),
    }


async def cancellation(provider: Any, phase: str) -> dict[str, Any]:
    started = asyncio.Event()
    first = asyncio.Event()
    seen = 0

    async def consume() -> None:
        nonlocal seen
        started.set()
        # Mirror the runtime's incremental calls for both implementations;
        # otherwise Piper would receive a whole paragraph but Kokoro a segment.
        for chunk in segments(CASES["long"]):
            async for _ in provider.synthesize(chunk):
                seen += 1
                first.set()
                await asyncio.sleep(0.06)

    task = asyncio.create_task(consume())
    await started.wait()
    if phase == "playback":
        await asyncio.wait_for(first.wait(), timeout=60)
    else:
        await asyncio.sleep(0.01)
    when, before = time.perf_counter(), seen
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=60)
    except asyncio.CancelledError:
        pass
    stopped = time.perf_counter()
    # Provider cleanup drains any uncancellable native work; separate from consumer stop.
    close = getattr(provider, "aclose", None)
    if close is not None:
        await asyncio.wait_for(close(), timeout=60)
    return {
        "phase": phase,
        "consumer_cancellation_seconds": stopped - when,
        "native_cleanup_drain_seconds": time.perf_counter() - stopped,
        "frames_after_cancel": seen - before,
        "frames_before_cancel": before,
    }


class BenchmarkPiper(EvaluationTTS):
    """Existing native Piper generation with owned/drained work and no PCM event retention."""

    def __init__(self) -> None:
        verify_piper(Path(".local/tts-evaluation/models/piper-libritts"))
        super().__init__("piper", threads=1)
        self.worker = NativeWorker("benchmark-piper")

    async def synthesize(self, text: str) -> AsyncIterator[AudioFrame]:
        pcm = await self.worker.run(lambda: self.generate(text))
        for offset in range(0, len(pcm), 1920):
            yield AudioFrame(
                pcm[offset : offset + 1920].ljust(1920, b"\0"),
                16000,
                offset // 1920,
                time.monotonic_ns(),
            )

    async def aclose(self) -> None:
        await self.worker.aclose()
        self.model = None


def provider_for(candidate: str, model: Path) -> Any:
    if candidate == "kokoro-int8":
        from vasa.speech.kokoro import KokoroInt8TTS

        return KokoroInt8TTS(model, num_threads=1)
    return BenchmarkPiper()


def save_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(pcm)


async def child(args: argparse.Namespace) -> dict[str, Any]:
    sampler = RSSSampler()
    sampler.thread.start()
    load = time.perf_counter()
    provider = provider_for(args.candidate, args.model)
    load_seconds = time.perf_counter() - load
    contender = None
    baseline: list[dict[str, Any]] = []
    if args.condition != "A":
        baseline_load = STTLoad(args.stt_model, args.fixtures)
        baseline_load.thread.start()
        if not await asyncio.to_thread(baseline_load.ready.wait, 60) or baseline_load.error:
            raise RuntimeError(f"STT baseline failed: {baseline_load.error}")
        deadline = time.perf_counter() + 60
        while not any(x["completed"] for x in baseline_load.results):
            if time.perf_counter() > deadline or baseline_load.error:
                raise RuntimeError("No complete standalone STT baseline fixture within 60 seconds")
            await asyncio.sleep(0.1)
        baseline_load.stop.set()
        await asyncio.to_thread(baseline_load.thread.join, 60)
        baseline = baseline_load.results
        contender = STTLoad(args.stt_model, args.fixtures)
        contender.thread.start()
        if not await asyncio.to_thread(contender.ready.wait, 60) or contender.error:
            raise RuntimeError(f"STT contender failed: {contender.error}")
    rows = []
    containers_before = container_snapshot(required=args.condition == "C")
    try:
        for iteration in range(args.iterations):
            for case in ("short", "sentence", "long"):
                row = await response(provider, CASES[case])
                for name, suffix in (("pcm", ""), ("playback_pcm", "-playback")):
                    data = row.pop(name)
                    filename = f"{args.candidate}-{args.condition}-{case}-{iteration}{suffix}.wav"
                    save_wav(args.output / filename, data)
                    row[name + "_file"] = filename
                row.update(
                    {
                        "case": case,
                        "iteration": iteration,
                        "first_worker_response": iteration == 0 and case == "short",
                    }
                )
                rows.append(row)
        cancellations = []
        close = getattr(provider, "aclose", None)
        if close:
            await close()
        provider = None
        gc.collect()
        for phase in ("before_first_audio", "playback"):
            # Separate once-loaded instance per cancellation trial, never per response/call.
            trial = provider_for(args.candidate, args.model)
            cancellations.append(await cancellation(trial, phase))
            del trial
            gc.collect()
    finally:
        if contender:
            contender.stop.set()
            await asyncio.to_thread(contender.thread.join, 60)
            if contender.thread.is_alive() or contender.error:
                raise RuntimeError(f"STT cleanup failed: {contender.error}")
        if provider is not None:
            close = getattr(provider, "aclose", None)
            if close:
                await close()
        sampler.stop.set()
        await asyncio.to_thread(sampler.thread.join, 5)
    model_path = (
        args.model
        if args.candidate == "kokoro-int8"
        else Path(".local/tts-evaluation/models/piper-libritts")
    )
    files = {
        str(path.relative_to(model_path)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in model_path.rglob("*")
        if path.is_file() and path.suffix != ".wav"
    }
    return {
        "scope": args.scope,
        "actual_vps": args.scope == "vps",
        "candidate": args.candidate,
        "condition": args.condition,
        "threads_tts": 1,
        "threads_stt": 2,
        "model_load_seconds": load_seconds,
        "model_files_sha256": files,
        "rows": rows,
        "cancellation": cancellations,
        "rss_samples": sampler.samples,
        "stt_baseline": baseline,
        "stt_contender": contender.results if contender else [],
        "stt_degradation_note": "Compare completed runs only; one fixture is limited evidence",
        "containers_before": containers_before,
        "containers_after": container_snapshot(required=args.condition == "C"),
        "system": system_information(),
        "timing_policy": "All text available at t=0; sequential chunks, paced 60ms playback; "
        "compute time excludes playback sleeps; first response is cold",
    }


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    output = {key: report[key] for key in ("scope", "candidate", "condition", "model_load_seconds")}
    output["cases"] = {}
    for case in ("short", "sentence", "long"):
        rows = [row for row in report["rows"] if row["case"] == case]
        values = sorted(row["first_playable_seconds"] for row in rows)
        output["cases"][case] = {
            "first_playable_max_seconds": max(values),
            "first_playable_p50_seconds": float(np.percentile(values, 50)),
            "first_playable_p95_seconds": float(np.percentile(values, 95)),
            "first_playable_samples_seconds": values,
            "rtf_max": max(row["real_time_factor"] for row in rows),
            "cpu_seconds_mean": sum(row["process_cpu_seconds"] for row in rows) / len(rows),
            "peak_rss_mib": max(row["peak_rss_mib"] for row in rows),
            "max_chunk_starvation_seconds": max(
                row["max_chunk_starvation_seconds"] for row in rows
            ),
        }
    output["cancellation"] = report["cancellation"]
    output["selection"] = "Not automatic: actual VPS results and human voice review required"
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("cloud-smoke", "vps"), required=True)
    parser.add_argument("--condition", choices=("A", "B", "C"), required=True)
    parser.add_argument("--candidate", choices=("kokoro-int8", "piper"), required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--model", type=Path, default=Path(".local/tts-evaluation/models/kokoro-int8")
    )
    parser.add_argument("--stt-model", type=Path, default=Path(".local/speech/asr"))
    parser.add_argument("--fixtures", type=Path, default=Path(".local/speech/fixtures"))
    parser.add_argument("--cpus", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--isolated-workload", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    validate_scope(args.scope, Path.cwd(), os.getuid(), args.isolated_workload, args.condition)
    if not 1 <= args.iterations <= 10:
        parser.error("--iterations must be 1..10")
    if args.scope == "cloud-smoke" and "cloud-smoke" not in args.output.parts:
        parser.error("Cloud smoke output must have a cloud-smoke path component")
    os.sched_setaffinity(0, set(args.cpus))
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.child:
        subprocess.run(
            [sys.executable, __file__, *sys.argv[1:], "--child"], timeout=1800, check=True
        )
        return
    report = asyncio.run(child(args))
    (args.output / "measurements.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output / "summary.json").write_text(json.dumps(summarize(report), indent=2) + "\n")


if __name__ == "__main__":
    main()
