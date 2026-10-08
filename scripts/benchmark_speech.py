"""Repeat verified native CPU speech fixtures; report measurements without live-call claims."""

import argparse
import asyncio
import importlib
import importlib.metadata
import json
import math
import os
import platform
import time
import wave
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

from vasa.contracts.models import AudioFrame
from vasa.speech import SherpaSTT, SherpaTTS, SpeechModels
from vasa.speech.models import ASR_COMMIT, TTS_ARCHIVE_SHA256

TTS_TEXT = "Hello. Your appointment is confirmed for tomorrow morning."
WER_THRESHOLD = 0.15


def percentile_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("Cannot summarize an empty benchmark")
    return {
        "count": len(values),
        "p50": float(np.percentile(values, 50, method="linear")),
        "p95": float(np.percentile(values, 95, method="linear")),
        "minimum": min(values),
        "maximum": max(values),
    }


def word_errors(reference: str, hypothesis: str) -> int:
    expected, observed = reference.lower().split(), hypothesis.lower().split()
    row = list(range(len(observed) + 1))
    for index, word in enumerate(expected, 1):
        next_row = [index]
        for column, candidate in enumerate(observed, 1):
            next_row.append(
                min(row[column] + 1, next_row[-1] + 1, row[column - 1] + int(word != candidate))
            )
        row = next_row
    return row[-1]


def load_fixture(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path)) as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise RuntimeError("Speech benchmark fixture requires mono PCM16")
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(
            np.float32
        )
    if rate != 16000:
        factor = math.gcd(rate, 16000)
        samples = importlib.import_module("scipy.signal").resample_poly(
            samples, 16000 // factor, rate // factor
        )
    return bytes(np.clip(samples, -32768, 32767).astype("<i2").tobytes()), rate


async def frames(pcm: bytes) -> AsyncIterator[AudioFrame]:
    for offset in range(0, len(pcm), 1920):
        yield AudioFrame(
            pcm[offset : offset + 1920].ljust(1920, b"\0"),
            16000,
            offset // 1920,
            time.monotonic_ns(),
        )


