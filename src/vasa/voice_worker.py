"""Trusted operator worker for the proven inbound Evolution media transport."""

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from vasa.config import Settings
from vasa.contracts.models import CallSession, CallState, IncomingCall, TenantContext
from vasa.contracts.providers import EvolutionClient, LLMProvider
from vasa.control.models import User, WhatsAppInstance
from vasa.evolution.client import EvolutionCalls
from vasa.evolution.models import EvolutionError
from vasa.llm import AnthropicProvider, FallbackProvider, OpenAIProvider
from vasa.runtime import ConversationRuntime, RuntimeConfig
from vasa.speech import SherpaSTT, SherpaTTS, SpeechModels
from vasa.storage.cache import CallRegistry
from vasa.storage.database import Database


async def resolve_instance(
    database: Database, email: str, instance: UUID
) -> tuple[TenantContext, str]:
    async with database.session() as session:
        user = await session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise ValueError("Unknown local user")
        mapping = await session.scalar(
            select(WhatsAppInstance).where(
                WhatsAppInstance.id == instance, WhatsAppInstance.tenant_id == user.tenant_id
            )
        )
        if mapping is None:
            raise ValueError("Unknown instance for this user")
        return TenantContext(user.tenant_id, user.id), mapping.external_id


async def handle_call(
    client: EvolutionClient,
    registry: CallRegistry,
    context: TenantContext,
    instance_id: str,
    incoming: IncomingCall,
    runtime: ConversationRuntime,
) -> dict[str, object]:
    if incoming.instance_id != instance_id:
        raise ValueError("Call instance mismatch")
    session = CallSession(uuid4(), context.tenant_id, instance_id, incoming.call_id)
    report: dict[str, object] = {"session_id": str(session.id), "error": None}

    async def state(value: CallState) -> None:
        nonlocal session
        session = replace(session, state=value)
        await registry.put(session)

    try:
        await state(CallState.RINGING)
        await state(CallState.ANSWERING)
        await client.answer(instance_id, incoming.call_id, incoming.caller_jid)
        await state(CallState.CONNECTED)
        async with client.open_media(instance_id, incoming.call_id) as media:
            result = await runtime.run(context, media, on_state=state)
        report.update(
            received_frames=result.received_frames,
            sent_frames=result.sent_frames,
            completed_turns=result.completed_turns,
            interruptions=result.interruptions,
            state_transitions=result.state_transitions,
            latencies_ms=result.latencies_ms,
            error=result.error,
            audio_recorded=False,
        )
    except asyncio.CancelledError:
        report["error"] = "cancelled"
        raise
    except Exception:
        # Provider exception bodies can contain tokens, caller identifiers or prompts.
        report["error"] = "call_failed"
    finally:

        async def finish_cleanup() -> None:
            try:
                async with asyncio.timeout(5):
                    await client.hangup(instance_id, incoming.call_id)
                report["hangup_acknowledged"] = True
            except Exception:
                report["hangup_acknowledged"] = False
                report["error"] = report["error"] or "hangup_failed"
            try:
                async with asyncio.timeout(5):
                    await registry.delete(context, session.id)
            except Exception:
                report["error"] = report["error"] or "cache_cleanup_failed"

        cleanup_task = asyncio.create_task(finish_cleanup())
        interrupted = False
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                interrupted = True
        await cleanup_task
        if interrupted:
            raise asyncio.CancelledError
    return report


async def run(email: str, instance: UUID, config: RuntimeConfig, *, once: bool) -> None:
    settings = Settings()
    models = SpeechModels(settings.speech_model_root)
    await asyncio.to_thread(models.verify)
    openai_key = settings.openai_api_key.get_secret_value()
    anthropic_key = settings.anthropic_api_key.get_secret_value()
    if not openai_key and not anthropic_key:
        raise ValueError("Configure a provider key securely before starting the voice worker")
    async with AsyncExitStack() as resources:
        database = Database(settings.database_url.get_secret_value())
        resources.push_async_callback(database.aclose)
        context, external_id = await resolve_instance(database, email, instance)
        cache = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_timeout=3,
            socket_connect_timeout=3,
            max_connections=10,
            retry=Retry(NoBackoff(), 0),
        )
        resources.push_async_callback(cache.aclose)
        await cache.ping()
        client = EvolutionCalls(
            settings.evolution_base_url,
            settings.evolution_admin_key.get_secret_value(),
            settings.evolution_stream_key.get_secret_value(),
            settings.evolution_instance_key.get_secret_value(),
        )
        resources.push_async_callback(client.aclose)
        status = await client.status(external_id)
        if not status.connected or not status.logged_in:
            raise ValueError("Selected instance is not paired")
        providers: dict[str, OpenAIProvider | AnthropicProvider] = {}
        if openai_key:
            providers["openai"] = OpenAIProvider(openai_key, model=settings.openai_model)
            resources.push_async_callback(providers["openai"].aclose)
        if anthropic_key:
            providers["anthropic"] = AnthropicProvider(
                anthropic_key, model=settings.anthropic_model
            )
            resources.push_async_callback(providers["anthropic"].aclose)
        primary = (
            settings.llm_primary if settings.llm_primary in providers else next(iter(providers))
        )
        llm: LLMProvider = providers[primary]
        if len(providers) == 2:
            llm = FallbackProvider(llm, providers["anthropic" if primary == "openai" else "openai"])
        stt = await asyncio.to_thread(SherpaSTT, models.stt_dir)
        resources.push_async_callback(stt.aclose)
        tts = await asyncio.to_thread(SherpaTTS, models.tts_dir)
        resources.push_async_callback(tts.aclose)
        runtime = ConversationRuntime(stt, tts, llm, config=config)
        registry = CallRegistry(cache)
        print("Voice worker ready for the selected paired instance; caller audio is not recorded.")
        # One selected instance; bounded admission prevents model/transport overload.
        active: dict[str, asyncio.Task[None]] = {}

        async def serve(incoming: IncomingCall) -> None:
            report = await handle_call(client, registry, context, external_id, incoming, runtime)
            print(json.dumps(report, separators=(",", ":")), flush=True)

        try:
            async for incoming in client.events(external_id):
                for call_id, task in list(active.items()):
                    if task.done():
                        await task
                        del active[call_id]
                if incoming.call_id in active:
                    continue
                if once:
                    await serve(incoming)
                    return
                if len(active) >= 2:
                    await client.reject(external_id, incoming.call_id, incoming.caller_jid)
                    continue
                active[incoming.call_id] = asyncio.create_task(serve(incoming))
        finally:
            for task in active.values():
                task.cancel()
            await asyncio.gather(*active.values(), return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--instance", required=True, type=UUID)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--instructions", type=Path, help="Trusted operator UTF-8 prompt file")
    parser.add_argument("--greeting", default="Hello, how can I help?")
    options = parser.parse_args()
    try:
        config = RuntimeConfig(greeting=options.greeting)
        if options.instructions:
            if options.instructions.stat().st_size > 16384:
                raise ValueError("Instructions exceed limit")
            config = replace(config, system_prompt=options.instructions.read_text(encoding="utf-8"))
        asyncio.run(run(options.email, options.instance, config, once=options.once))
    except KeyboardInterrupt:
        pass
    except (ValueError, RuntimeError, EvolutionError, OSError, RedisError, SQLAlchemyError):
        parser.exit(
            1, "Voice worker unavailable: check models, private keys, services and mapping.\n"
        )


if __name__ == "__main__":
    main()
