"""Operational worker admission/lifecycle checks; transport/speech/providers are component fakes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.control.fixtures import ControlHarness
from vasa import voice_worker as worker
from vasa.config import Settings
from vasa.contracts.models import CallSession, ConnectionStatus, IncomingCall, TenantContext
from vasa.runtime import ConversationResult, RuntimeConfig
from vasa.storage.database import Database
from vasa.voice_worker import resolve_instance

PRIVATE_DETAIL = "private-credentials-provider-error-do-not-disclose"


class PreflightRig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.settings = Settings(
            _env_file=None,
            tts_provider="piper",
            openai_api_key="component-only-openai",
            anthropic_api_key="",
            evolution_admin_key="component-admin",
            evolution_stream_key="component-stream",
            evolution_instance_key="component-instance",
        )
        self.context = TenantContext(uuid4(), uuid4())
        self.external = "owned-instance"
        self.created: list[str] = []
        self.closed: list[str] = []
        self.actions: list[tuple[str, str]] = []
        self.sessions: list[CallSession] = []
        self.deleted: list[UUID] = []
        self.providers: list[str] = []
        self.model_failure: Exception | None = None
        self.model_verified = False
        self.paired = True
        self.reject_failure: Exception | None = None
        self.offers: list[IncomingCall] = []
        self.reject_seen = asyncio.Event()
        self.listening = asyncio.Event()
        self.release_events = asyncio.Event()
        self.contexts: list[TenantContext] = []
        self.runtime_finished = 0
        self.block_calls = True
        self.media_closed: list[str] = []
        self.live_database: Database | None = None

        rig = self

        class Models:
            stt_dir = Path("component/stt")
            tts_dir = Path("component/tts")

            def __init__(self, root: Path) -> None:
                pass

            def verify(self) -> None:
                rig.model_verified = True
                if rig.model_failure is not None:
                    raise rig.model_failure

        class FakeDatabase:
            def __init__(self, url: str, **options: Any) -> None:
                rig.created.append("database")

            def session(self) -> Any:
                assert rig.live_database is not None
                return rig.live_database.session()

            async def aclose(self) -> None:
                if rig.live_database is not None:
                    await rig.live_database.aclose()
                rig.closed.append("database")

        class FakeCache:
            @classmethod
            def from_url(cls, url: str, **options: Any) -> "FakeCache":
                rig.created.append("cache")
                assert options["max_connections"] == 10
                return cls()

            async def ping(self) -> bool:
                return True

            async def aclose(self) -> None:
                rig.closed.append("cache")

        class Registry:
            def __init__(self, cache: FakeCache) -> None:
                pass

            async def put(self, session: CallSession) -> None:
                rig.sessions.append(session)

            async def delete(self, context: TenantContext, id: UUID) -> None:
                assert context == rig.context
                rig.deleted.append(id)

        class Transport:
            def __init__(self, *credentials: str) -> None:
                rig.created.append("transport")

            async def status(self, instance: str) -> ConnectionStatus:
                assert instance == rig.external
                return ConnectionStatus(rig.paired, rig.paired, "Component instance")

            async def events(self, instance: str) -> AsyncIterator[IncomingCall]:
                assert instance == rig.external
                for incoming in rig.offers:
                    yield incoming
                    await asyncio.sleep(0)
                rig.listening.set()
                await rig.release_events.wait()

            async def answer(self, instance: str, call: str, caller: str) -> None:
                rig.actions.append(("answer", call))

            async def reject(self, instance: str, call: str, caller: str) -> None:
                rig.actions.append(("reject", call))
                rig.reject_seen.set()
                if rig.reject_failure is not None:
                    raise rig.reject_failure

            @asynccontextmanager
            async def open_media(self, instance: str, call: str) -> AsyncIterator[object]:
                try:
                    yield object()
                finally:
                    rig.media_closed.append(call)

            async def hangup(self, instance: str, call: str) -> None:
                rig.actions.append(("hangup", call))

            async def aclose(self) -> None:
                rig.closed.append("transport")

        class Provider:
            def __init__(self, api_key: str, *, model: str, tools: Any = None) -> None:
                self.name = "openai" if "openai" in api_key else "anthropic"
                rig.created.append(self.name)
                rig.providers.append(self.name)

            async def aclose(self) -> None:
                # Lifecycle callbacks must run only after admitted calls have drained.
                assert rig.runtime_finished == len(rig.contexts)
                assert len(rig.deleted) == len(rig.contexts)
                rig.closed.append(self.name)

        class Speech:
            def __init__(self, path: Path, *, num_threads: int = 1) -> None:
                assert num_threads == 1
                self.name = path.name
                rig.created.append(self.name)

            async def aclose(self) -> None:
                rig.closed.append(self.name)

        class Runtime:
            def __init__(self, *providers: object, config: RuntimeConfig, **options: Any) -> None:
                self.stt, self.tts, self.llm = providers
                self.config = config
                self.vad_factory = lambda: None

            async def run(
                self,
                context: TenantContext,
                media: object,
                *,
                on_state: Any,
                on_message: Any = None,
            ) -> ConversationResult:
                rig.contexts.append(context)
                try:
                    if rig.block_calls:
                        await asyncio.Event().wait()
                    return ConversationResult()
                finally:
                    rig.runtime_finished += 1

        async def mapping(
            database: object, email: str, instance: UUID
        ) -> tuple[TenantContext, str]:
            return rig.context, rig.external

        async def agent_config(
            database: object, context: object, config: RuntimeConfig, **options: Any
        ) -> RuntimeConfig:
            return config

        class Persistence:
            call_id = uuid4()

            @classmethod
            async def create(cls, *args: Any) -> "Persistence":
                return cls()

            async def on_message(self, message: Any) -> None:
                pass

            async def finalize(self, error: str | None) -> None:
                pass

        monkeypatch.setattr(worker, "persisted_config", agent_config)
        monkeypatch.setattr(worker, "DurableCall", Persistence)
        monkeypatch.setattr(worker, "Settings", lambda: rig.settings)
        monkeypatch.setattr(worker, "SpeechModels", Models)
        monkeypatch.setattr(worker, "Database", FakeDatabase)
        monkeypatch.setattr(worker, "resolve_instance", mapping)
        monkeypatch.setattr(worker, "Redis", FakeCache)
        monkeypatch.setattr(worker, "CallRegistry", Registry)
        monkeypatch.setattr(worker, "EvolutionCalls", Transport)
        monkeypatch.setattr(worker, "OpenAIProvider", Provider)
        monkeypatch.setattr(worker, "AnthropicProvider", Provider)
        monkeypatch.setattr(worker, "SherpaSTT", Speech)
        monkeypatch.setattr(worker, "SherpaTTS", Speech)
        monkeypatch.setattr(worker, "ConversationRuntime", Runtime)


@pytest.mark.parametrize("failure", ["key", "models"])
async def test_missing_live_prerequisite_prevents_all_remote_calls(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    rig = PreflightRig(monkeypatch)
    if failure == "key":
        rig.settings.openai_api_key = rig.settings.anthropic_api_key
        error = ValueError
    else:
        rig.model_failure = FileNotFoundError(PRIVATE_DETAIL)
        error = FileNotFoundError
    with pytest.raises(error):
        await worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    assert rig.model_verified
    assert rig.created == rig.actions == rig.sessions == []


async def test_missing_speechify_key_prevents_remote_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr

    rig = PreflightRig(monkeypatch)
    rig.settings.tts_provider = "speechify"
    rig.settings.speechify_api_key = SecretStr("")
    with pytest.raises(ValueError, match="SPEECHIFY_API_KEY"):
        await worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    assert rig.created == rig.actions == rig.sessions == []


@pytest.mark.integration
async def test_foreign_real_sql_instance_mapping_prevents_transport_creation_or_answer(
    monkeypatch: pytest.MonkeyPatch,
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    rig = PreflightRig(monkeypatch)
    rig.live_database = Database(harness.settings.database_url.get_secret_value())
    monkeypatch.setattr(worker, "resolve_instance", resolve_instance)
    with pytest.raises(ValueError, match="Unknown instance for this user"):
        await worker.run(
            harness.users[0].email, harness.instances[1].id, RuntimeConfig(), once=True
        )
    assert rig.created == rig.closed == ["database"]
    assert rig.actions == rig.sessions == []


async def test_unpaired_status_releases_preflight_clients_without_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = PreflightRig(monkeypatch)
    rig.paired = False
    with pytest.raises(ValueError, match="not paired"):
        await worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    assert rig.created == ["database", "cache", "transport"]
    assert rig.closed == ["transport", "cache", "database"]
    assert rig.actions == rig.sessions == []


async def test_second_provider_constructor_failure_closes_first_provider_and_all_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = PreflightRig(monkeypatch)
    rig.settings.anthropic_api_key = type(rig.settings.openai_api_key)("component-only-anthropic")

    def fail_anthropic(*credentials: Any, **options: Any) -> None:
        raise ValueError(PRIVATE_DETAIL)

    monkeypatch.setattr(worker, "AnthropicProvider", fail_anthropic)
    with pytest.raises(ValueError):
        await worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    assert rig.providers == ["openai"]
    assert rig.closed == ["openai", "transport", "cache", "database"]
    assert rig.actions == rig.sessions == []


async def test_two_active_calls_deduplicate_and_reject_excess_then_cancel_drains_every_resource(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = PreflightRig(monkeypatch)
    rig.settings.anthropic_api_key = type(rig.settings.openai_api_key)("component-only-anthropic")
    call_a = IncomingCall(rig.external, "call-a", "private-caller-a")
    rig.offers = [
        call_a,
        call_a,
        IncomingCall(rig.external, "call-b", "private-caller-b"),
        IncomingCall(rig.external, "excess", "private-caller-c"),
    ]
    task = asyncio.create_task(
        worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=False)
    )
    try:
        await asyncio.wait_for(rig.reject_seen.wait(), 2)
        await asyncio.wait_for(rig.listening.wait(), 2)
        assert rig.actions == [("answer", "call-a"), ("answer", "call-b"), ("reject", "excess")]
        assert rig.contexts == [rig.context, rig.context]
        assert len({session.id for session in rig.sessions}) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert rig.runtime_finished == 2
        assert set(rig.media_closed) == {"call-a", "call-b"}
        assert len(set(rig.deleted)) == 2
        assert sorted(rig.created) == sorted(rig.closed)
        assert set(rig.actions[-2:]) == {("hangup", "call-a"), ("hangup", "call-b")}
        output = capsys.readouterr().out
        for private in (
            PRIVATE_DETAIL,
            "private-caller",
            "component-only-openai",
            "component-only-anthropic",
        ):
            assert private not in output
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_once_waits_for_one_call_and_closes_every_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = PreflightRig(monkeypatch)
    rig.block_calls = False
    rig.offers = [
        IncomingCall(rig.external, "once-a", "private-caller"),
        IncomingCall(rig.external, "once-b", "private-caller"),
    ]
    await worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=True)
    assert rig.actions == [("answer", "once-a"), ("hangup", "once-a")]
    assert rig.runtime_finished == len(rig.deleted) == 1
    assert sorted(rig.created) == sorted(rig.closed)
    output = capsys.readouterr().out
    assert '"audio_recorded":false' in output
    assert "private-caller" not in output


async def test_reject_rpc_failure_drains_admitted_calls_and_never_prints_raw_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rig = PreflightRig(monkeypatch)
    rig.reject_failure = RuntimeError(PRIVATE_DETAIL)
    rig.offers = [
        IncomingCall(rig.external, call_id, "private-caller") for call_id in ("a", "b", "excess")
    ]
    with pytest.raises(RuntimeError):
        await worker.run("operator@example.invalid", uuid4(), RuntimeConfig(), once=False)
    assert rig.runtime_finished == len(rig.deleted) == 2
    assert sorted(rig.created) == sorted(rig.closed)
    assert set(rig.media_closed) == {"a", "b"}
    assert PRIVATE_DETAIL not in capsys.readouterr().out


def test_cli_reports_fixed_error_without_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(*arguments: Any, **options: Any) -> None:
        raise RuntimeError(PRIVATE_DETAIL)

    monkeypatch.setattr(worker, "run", fail)
    monkeypatch.setattr(
        "sys.argv",
        ["voice-worker", "--email", "operator@example.invalid", "--instance", str(uuid4())],
    )
    with pytest.raises(SystemExit) as exit_status:
        worker.main()
    assert exit_status.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "Voice worker unavailable" in output.err
    assert PRIVATE_DETAIL not in output.err and "Traceback" not in output.err


@pytest.mark.parametrize("tts_provider", ["piper", "kokoro-int8", "kitten-micro", "speechify"])
async def test_all_mode_shares_native_models_and_derives_each_call_context(
    monkeypatch: pytest.MonkeyPatch,
    tts_provider: str,
) -> None:
    rig = PreflightRig(monkeypatch)
    rig.settings.tts_provider = tts_provider
    if tts_provider == "speechify":
        from pydantic import SecretStr

        rig.settings.speechify_api_key = SecretStr("component-only-speechify")

        class Speechify:
            def __init__(self, api_key: str, *, voice_id: str) -> None:
                assert api_key == "component-only-speechify"
                assert voice_id == rig.settings.speechify_voice_id
                rig.created.append("speechify")

            async def aclose(self) -> None:
                rig.closed.append("speechify")

        monkeypatch.setattr(worker, "SpeechifyTTS", Speechify)
    elif tts_provider in {"kokoro-int8", "kitten-micro"}:

        class Kokoro:
            def __init__(self, path: Path, *, num_threads: int) -> None:
                assert path == (
                    rig.settings.kitten_model_dir
                    if tts_provider == "kitten-micro"
                    else rig.settings.kokoro_model_dir
                )
                assert num_threads == 1
                rig.created.append(tts_provider)

            async def aclose(self) -> None:
                rig.closed.append(tts_provider)

            async def warmup(self) -> None:
                assert not rig.contexts  # Startup completes before any call is admitted.

        monkeypatch.setattr(
            worker, "KittenMicroTTS" if tts_provider == "kitten-micro" else "KokoroInt8TTS", Kokoro
        )
    contexts = [rig.context, TenantContext(uuid4(), uuid4())]
    mappings = [(contexts[0], uuid4(), "owned-a"), (contexts[1], uuid4(), "owned-b")]

    async def all_mappings(database: object) -> list[tuple[TenantContext, UUID, str]]:
        return mappings

    async def status(self: object, external: str) -> ConnectionStatus:
        return ConnectionStatus(True, True, "Paired")

    async def events(self: object, external: str) -> AsyncIterator[IncomingCall]:
        yield IncomingCall(external, "same-call-id", "private-caller")
        await asyncio.Event().wait()

    async def delete(self: object, context: TenantContext, call_id: UUID) -> None:
        assert context in contexts
        rig.deleted.append(call_id)

    monkeypatch.setattr(worker, "resolve_all", all_mappings)
    monkeypatch.setattr(worker.EvolutionCalls, "status", status)
    monkeypatch.setattr(worker.EvolutionCalls, "events", events)
    monkeypatch.setattr(worker.CallRegistry, "delete", delete)
    task = asyncio.create_task(worker.run_all(RuntimeConfig()))
    try:
        for _ in range(100):
            if len(rig.contexts) == 2:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert set(rig.contexts) == set(contexts)
        expected_tts = tts_provider if tts_provider != "piper" else "tts"
        assert rig.created.count("stt") == rig.created.count(expected_tts) == 1
        assert rig.created.count("tts") == (1 if tts_provider == "piper" else 0)
        assert rig.created.count("openai") == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert rig.runtime_finished == 2 and len(rig.deleted) == 2
    assert sorted(rig.closed) == sorted(rig.created)
