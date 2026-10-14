"""Opt-in sequential Speechify streaming benchmark; never changes production settings."""

import argparse
import asyncio
import importlib.metadata
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Direct filename invocation and ``python -m`` use the same trusted checkout.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_kokoro_int8_vps import (
    RSSSampler,
    STTLoad,
    buffered_response,
    container_snapshot,
    current_rss_mib,
    save_wav,
    system_information,
    validate_scope,
)
from vasa.speech.speechify import SpeechifyTTS

CATEGORIES = ("short", "sentence", "long")


@dataclass(frozen=True)
class BenchmarkProfile:
    """Trusted provider binding; credentials and HTTP payloads never enter evidence."""

    key_environment: str
    provider_factory: Callable[[str, argparse.Namespace, Callable[[dict[str, Any]], None]], Any]
    environment_metadata: Callable[[argparse.Namespace], dict[str, Any]]


def speechify_metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "model": "simba-3.2",
        "voice_id": args.voice_id,
        "output_format": "pcm_16000",
        "speechify_api_version": "2026-09-30",
        "endpoint": "POST https://api.speechify.ai/v1/audio/stream",
    }


def speechify_factory(key: str, args: argparse.Namespace, observer: Any) -> Any:
    return SpeechifyTTS(key, voice_id=args.voice_id, observer=observer)


def benchmark_text(index: int) -> tuple[str, str]:
    """Server-owned synthetic business text; every logical response is unseen."""
    category = CATEGORIES[index % len(CATEGORIES)]
    number = index + 1
    if category == "short":
        return category, f"Certainly, I can check request number {number}."
    if category == "sentence":
        return category, (
            f"For booking number {number}, I can check availability and confirm "
            "the best appointment time for you."
        )
    return category, (
        f"I can help you arrange booking number {number}. "
        f"First I will check available appointment times for request number {number}. "
        f"Then we can review the service details for booking number {number} together. "
        f"Before confirming request number {number} I will repeat the appointment information."
    )


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summary_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {}
    for mode in ("direct", "buffered"):
        for category in ("all", *CATEGORIES):
            selected = [
                row
                for row in rows
                if row["mode"] == mode and (category == "all" or row["category"] == category)
            ]
            complete = [row for row in selected if row["outcome"] == "complete"]
            latencies = [row["first_playable_seconds"] for row in complete]
            groups[f"{mode}/{category}"] = {
                "attempts": len(selected),
                "complete": len(complete),
                "failed": len(selected) - len(complete),
                "first_playable_p50_seconds": percentile(latencies, 0.5),
                "first_playable_p90_seconds": percentile(latencies, 0.9),
                "first_playable_p95_seconds": percentile(latencies, 0.95),
                "max_frame_starvation_seconds": max(
                    (row["max_frame_starvation_seconds"] for row in complete), default=None
                ),
                "effective_rtf_p50": percentile([row["effective_rtf"] for row in complete], 0.5),
                "process_cpu_seconds_p50": percentile(
                    [row["process_cpu_seconds"] for row in complete], 0.5
                ),
                "peak_rss_mib": max((row["peak_rss_mib"] for row in complete), default=None),
            }
    return groups


def load_baseline(path: Path | None, candidate: str) -> dict[str, Any] | None:
    if path is None:
        return None
    record = json.loads(path.read_text())
    if record.get("actual_vps") is not True or record.get("scope") != "vps":
        raise ValueError("Comparison input must explicitly contain actual_vps=true and scope=vps")
    if record.get("candidate") != candidate:
        raise ValueError("Comparison input has the wrong candidate")
    return {"source": str(path), "record": record}


