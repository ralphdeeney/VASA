"""Restore only the exact known persisted instance set without re-pairing."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import evolution_instance_check as probe


@pytest.mark.parametrize(
    "restore,connected,preserve_offline",
    [
        (False, True, False),
        (False, False, False),
        (True, True, False),
        (True, False, False),
        (False, False, True),
        (False, True, True),
    ],
)
@pytest.mark.parametrize("paired", [True, False])
async def test_existing_instance_connection_only(
    monkeypatch, capsys, restore, connected, paired, preserve_offline
):
    secret = SimpleNamespace(get_secret_value=lambda: "private-secret")
    settings = SimpleNamespace(
        database_url=SimpleNamespace(
            get_secret_value=lambda: "postgresql+asyncpg://user:private-secret@postgres/app"
        ),
        evolution_base_url="http://private",
        evolution_admin_key=secret,
        evolution_stream_key=secret,
        evolution_instance_key=secret,
    )
    client = SimpleNamespace(
        aclose=AsyncMock(),
        _request=AsyncMock(
            return_value={"data": [{"id": "existing", "jid": "saved-private-device"}]}
        ),
        status=AsyncMock(
            side_effect=[
                SimpleNamespace(connected=connected, logged_in=connected),
                SimpleNamespace(connected=True, logged_in=True),
            ]
        ),
        connect=AsyncMock(),
        token_for_instance=lambda _: "private-instance-token",
    )

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(scalar=AsyncMock(return_value=paired))

    database = SimpleNamespace(aclose=AsyncMock(), session=session)
    monkeypatch.setattr(probe, "Settings", lambda: settings)
    monkeypatch.setattr(probe, "Database", lambda _: database)
    monkeypatch.setattr(probe, "EvolutionCalls", lambda *a: client)
    monkeypatch.setattr(
        probe, "resolve_all", AsyncMock(return_value=[("tenant", "id", "existing")])
    )
    monkeypatch.setattr(probe.asyncio, "sleep", AsyncMock())
    if not paired:
        with pytest.raises(ValueError, match="paired device missing"):
            await probe.inspect(restore, preserve_offline=preserve_offline)
        assert client._request.await_count == 1
        client.connect.assert_not_awaited()
        return
    if preserve_offline and connected:
        with pytest.raises(ValueError, match="offline baseline changed"):
            await probe.inspect(restore, preserve_offline=True)
        assert client._request.await_count == 1
        return
    await probe.inspect(restore, preserve_offline=preserve_offline)
    client.connect.assert_not_awaited()
    assert client._request.await_count == 1 + int(restore and not connected)
    client._request.assert_any_await("GET", "/instance/all", "private-secret")
    if restore and not connected:
        client._request.assert_any_await("POST", "/instance/reconnect", "private-instance-token")
    output = capsys.readouterr().out
    assert output.endswith("EVOLUTION_REGISTERED_INSTANCES_OK\n")
    assert "private-secret" not in output
    assert "existing" not in output
    assert database.aclose.await_count == 2
    client.aclose.assert_awaited_once()


def test_exception_details_never_printed(monkeypatch, capsys):
    async def fail(_):
        raise ValueError("private-key response body")

    monkeypatch.setattr(probe, "inspect", fail)
    monkeypatch.setattr(probe.sys, "argv", ["probe"])
    assert probe.main() == 1
    assert capsys.readouterr().out == "EVOLUTION_REGISTERED_INSTANCES_FAILED\n"
