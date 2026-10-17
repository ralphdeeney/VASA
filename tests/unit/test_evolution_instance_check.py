"""Restore only the exact known persisted instance set without re-pairing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import evolution_instance_check as probe


@pytest.mark.parametrize("restore,connected", [(False, True), (True, True), (True, False)])
async def test_existing_instance_connection_only(monkeypatch, capsys, restore, connected):
    secret = SimpleNamespace(get_secret_value=lambda: "private-secret")
    settings = SimpleNamespace(
        database_url=secret,
        evolution_base_url="http://private",
        evolution_admin_key=secret,
        evolution_stream_key=secret,
        evolution_instance_key=secret,
    )
    client = SimpleNamespace(
        aclose=AsyncMock(),
        _request=AsyncMock(return_value={"data": [{"id": "existing"}]}),
        status=AsyncMock(
            side_effect=[
                SimpleNamespace(connected=connected, logged_in=connected),
                SimpleNamespace(connected=True, logged_in=True),
            ]
        ),
        connect=AsyncMock(),
    )
    database = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(probe, "Settings", lambda: settings)
    monkeypatch.setattr(probe, "Database", lambda _: database)
    monkeypatch.setattr(probe, "EvolutionCalls", lambda *a: client)
    monkeypatch.setattr(
        probe, "resolve_all", AsyncMock(return_value=[("tenant", "id", "existing")])
    )
    monkeypatch.setattr(probe.asyncio, "sleep", AsyncMock())
    await probe.inspect(restore)
    assert client.connect.await_count == int(restore and not connected)
    client._request.assert_awaited_once_with("GET", "/instance/all", "private-secret")
    output = capsys.readouterr().out
    assert output.endswith("EVOLUTION_REGISTERED_INSTANCES_OK\n")
    assert "private-secret" not in output
    assert "existing" not in output
    database.aclose.assert_awaited_once()
    client.aclose.assert_awaited_once()


def test_exception_details_never_printed(monkeypatch, capsys):
    async def fail(_):
        raise ValueError("private-key response body")

    monkeypatch.setattr(probe, "inspect", fail)
    monkeypatch.setattr(probe.sys, "argv", ["probe"])
    assert probe.main() == 1
    assert capsys.readouterr().out == "EVOLUTION_REGISTERED_INSTANCES_FAILED\n"