async def direct_response(provider: Any, text: str) -> dict[str, Any]:
    start = time.monotonic()
    sent = []
    iterator = provider.synthesize(text)
    try:
        async for frame in iterator:
            sent.append((time.monotonic() - start, frame.pcm))
    finally:
        await iterator.aclose()
    if not sent:
        raise RuntimeError("No playable PCM audio received")
    pcm = b"".join(data for _, data in sent)
    gaps = []
    playback_end = sent[0][0] + 0.06
    for when, _data in sent[1:]:
        gaps.append(max(0.0, when - playback_end))
        playback_end = max(when, playback_end) + 0.06
    return {
        "first_playable_seconds": sent[0][0],
        "audio_seconds": len(pcm) / 32000,
        "full_response_provider_completion_seconds": time.monotonic() - start,
        "max_frame_starvation_seconds": max(gaps, default=0.0),
        "starvation_note": "Direct mode simulates paced playback of accumulated frames; "
        "buffered mode records actual runtime playback sends.",
        "max_chunk_starvation_seconds": None,
        "pcm": pcm,
    }


async def cancellation_probe(provider: Any, during_playback: bool) -> dict[str, Any]:
    first = asyncio.Event()
    frames = 0

    async def consume() -> None:
        nonlocal frames
        phase = "during playback" if during_playback else "before first audio"
        iterator = provider.synthesize(
            f"Please check cancellation {phase} for this benchmark request. "
            "The appointment details will be confirmed after checking the available times."
        )
        try:
            async for _frame in iterator:
                frames += 1
                first.set()
                await asyncio.sleep(0.06)
        finally:
            await iterator.aclose()

    task = asyncio.create_task(consume())
    try:
        if during_playback:
            first_wait = asyncio.create_task(first.wait())
            try:
                done, _ = await asyncio.wait(
                    {first_wait, task}, timeout=60, return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    raise TimeoutError("Cancellation probe received no playable audio")
                if task in done:
                    await task
                    raise RuntimeError("Cancellation probe stream ended before cancellation")
            finally:
                first_wait.cancel()
                await asyncio.gather(first_wait, return_exceptions=True)
        else:
            await asyncio.sleep(0.001)
        count = frames
        was_active = not task.done()
        before = time.monotonic()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        elapsed = time.monotonic() - before
        await asyncio.sleep(0.1)
        return {
            "phase": "during_playback" if during_playback else "before_first_audio",
            "consumer_cancellation_seconds": elapsed,
            "frames_before_cancel": count,
            "frames_after_cancel": frames - count,
            "stream_was_active": was_active,
            "outcome": "complete" if was_active else "stream_already_complete",
        }
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def write_json(path: Path, record: Any) -> None:
    path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")


async def start_stt(load: Any) -> None:
    load.thread.start()
    if not await asyncio.to_thread(load.ready.wait, 60) or load.error:
        raise RuntimeError("STT fixture/model startup failed; verify prepared speech assets")


async def stop_stt(load: Any) -> None:
    load.stop.set()
    await asyncio.to_thread(load.thread.join, 60)
    if load.thread.is_alive() or load.error:
        raise RuntimeError("STT worker cleanup failed or exceeded 60 seconds")


def stt_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if row["completed"]]
    return {
        "complete_fixtures": len(complete),
        "truncated_cleanup_fixtures": len(rows) - len(complete),
        "max_word_error_rate": max((row["word_error_rate"] for row in complete), default=None),
        "max_frame_processing_deadline_overrun_seconds": max(
            (row["max_frame_processing_deadline_overrun_seconds"] for row in complete),
            default=None,
        ),
        "deadline_misses": sum(row["deadline_misses"] for row in complete),
        "note": "Completed fixtures only; one repeated prerecorded fixture is limited evidence.",
    }


