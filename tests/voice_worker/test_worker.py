import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest

from tests.control.fixtures import ControlHarness
from vasa.contracts.models import AudioFrame, CallSession, CallState, IncomingCall, TenantContext
from vasa.runtime import ConversationResult
from vasa.voice_worker import handle_call, resolve_instance

PRIVATE_DETAIL = "private-provider-error-never-disclose"


class Registry:
    def __init__(self, *, put_failure: bool = False, delete_failure: bool = False) -> None:
        self.put_failure = put_failure
        self.delete_failure = delete_failure
        self.sessions: list[CallSession] = []
        self.deleted: list[tuple[TenantContext, UUID]] = []

    async def put(self, session: CallSession) -> None:
        self.sessions.append(session)
        if self.put_failure:
            raise RuntimeError(PRIVATE_DETAIL)

    async def delete(self, context: TenantContext, session_id: UUID) -> None:
        self.deleted.append((context, session_id))
        if self.delete_failure:
            raise RuntimeError(PRIVATE_DETAIL)


class Transport:
    def __init__(self, *, failure: str | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, ...]] = []
        self.closed = False
        self.sent: list[AudioFrame] = []
        self.hangup_entered = asyncio.Event()
        self.release_hangup: asyncio.Event | None = None

    async def answer(self, instance: str, call: str, caller: str) -> None:
        self.calls.append(("answer", instance, call, caller))
        if self.failure == "answer":
            raise RuntimeError(PRIVATE_DETAIL)

    @asynccontextmanager
    async def open_media(self, instance: str, call: str) -> AsyncIterator["Transport"]:
        self.calls.append(("open_media", instance, call))
        if self.failure == "media":
            raise RuntimeError(PRIVATE_DETAIL)
        try:
            yield self
        finally:
            self.closed = True

    async def hangup(self, instance: str, call: str) -> None:
        self.calls.append(("hangup", instance, call))
        self.hangup_entered.set()
        if self.release_hangup is not None:
            await self.release_hangup.wait()
        if self.failure == "hangup":
            raise RuntimeError(PRIVATE_DETAIL)

    async def receive(self) -> AudioFrame:
        return AudioFrame(b"\0" * 1920, 16000, 0, 0)

    async def send(self, frame: AudioFrame) -> None:
        self.sent.append(frame)


class Runtime:
    def __init__(
        self, *, error: str | None = None, failure: bool = False, wait: bool = False
    ) -> None:
        self.error = error
        self.failure = failure
        self.wait = wait
        self.started = asyncio.Event()
        self.closed = False
        self.contexts: list[TenantContext] = []

    async def run(
        self,
        context: TenantContext,
        media: Transport,
        *,
        on_state: Callable[[CallState], Awaitable[None]],
    ) -> ConversationResult:
        self.started.set()
        self.contexts.append(context)
        try:
            if self.failure:
                raise RuntimeError(PRIVATE_DETAIL)
            if self.wait:
                await asyncio.Event().wait()
            await on_state(CallState.LISTENING)
            await on_state(CallState.SPEAKING)
            await media.send(await media.receive())
            await on_state(CallState.ENDING)
            await on_state(CallState.ENDED)
            return ConversationResult(
                received_frames=1,
                sent_frames=1,
                completed_turns=1,
                state_transitions=["CONNECTED", "LISTENING", "SPEAKING", "ENDING", "ENDED"],
                messages=[{"role": "user", "content": PRIVATE_DETAIL}],
                latencies_ms={"tts_time_to_first_audio": [1.0]},
                error=self.error,
            )
        finally:
            self.closed = True


def identity() -> tuple[TenantContext, IncomingCall]:
    return TenantContext(uuid4(), uuid4()), IncomingCall(
        "owned-instance", "call-123", "caller-private"
    )


async def test_worker_answers_routes_trusted_context_and_reports_only_noncontent_metadata() -> None:
    context, incoming = identity()
    client, registry, runtime = Transport(), Registry(), Runtime()
    result = await handle_call(client, registry, context, incoming.instance_id, incoming, runtime)
    assert result["error"] is None and result["hangup_acknowledged"] is True
    assert result["received_frames"] == result["sent_frames"] == result["completed_turns"] == 1
    assert result["audio_recorded"] is False
    assert runtime.contexts == [context]
    assert [session.state for session in registry.sessions] == [
        CallState.RINGING,
        CallState.ANSWERING,
        CallState.CONNECTED,
        CallState.LISTENING,
        CallState.SPEAKING,
        CallState.ENDING,
        CallState.ENDED,
    ]
    assert all(session.tenant_id == context.tenant_id for session in registry.sessions)
    assert client.calls == [
        ("answer", incoming.instance_id, incoming.call_id, incoming.caller_jid),
        ("open_media", incoming.instance_id, incoming.call_id),
        ("hangup", incoming.instance_id, incoming.call_id),
    ]
    assert registry.deleted == [(context, UUID(str(result["session_id"])))]
    assert client.closed and runtime.closed
    output = json.dumps(result)
    for private in (PRIVATE_DETAIL, incoming.caller_jid, "messages", "password", "pcm"):
        assert private not in output


