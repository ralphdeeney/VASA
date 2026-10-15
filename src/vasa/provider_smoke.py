"""Explicit, bounded operator probes. Never invoked by the call runtime."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import cast
from uuid import UUID

from vasa.config import Settings
from vasa.contracts.models import AudioFrame, TenantContext
from vasa.llm.openai import OpenAIProvider
from vasa.speech.deepgram import DeepgramTTS


async def probe(settings: Settings, provider: str) -> list[str]:
    """Return only fixed markers and locally measured numeric timings."""
    name = "LLM" if provider == "llm" else "DEEPGRAM"
    client: OpenAIProvider | DeepgramTTS | None = None
    try:
        key = (
            settings.openai_api_key if provider == "llm" else settings.deepgram_api_key
        ).get_secret_value()
        if not key or (provider == "llm" and settings.llm_primary != "openai"):
            return [f"{name}_SMOKE_FAILED=missing_configuration"]
        async with asyncio.timeout(45):
            started = time.perf_counter()
            first: float | None = None
            audio_bytes = 0
            if provider == "llm":
                client = OpenAIProvider(
                    key,
                    model=settings.openai_model,
                    base_url=settings.openai_base_url,
                    max_output_tokens=32,
                    timeout_seconds=30,
                )
                context = TenantContext(UUID(int=1), UUID(int=1))
                async with aclosing(
                    client.respond(context, [{"role": "user", "content": "Say hello briefly."}])
                ) as events:
                    async for event in events:
                        if event.get("type") == "text" and event.get("text") and first is None:
                            first = time.perf_counter()
            else:
                client = DeepgramTTS(
                    key,
                    model=settings.deepgram_model,
                    request_timeout=30,
                    max_audio_seconds=10,
                    max_streams=1,
                )
                async with aclosing(
                    cast(
                        AsyncGenerator[AudioFrame, None],
                        client.synthesize("Hello. The voice service is available."),
                    )
                ) as frames:
                    async for frame in frames:
                        if (
                            frame.sample_rate != 16000
                            or frame.channels != 1
                            or len(frame.pcm) != 1920
                        ):
                            raise ValueError("invalid frame")
                        audio_bytes += len(frame.pcm)
                        if first is None:
                            first = time.perf_counter()
            if first is None:
                return [f"{name}_SMOKE_FAILED=invalid_response"]
            elapsed = time.perf_counter() - started
            metric = "FIRST_TOKEN" if provider == "llm" else "FIRST_AUDIO"
            result = [
                f"{name}_SMOKE_OK",
                f"{name}_{metric}_MS={(first - started) * 1000:.2f}",
                f"{name}_TOTAL_MS={elapsed * 1000:.2f}",
            ]
            if audio_bytes:
                result.append(f"DEEPGRAM_AUDIO_MS={audio_bytes / 32:.2f}")
            return result
    except TimeoutError:
        return [f"{name}_SMOKE_FAILED=timeout"]
    except Exception:
        # Never interpolate dependency exceptions or remote response content.
        return [f"{name}_SMOKE_FAILED=provider_error"]
    finally:
        if client is not None:
            try:
                async with asyncio.timeout(3):
                    await client.aclose()
            except Exception:
                pass


async def smoke() -> int:
    try:
        settings = Settings()
    except Exception:
        print("LLM_SMOKE_FAILED=invalid_configuration")
        print("DEEPGRAM_SMOKE_FAILED=invalid_configuration")
        return 1
    failed = False
    for provider in ("llm", "deepgram"):
        lines = await probe(settings, provider)
        for line in lines:
            print(line, flush=True)
        failed |= any("_SMOKE_FAILED=" in line for line in lines)
    return int(failed)


def main() -> int:
    # HTTP libraries may otherwise log credential-bearing URLs or error bodies.
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(smoke())
    except Exception:
        print("LLM_SMOKE_FAILED=internal_error")
        print("DEEPGRAM_SMOKE_FAILED=internal_error")
        return 1
