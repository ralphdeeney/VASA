import json
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vasa.app import create_app
from vasa.config import Settings
from vasa.contracts.models import AudioFrame, CallState, TenantContext
from vasa.logging import JsonFormatter


def test_liveness() -> None:
    assert TestClient(create_app()).get("/health/live").json() == {"status": "alive"}


def test_configuration_keeps_connection_strings_secret() -> None:
    settings = Settings(database_url="postgresql+asyncpg://user:private@localhost/db")
    assert "private" not in repr(settings)
    assert "private" not in settings.model_dump_json()


def test_logging_does_not_emit_message_arguments_or_exception_text() -> None:
    record = logging.LogRecord("vasa", logging.ERROR, "", 0, "token=%s", ("private",), None)
    record.event = "dependency_failure"
    output = JsonFormatter().format(record)
    assert "private" not in output
    assert json.loads(output)["event"] == "dependency_failure"


@pytest.mark.parametrize(
    "pcm,rate,sequence",
    [(b"x", 16000, 0), (b"xx", 123, 0), (b"xx", 16000, -1), (b"xx" * 16001, 16000, 0)],
)
def test_rejects_invalid_normalized_audio(pcm: bytes, rate: int, sequence: int) -> None:
    with pytest.raises(ValueError):
        AudioFrame(pcm=pcm, sample_rate=rate, sequence=sequence, timestamp_ns=0)


def test_trusted_context_and_call_states() -> None:
    tenant_id = uuid4()
    context = TenantContext(tenant_id=tenant_id, user_id=uuid4())
    assert context.tenant_id == tenant_id
    assert CallState.SPEAKING.value == "SPEAKING"