async def test_foreign_instance_rejected_before_any_answer_cache_or_runtime_action() -> None:
    context, incoming = identity()
    client, registry, runtime = Transport(), Registry(), Runtime()
    with pytest.raises(ValueError):
        await handle_call(client, registry, context, "foreign-instance", incoming, runtime)
    assert client.calls == registry.sessions == registry.deleted == runtime.contexts == []


@pytest.mark.parametrize("failure", ["answer", "media", "runtime", "registry"])
async def test_worker_failure_is_sanitized_and_always_attempts_hangup_and_cache_cleanup(
    failure: str,
) -> None:
    context, incoming = identity()
    client = Transport(failure=failure)
    registry = Registry(put_failure=failure == "registry")
    runtime = Runtime(failure=failure == "runtime")
    result = await handle_call(client, registry, context, incoming.instance_id, incoming, runtime)
    assert result["error"] == "call_failed"
    assert result["hangup_acknowledged"] is True
    assert PRIVATE_DETAIL not in json.dumps(result)
    assert client.calls[-1] == ("hangup", incoming.instance_id, incoming.call_id)
    assert registry.deleted == [(context, UUID(str(result["session_id"])))]
    if failure == "runtime":
        assert client.closed and runtime.closed


@pytest.mark.parametrize(
    "hangup_failure,cache_failure,expected",
    [
        (True, False, "hangup_failed"),
        (False, True, "cache_cleanup_failed"),
        (True, True, "hangup_failed"),
    ],
)
async def test_cleanup_failures_do_not_skip_other_cleanup_or_expose_error_text(
    hangup_failure: bool, cache_failure: bool, expected: str
) -> None:
    context, incoming = identity()
    client = Transport(failure="hangup" if hangup_failure else None)
    registry = Registry(delete_failure=cache_failure)
    result = await handle_call(client, registry, context, incoming.instance_id, incoming, Runtime())
    assert result["error"] == expected
    assert result["hangup_acknowledged"] is not hangup_failure
    assert len(registry.deleted) == 1
    assert PRIVATE_DETAIL not in json.dumps(result)


async def test_runtime_fixed_error_is_preserved_despite_later_cleanup_failure() -> None:
    context, incoming = identity()
    result = await handle_call(
        Transport(failure="hangup"),
        Registry(delete_failure=True),
        context,
        incoming.instance_id,
        incoming,
        Runtime(error="stt_timeout"),
    )
    assert result["error"] == "stt_timeout"


async def test_cancelled_worker_propagates_cancellation_after_media_and_cache_cleanup() -> None:
    context, incoming = identity()
    client, registry, runtime = Transport(), Registry(), Runtime(wait=True)
    task = asyncio.create_task(
        handle_call(client, registry, context, incoming.instance_id, incoming, runtime)
    )
    await asyncio.wait_for(runtime.started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.closed and runtime.closed and len(registry.deleted) == 1
    assert client.calls[-1][0] == "hangup"


async def test_repeated_cancellation_cannot_interrupt_cache_cleanup() -> None:
    context, incoming = identity()
    client, registry, runtime = Transport(), Registry(), Runtime(wait=True)
    client.release_hangup = asyncio.Event()
    task = asyncio.create_task(
        handle_call(client, registry, context, incoming.instance_id, incoming, runtime)
    )
    try:
        await asyncio.wait_for(runtime.started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(client.hangup_entered.wait(), 1)
        task.cancel()
        client.release_hangup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert len(registry.deleted) == 1
        assert client.closed and runtime.closed
    finally:
        client.release_hangup.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.integration
async def test_worker_instance_resolution_queries_real_user_and_tenant_mapping(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    context, external = await resolve_instance(
        harness.database, f" {harness.users[0].email.upper()} ", harness.instances[0].id
    )
    assert context == TenantContext(harness.tenants[0].id, harness.users[0].id)
    assert external == harness.instances[0].external_id
    with pytest.raises(ValueError):
        await resolve_instance(harness.database, harness.users[0].email, harness.instances[1].id)
    with pytest.raises(ValueError):
        await resolve_instance(harness.database, "missing@example.invalid", harness.instances[0].id)