async def run(args: argparse.Namespace, *, profile: BenchmarkProfile | None = None) -> int:
    profile = profile or BenchmarkProfile(
        "SPEECHIFY_API_KEY", speechify_factory, speechify_metadata
    )
    key = os.environ.get(profile.key_environment, "").strip()
    if not key:
        raise ValueError(
            f"Set {profile.key_environment} privately in the benchmark process environment"
        )
    validate_scope(args.scope, Path.cwd(), os.getuid(), True, "A")
    if args.requests < 20 or args.requests > 100:
        raise ValueError("--requests must be between 20 and 100 per mode")
    if len(set(args.cpus)) != 2 or not set(args.cpus).issubset(os.sched_getaffinity(0)):
        raise ValueError("--cpus requires two distinct available CPU indices")
    baselines = {
        "kokoro_int8": load_baseline(args.kokoro_results, "kokoro-int8"),
        "piper": load_baseline(args.piper_results, "piper"),
        "user_reported_kokoro_vps": {
            "provenance": "User-reported approximate VPS results, not independently verified",
            "sentence_first_audio_seconds": 4.2,
            "sentence_rtf": 1.32,
            "long_starvation_seconds": 4.28,
        },
    }
    os.sched_setaffinity(0, set(args.cpus))
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "measurements.json").exists():
        raise ValueError("Output already contains measurements; choose a new evidence directory")
    sampler = RSSSampler()
    events: list[dict[str, Any]] = []
    provider = profile.provider_factory(key, args, events.append)
    sampler.thread.start()
    rows: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    warmups: list[dict[str, Any]] = []
    baseline_load = None
    contender = None
    baseline: list[dict[str, Any]] = []
    environment = system_information()
    environment.update(
        {
            "scope": args.scope,
            "actual_vps": args.scope == "vps",
            "httpx_version": importlib.metadata.version("httpx"),
            "containers_before": container_snapshot(),
            **profile.environment_metadata(args),
            "requests_per_mode": args.requests,
            "warmup_requests": 2,
            "concurrency": 1,
            "stt_contention": args.with_stt,
            "stt_threads": 1 if args.with_stt else None,
            "stt_model": str(args.stt_model) if args.with_stt else None,
            "stt_fixture": str(args.fixtures / "0.wav") if args.with_stt else None,
        }
    )
    fatal = None
    try:
        if args.with_stt:
            # HTTP client is idle: standalone real STT baseline before excluded API warmups.
            baseline_load = STTLoad(args.stt_model, args.fixtures, num_threads=1)
            await start_stt(baseline_load)
            deadline = time.monotonic() + 60
            while not any(row["completed"] for row in baseline_load.results):
                if baseline_load.error or time.monotonic() > deadline:
                    raise RuntimeError("No complete standalone STT fixture within 60 seconds")
                await asyncio.sleep(0.1)
            await stop_stt(baseline_load)
            baseline = list(baseline_load.results)
            baseline_load = None
            contender = STTLoad(args.stt_model, args.fixtures, num_threads=1)
            await start_stt(contender)
        for index in range(2):
            events.clear()
            try:
                await direct_response(provider, benchmark_text(1000 + index)[1])
            finally:
                warmups.append({"excluded_from_statistics": True, "http_requests": list(events)})
        modes = ("direct", "buffered") if args.mode == "both" else (args.mode,)
        for mode_index, mode in enumerate(modes):
            for index in range(args.requests):
                category, text = benchmark_text(mode_index * args.requests + index)
                events.clear()
                start, cpu = time.monotonic(), time.process_time()
                sample_start = len(sampler.samples)
                rss_before = current_rss_mib()
                row: dict[str, Any] = {
                    "mode": mode,
                    "category": category,
                    "index": index + 1,
                    "text": text,
                }
                try:
                    result = await (
                        direct_response(provider, text)
                        if mode == "direct"
                        else buffered_response(provider, text)
                    )
                    pcm = result.pop("pcm")
                    playback = result.pop("playback_pcm", None)
                    filename = f"{mode}-{index + 1:02d}-{category}.wav"
                    save_wav(args.output / filename, pcm)
                    row["wav"] = filename
                    if playback is not None:
                        playback_name = filename.replace(".wav", "-playback.wav")
                        save_wav(args.output / playback_name, playback)
                        row["playback_wav"] = playback_name
                    row.update(result)
                    received_duration = sum(event.get("audio_seconds", 0) for event in events)
                    http_duration = sum(event.get("full_response_seconds", 0) for event in events)
                    if not received_duration or any(
                        event.get("outcome") != "complete" for event in events
                    ):
                        raise RuntimeError("HTTP stream did not complete with audio")
                    row.update(
                        {
                            "outcome": "complete",
                            "received_audio_seconds": received_duration,
                            "effective_rtf": http_duration / received_duration,
                            "effective_rtf_note": "Sum of sequential HTTP stream durations / "
                            "unpadded received audio. Buffered reads include "
                            "playback backpressure.",
                        }
                    )
                except Exception as exc:
                    row.update({"outcome": "failed", "error_type": type(exc).__name__})
                wall = time.monotonic() - start
                cpu_elapsed = time.process_time() - cpu
                row.update(
                    {
                        "http_requests": list(events),
                        "http_request_count": len(events),
                        "process_cpu_seconds": cpu_elapsed,
                        "process_cpu_utilization_percent": 100 * cpu_elapsed / max(wall, 1e-9),
                        "wall_seconds": wall,
                        "cpu_measurement_note": "Includes local frame collection, WAV writing "
                        "and real STT when enabled; "
                        "excludes normal VASA container processes and other host processes.",
                        "rss_before_mib": rss_before,
                        "rss_after_mib": current_rss_mib(),
                        "peak_rss_mib": max(
                            (item["rss_mib"] for item in sampler.samples[sample_start:]),
                            default=current_rss_mib(),
                        ),
                    }
                )
                rows.append(row)
                write_json(
                    args.output / "measurements.json", {"requests": rows, "warmups": warmups}
                )
                if row["outcome"] != "complete":
                    raise RuntimeError("API request failed; inspect sanitized partial evidence")
                if contender is not None and contender.error:
                    raise RuntimeError("Real STT contender failed during API benchmarking")
        for playback in (False, True):
            events.clear()
            try:
                probe = await cancellation_probe(provider, playback)
            except Exception as exc:
                probe = {"outcome": "failed", "error_type": type(exc).__name__}
            probe["http_requests"] = list(events)
            probe["cancelled_before_first_body_byte"] = bool(events) and all(
                event.get("first_byte_seconds") is None for event in events
            )
            probes.append(probe)
    except Exception as exc:
        fatal = type(exc).__name__
    finally:
        for stt_load in (baseline_load, contender):
            if stt_load is not None:
                try:
                    await stop_stt(stt_load)
                except Exception as exc:
                    fatal = type(exc).__name__
        await provider.aclose()
        sampler.stop.set()
        sampler.thread.join(timeout=1)
    if args.with_stt and (
        contender is None or not any(row["completed"] for row in contender.results)
    ):
        fatal = fatal or "NoCompletedSTTContenderFixture"
    environment["containers_after"] = container_snapshot()
    probes_valid = len(probes) == 2 and all(
        probe.get("outcome") == "complete"
        and probe.get("frames_after_cancel") == 0
        and probe.get("stream_was_active") is True
        and (
            (
                probe.get("cancelled_before_first_body_byte") is True
                and probe.get("frames_before_cancel") == 0
            )
            if probe.get("phase") == "before_first_audio"
            else probe.get("frames_before_cancel", 0) > 0
        )
        for probe in probes
    )
    complete = (
        fatal is None
        and probes_valid
        and len(rows) == args.requests * (2 if args.mode == "both" else 1)
        and all(row["outcome"] == "complete" for row in rows)
    )
    measurements = {
        "scope": args.scope,
        "actual_vps": args.scope == "vps",
        **profile.environment_metadata(args),
        "warmups": warmups,
        "requests": rows,
        "cancellation": probes,
        "complete": complete,
        "failure_type": fatal,
        "stt_baseline": baseline,
        "stt_contention": list(contender.results) if contender is not None else [],
    }
    all_events = [event for warmup in warmups for event in warmup["http_requests"]]
    all_events.extend(event for row in rows for event in row["http_requests"])
    statistics = summary_rows(rows)
    targets = {}
    for mode in ("direct", "buffered"):
        sentence = statistics[f"{mode}/sentence"]
        long = statistics[f"{mode}/long"]
        p50 = sentence["first_playable_p50_seconds"]
        p90 = sentence["first_playable_p90_seconds"]
        gap = long["max_frame_starvation_seconds"]
        targets[mode] = {
            "sentence_first_playable_p50_below_500ms": p50 < 0.5 if p50 is not None else None,
            "sentence_first_playable_p90_below_800ms": p90 < 0.8 if p90 is not None else None,
            "long_frame_starvation_below_2_seconds": gap < 2 if gap is not None else None,
            "sentence_sample_count": sentence["complete"],
            "long_sample_count": long["complete"],
        }
    targets["cancellation"] = {
        "valid_probes_no_late_frames": probes_valid,
        "max_consumer_cancellation_seconds": max(
            (
                probe["consumer_cancellation_seconds"]
                for probe in probes
                if "consumer_cancellation_seconds" in probe
            ),
            default=None,
        ),
        "note": "Review consumer and per-HTTP cleanup latency; no automatic provider promotion.",
    }
    baseline_stats = stt_statistics(baseline)
    contender_stats = stt_statistics(list(contender.results) if contender is not None else [])
    stt_degradation = {}
    for metric in ("max_word_error_rate", "max_frame_processing_deadline_overrun_seconds"):
        before, after = baseline_stats[metric], contender_stats[metric]
        stt_degradation[f"{metric}_change"] = (
            after - before if before is not None and after is not None else None
        )
    summary = {
        "scope": args.scope,
        "actual_vps": args.scope == "vps",
        **profile.environment_metadata(args),
        "complete": complete,
        "statistics": statistics,
        "target_observations": targets,
        "tail_estimate_note": "Thirty mixed-category responses yield ten samples/category; "
        "P90/P95 are small-sample descriptive estimates, not reliability guarantees.",
        "comparison": baselines,
        "comparison_limits": "Local baseline fixed texts differ from varied API requests. "
        "B/C local baselines require --with-stt for the same introduced real STT workload; "
        "A requires no introduced STT. Normal container load must also be comparable. "
        "These remain contextual, not paired identical-text measurements.",
        "stt": {
            "enabled": args.with_stt,
            "num_threads": 1 if args.with_stt else None,
            "baseline": baseline_stats,
            "contender": contender_stats,
            "degradation": stt_degradation,
        },
        "connection_evidence": {
            "connect_tcp_events": sum(event.get("connect_tcp_count", 0) for event in all_events),
            "tls_events": sum(event.get("tls_count", 0) for event in all_events),
            "http_requests": len(all_events),
            "note": "One persistent pooled client. Server idle closure can require reconnects; "
            "cancellation may retire the active connection. Probes excluded here.",
        },
        "production_default_changed": False,
        "human_listening": "pending",
        "recommendation": "Pending actual VPS measurements and human listening; no promotion",
        "metric_limits": "Server TTFB subtraction is an estimate, not isolated network RTT; "
        "first response byte is a raw PCM body byte, not HTTP header arrival. "
        "RSS is process-local, not whole VPS.",
    }
    write_json(args.output / "environment.json", environment)
    write_json(args.output / "measurements.json", measurements)
    write_json(args.output / "summary.json", summary)
    return 0 if complete else 1


