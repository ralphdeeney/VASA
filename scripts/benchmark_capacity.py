"""Native CPU synthetic concurrency evidence, never live phone/provider capacity."""

import argparse
import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.benchmark_speech import load_fixture, percentile_summary
from vasa.contracts.models import AudioFrame
from vasa.contracts.providers import STTProvider, TTSProvider
from vasa.speech import KokoroInt8TTS, SherpaSTT, SpeechModels
from vasa.speech.vad import StreamingVAD

POLICY: dict[str, int | float] = {
    "concurrency": 10,
    "rounds": 3,
    "turn_deadline_seconds": 120,
    "cancellation_deadline_seconds": 10,
    "cleanup_deadline_seconds": 10,
    "frame_seconds": 0.06,
}


def rss_kib() -> int:
    """Current Linux process RSS, excluding other services and shared accounting."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("Capacity benchmark requires Linux VmRSS accounting")


def validate_frame(frame: AudioFrame) -> None:
    if frame.channels != 1 or frame.sample_rate != 16000 or len(frame.pcm) != 1920:
        raise RuntimeError("Synthetic capacity run received invalid PCM framing")


async def run_call(
    stt: STTProvider, tts: TTSProvider, pcm: bytes, *, frame_seconds: float = 0.06
) -> dict[str, Any]:
    vad = StreamingVAD()
    started = time.perf_counter()
    fixture_end = started
    endpoint_times: list[float] = []
    inbound = 0

    async def source() -> AsyncIterator[AudioFrame]:
        nonlocal fixture_end, inbound
        padded = pcm + bytes(1920 * 10)
        for offset in range(0, len(padded), 1920):
            target = started + (offset // 1920) * frame_seconds
            await asyncio.sleep(max(0, target - time.perf_counter()))
            frame = AudioFrame(
                padded[offset : offset + 1920].ljust(1920, b"\0"),
                16000,
                inbound,
                time.monotonic_ns(),
            )
            validate_frame(frame)
            inbound += 1
            result = vad.process(frame)
            if offset < len(pcm):
                fixture_end = time.perf_counter()
            if result.ended:
                endpoint_times.append(time.perf_counter())
            yield frame
        vad.finish()

    updates = [text async for text in stt.transcribe(source())]
    finalized = time.perf_counter()
    if not updates or not updates[-1].strip():
        raise RuntimeError("Native concurrent recognition returned empty text")
    tts_started = time.perf_counter()
    first_audio: float | None = None
    output_count = 0
    async for frame in tts.synthesize("Hello. Your appointment is confirmed."):
        validate_frame(frame)
        now = time.perf_counter()
        if first_audio is None:
            first_audio = now
        output_count += 1
        await asyncio.sleep(frame_seconds)
    if first_audio is None:
        raise RuntimeError("Native concurrent synthesis returned no frames")
    return {
        "inbound_frames": inbound,
        "outbound_frames": output_count,
        "stt_finalization_seconds": finalized - fixture_end,
        "tts_first_audio_seconds": first_audio - tts_started,
        "synthetic_fixture_end_to_first_audio_seconds": first_audio - fixture_end,
        "elapsed_seconds": time.perf_counter() - started,
        "vad_endpoints": len(endpoint_times),
        "vad_final_endpoint_after_fixture_seconds": (
            endpoint_times[-1] - fixture_end if endpoint_times else None
        ),
    }


async def benchmark(directory: Path, rounds: int = 3) -> dict[str, Any]:
    if not 3 <= rounds <= 10:
        raise ValueError("Use three to ten repeated ten-call rounds")
    models = SpeechModels(directory)
    models.verify()
    pcm, _ = load_fixture(models.fixture_dir / "0.wav")
    threads_before = {t.ident for t in threading.enumerate()}
    tasks_before = set(asyncio.all_tasks())
    rss_before = rss_kib()
    stt = SherpaSTT(models.stt_dir, num_threads=1, max_streams=10)
    tts = KokoroInt8TTS(models.kokoro_dir, num_threads=1)
    await tts.warmup()
    lag: list[float] = []
    rss_samples: list[int] = [rss_before, rss_kib()]
    stopping = asyncio.Event()

    async def monitor() -> None:
        while not stopping.is_set():
            before = time.perf_counter()
            await asyncio.sleep(0.02)
            lag.append(max(0, time.perf_counter() - before - 0.02))
            rss_samples.append(rss_kib())

    monitor_task = asyncio.create_task(monitor())
    samples: list[dict[str, Any]] = []
    cancellations: list[float] = []
    try:
        for round_number in range(rounds):
            print(f"Starting native round {round_number + 1}", flush=True)
            batch = await asyncio.wait_for(
                asyncio.gather(*(run_call(stt, tts, pcm) for _ in range(10))),
                timeout=float(POLICY["turn_deadline_seconds"]),
            )
            samples.extend({"round": round_number + 1, **sample} for sample in batch)
            print("Utterance cohort complete; canceling native cohort", flush=True)

            # Cancel real native inference and queued requests together, twice per task.
            async def cancel_call(index: int) -> None:
                if index % 2:

                    async def incoming() -> AsyncIterator[AudioFrame]:
                        for sequence in range(100):
                            yield AudioFrame(bytes(1920), 16000, sequence, time.monotonic_ns())
                            await asyncio.sleep(0.06)

                    async for _ in stt.transcribe(incoming()):
                        pass
                else:
                    async for _ in tts.synthesize("Hello. " * 25):
                        await asyncio.sleep(0.06)

            cohort = [asyncio.create_task(cancel_call(index)) for index in range(10)]
            await asyncio.sleep(0.025)
            canceled_at = time.perf_counter()
            for task in cohort:
                task.cancel()
            await asyncio.sleep(0)
            for task in cohort:
                task.cancel()
            results = await asyncio.wait_for(
                asyncio.gather(*cohort, return_exceptions=True),
                timeout=float(POLICY["cancellation_deadline_seconds"]),
            )
            if any(not isinstance(result, asyncio.CancelledError) for result in results):
                raise RuntimeError("Native cancellation cohort did not cancel every task")
            cancellations.append(time.perf_counter() - canceled_at)
            print("Cancellation cohort complete", flush=True)
    finally:
        cleanup_started = time.perf_counter()
        await asyncio.wait_for(
            asyncio.gather(stt.aclose(), tts.aclose()),
            timeout=float(POLICY["cleanup_deadline_seconds"]),
        )
        stopping.set()
        await monitor_task
        cleanup_seconds = time.perf_counter() - cleanup_started
    leaked_tasks = len(set(asyncio.all_tasks()) - tasks_before)
    leaked_native_threads = [
        t.name
        for t in threading.enumerate()
        if t.ident not in threads_before and t.name.startswith(("vasa-stt", "vasa-tts"))
    ]
    if leaked_tasks or leaked_native_threads:
        raise RuntimeError("Synthetic benchmark leaked task/native worker resources")
    return {
        "schema_version": 1,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Ten synthetic native CPU utterances; no network LLM or WhatsApp calls",
        "phone_capacity_claim": None,
        "policy_declared_before_execution": {**POLICY, "rounds": rounds},
        "acceptance_passed": True,
        "environment": {"cpu_affinity_count": len(os.sched_getaffinity(0))},
        "model_pool": {
            "stt_workers": 1,
            "stt_slots": 10,
            "tts_workers": 1,
            "tts_slots": 2,
            "tts_stream_slots": 10 if hasattr(tts, "_streams") else 2,
            "tts_generation_admission_scope": (
                "native_generation_only" if hasattr(tts, "_streams") else "stream_lifetime"
            ),
        },
        "queue_observation": "Provider admission limits configured; internal queue sizes unexposed",
        "frame_loss_observation": "Locally yielded frames validated; remote delivery unobserved",
        "latency_seconds": {
            key: percentile_summary([float(sample[key]) for sample in samples])
            for key in [
                "stt_finalization_seconds",
                "tts_first_audio_seconds",
                "synthetic_fixture_end_to_first_audio_seconds",
                "elapsed_seconds",
            ]
        },
        "event_loop_lag_seconds": percentile_summary(lag),
        "cancellation_seconds": percentile_summary(cancellations),
        "cleanup_seconds": cleanup_seconds,
        "resource_cleanup": {
            "leaked_tasks": leaked_tasks,
            "leaked_native_worker_threads": leaked_native_threads,
        },
        "rss_kib": {
            "before_models": rss_before,
            "peak_observed": max(rss_samples),
            "after_close": rss_kib(),
            "samples": len(rss_samples),
        },
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".local/speech"))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("work/capacity-benchmark.json"))
    args = parser.parse_args()
    report = asyncio.run(benchmark(args.directory, args.rounds))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Synthetic native CPU benchmark passed: {len(report['samples'])} utterances.")


if __name__ == "__main__":
    main()
