"""Summarize measured records and export original per-chunk PCM for listening."""

import hashlib
import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path("docs/tts-evaluation/streaming")


def main() -> None:
    summaries = []
    chunks = []
    for path in sorted(ROOT.rglob("*.json")):
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "rows" not in data:
            continue
        for case in sorted({row["case"] for row in data["rows"]}):
            for policy in sorted({row["policy"] for row in data["rows"]}):
                rows = [
                    row for row in data["rows"] if row["case"] == case and row["policy"] == policy
                ]
                if not rows:
                    continue
                summaries.append(
                    {
                        "source": str(path.relative_to(ROOT)),
                        "candidate": data["candidate"],
                        "stt": data["contention"],
                        "threads": data.get("threads_per_model", 2),
                        "case": case,
                        "policy": policy,
                        "count": len(rows),
                        "first_playable_p50": float(
                            np.median([r["first_playable_seconds"] for r in rows])
                        ),
                        "first_playable_p95": float(
                            np.percentile([r["first_playable_seconds"] for r in rows], 95)
                        ),
                        "rtf_p50": float(np.median([r["rtf"] for r in rows])),
                        "cpu_seconds_p50": float(np.median([r["cpu_seconds"] for r in rows])),
                        "max_starvation_seconds": max(
                            r["total_playback_underrun_seconds"] for r in rows
                        ),
                        "peak_rss_kib": data["peak_rss_kib"],
                    }
                )
                row = rows[0]
                if len(row["chunks"]) <= 1 or "wav" not in row:
                    continue
                wav_path = path.parent / row["wav"]
                with wave.open(str(wav_path)) as source:
                    assert source.getframerate() == 16000 and source.getsampwidth() == 2
                    pcm = source.readframes(source.getnframes())
                offset = 0
                for index, event in enumerate(row["chunks"]):
                    length = round(event["audio_seconds"] * 32000)
                    section = pcm[offset : offset + length]
                    offset += length
                    target = wav_path.with_name(wav_path.stem + f"-chunk-{index + 1:02}.wav")
                    with wave.open(str(target), "wb") as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(16000)
                        output.writeframes(section)
                    chunks.append(
                        {
                            "wav": str(target.relative_to(ROOT)),
                            "text": event["text"],
                            "generation_seconds": event["generation_seconds"],
                            "ready_seconds": event["ready_seconds"],
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        }
                    )
                assert offset == len(pcm)
    (ROOT / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    (ROOT / "chunk-samples.json").write_text(json.dumps(chunks, indent=2) + "\n")
    checksums = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            checksums.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT)}"
            )
    (ROOT / "SHA256SUMS").write_text("\n".join(checksums) + "\n")


if __name__ == "__main__":
    main()