async def benchmark(directory: Path, iterations: int, num_threads: int) -> dict[str, Any]:
    if not 5 <= iterations <= 50 or not 1 <= num_threads <= 8:
        raise ValueError("Use 5 to 50 iterations and 1 to 8 native threads")
    models = SpeechModels(directory)
    models.verify()
    references = {}
    for line in (models.fixture_dir / "trans.txt").read_text().splitlines():
        name, text = line.split(" ", 1)
        references[name] = text
    fixtures = {
        name: load_fixture(models.fixture_dir / name) for name in ["0.wav", "1.wav", "8k.wav"]
    }

    started = time.perf_counter()
    stt = SherpaSTT(models.stt_dir, num_threads=num_threads)
    stt_cold = time.perf_counter() - started
    tts: SherpaTTS | None = None
    stt_samples: list[dict[str, Any]] = []
    tts_samples: list[dict[str, Any]] = []
    try:
        started = time.perf_counter()
        tts = SherpaTTS(models.tts_dir, num_threads=num_threads)
        tts_cold = time.perf_counter() - started
        for iteration in range(iterations):
            for name, (pcm, original_rate) in fixtures.items():
                started = time.perf_counter()
                updates = [text async for text in stt.transcribe(frames(pcm))]
                elapsed = time.perf_counter() - started
                if not updates:
                    raise RuntimeError("Native STT produced no fixture text")
                errors = word_errors(references[name], updates[-1])
                count = len(references[name].split())
                duration = len(pcm) / 32000
                stt_samples.append(
                    {
                        "iteration": iteration + 1,
                        "fixture": name,
                        "original_sample_rate": original_rate,
                        "normalized_sample_rate": 16000,
                        "audio_duration_seconds": duration,
                        "processing_seconds": elapsed,
                        "real_time_factor": elapsed / duration,
                        "update_count": len(updates),
                        "word_errors": errors,
                        "reference_words": count,
                        "word_error_rate": errors / count,
                    }
                )

            started = time.perf_counter()
            output = cast(AsyncGenerator[AudioFrame, None], tts.synthesize(TTS_TEXT))
            try:
                first = await anext(output)
                first_audio = time.perf_counter() - started
                frame_count = 1
                if len(first.pcm) != 1920 or first.sample_rate != 16000:
                    raise RuntimeError("Native TTS returned an invalid frame")
                async for frame in output:
                    if len(frame.pcm) != 1920 or frame.sample_rate != 16000:
                        raise RuntimeError("Native TTS returned an invalid frame")
                    frame_count += 1
                elapsed = time.perf_counter() - started
            finally:
                await output.aclose()
            duration = frame_count * 0.06
            tts_samples.append(
                {
                    "iteration": iteration + 1,
                    "processing_seconds": elapsed,
                    "first_audio_seconds": first_audio,
                    "audio_duration_seconds": duration,
                    "real_time_factor": elapsed / duration,
                    "frame_count": frame_count,
                }
            )
    finally:
        await stt.aclose()
        if tts is not None:
            await tts.aclose()

    errors = sum(sample["word_errors"] for sample in stt_samples)
    words = sum(sample["reference_words"] for sample in stt_samples)
    aggregate_wer = errors / words
    affinity_count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    return {
        "schema_version": 1,
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Sequential native CPU component benchmark; no WhatsApp or LLM latency measured",
        "concurrency_claim": None,
        "iterations": iterations,
        "environment": {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "cpu_affinity_count": affinity_count,
            "native_threads_per_model": num_threads,
            "native_workers_per_model": 1,
            "versions": {
                name: importlib.metadata.version(name)
                for name in ["sherpa-onnx", "sherpa-onnx-core", "numpy", "scipy"]
            },
        },
        "models": {
            "asr_commit": ASR_COMMIT,
            "tts_archive_sha256": TTS_ARCHIVE_SHA256,
            "tts_noise_scale": 0.0,
            "tts_noise_scale_w": 0.0,
        },
        "measurement_policy": {
            "cold_load": "First constructor in this process; OS file cache was not flushed",
            "stt": "Transcribe includes model warmup/final tail; WAV decode/resampling excluded",
            "tts": (
                "Includes synthesis, 22050-to-16000 resampling and PCM framing; playback unpaced"
            ),
            "percentile_method": "linear interpolation",
            "os_file_cache_flushed": False,
        },
        "cold_load_seconds": {"stt": stt_cold, "tts": tts_cold},
        "stt": {
            "processing_seconds": percentile_summary(
                [s["processing_seconds"] for s in stt_samples]
            ),
            "real_time_factor": percentile_summary([s["real_time_factor"] for s in stt_samples]),
            "aggregate_word_error_rate": aggregate_wer,
            "word_errors": errors,
            "reference_words": words,
            "wer_threshold": WER_THRESHOLD,
            "acceptance_passed": aggregate_wer <= WER_THRESHOLD,
            "samples": stt_samples,
        },
        "tts": {
            "text": TTS_TEXT,
            "processing_seconds": percentile_summary(
                [s["processing_seconds"] for s in tts_samples]
            ),
            "first_audio_seconds": percentile_summary(
                [s["first_audio_seconds"] for s in tts_samples]
            ),
            "real_time_factor": percentile_summary([s["real_time_factor"] for s in tts_samples]),
            "samples": tts_samples,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".local/speech"))
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--num-threads", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("reports/speech-benchmark.json"))
    args = parser.parse_args()
    report = asyncio.run(benchmark(args.directory, args.iterations, args.num_threads))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        "Native CPU speech benchmark recorded; aggregate STT WER "
        f"{report['stt']['aggregate_word_error_rate']:.4f}."
    )
    if not report["stt"]["acceptance_passed"]:
        raise SystemExit("Native STT benchmark failed the predefined WER threshold")


if __name__ == "__main__":
    main()
