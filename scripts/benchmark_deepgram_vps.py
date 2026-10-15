"""Opt-in Deepgram Aura TTS benchmark using VASA's shared sequential streaming harness."""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_speechify_vps import BenchmarkProfile
from scripts.benchmark_speechify_vps import parser as shared_parser
from scripts.benchmark_speechify_vps import run as shared_run
from vasa.speech.deepgram import DeepgramTTS


def metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "candidate": "deepgram",
        "model": args.model,
        "encoding": "linear16",
        "container": "none",
        "sample_rate": 16000,
        "channels": 1,
        "endpoint": "POST https://api.deepgram.com/v1/speak",
    }


def provider_factory(key: str, args: argparse.Namespace, observer: Any) -> DeepgramTTS:
    return DeepgramTTS(key, model=args.model, observer=observer)


async def run(args: argparse.Namespace) -> int:
    return await shared_run(
        args,
        profile=BenchmarkProfile("DEEPGRAM_API_KEY", provider_factory, metadata),
    )


def parser() -> argparse.ArgumentParser:
    result = shared_parser(include_voice=False)
    result.description = __doc__
    result.add_argument("--model", default="aura-2-thalia-en")
    result.set_defaults(output=Path("docs/tts-evaluation/deepgram-aura-2-vps/vps"))
    return result


def main() -> None:
    try:
        code = asyncio.run(run(parser().parse_args()))
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if code:
        raise SystemExit("Benchmark incomplete; inspect sanitized evidence, no production decision")


if __name__ == "__main__":
    main()