def parser(*, include_voice: bool = True) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--scope", choices=("vps", "component-smoke"), default="vps")
    result.add_argument("--mode", choices=("direct", "buffered", "both"), default="both")
    result.add_argument("--requests", type=int, default=30, help="20–100 per mode, default 30")
    if include_voice:
        result.add_argument("--voice-id", default="geffen_32")
    result.add_argument("--cpus", nargs=2, type=int, default=[0, 1])
    result.add_argument(
        "--output", type=Path, default=Path("docs/tts-evaluation/speechify-simba-3.2-vps/vps")
    )
    result.add_argument("--piper-results", type=Path)
    result.add_argument("--kokoro-results", type=Path)
    result.add_argument("--with-stt", action="store_true", help="Real one-thread STT contention")
    result.add_argument("--stt-model", type=Path, default=Path(".local/speech/asr"))
    result.add_argument("--fixtures", type=Path, default=Path(".local/speech/fixtures"))
    return result


def main() -> None:
    try:
        code = asyncio.run(run(parser().parse_args()))
    except ValueError as exc:
        # Only local preflight errors are printed; never print HTTP exception bodies/headers.
        raise SystemExit(str(exc)) from None
    if code:
        raise SystemExit("Benchmark incomplete; inspect partial evidence, no production decision")


if __name__ == "__main__":
    main()
