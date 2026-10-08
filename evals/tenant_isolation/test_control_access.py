import pytest

from tests.control.fixtures import ControlHarness, control_harness

__all__ = ["control_harness"]
pytestmark = [pytest.mark.integration, pytest.mark.eval]


async def test_authenticated_foreign_instance_access_denied_before_upstream(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    victim_client, attacker_client = harness.client(), harness.client()
    victim_csrf = harness.login(victim_client, 0)
    attacker_csrf = harness.login(attacker_client, 1)
    victim, attacker = harness.instances
    assert victim_client.get(f"/api/whatsapp/instances/{victim.id}/status").status_code == 200
    assert attacker_client.get(f"/api/whatsapp/instances/{attacker.id}/status").status_code == 200
    positive_calls = list(harness.evolution.calls)
    assert positive_calls == [("status", victim.external_id), ("status", attacker.external_id)]

    victim_path = f"/api/whatsapp/instances/{victim.id}"
    forged_headers = {"x-tenant-id": str(harness.tenants[0].id), "x-csrf-token": attacker_csrf}
    for action in ("status", "qr"):
        assert (
            attacker_client.get(f"{victim_path}/{action}", headers=forged_headers).status_code
            == 404
        )
    for action in ("connect", "disconnect"):
        assert (
            attacker_client.post(f"{victim_path}/{action}", headers=forged_headers).status_code
            == 404
        )
    assert attacker_client.get("/api/whatsapp/instances", headers=forged_headers).json() == [
        {"id": str(attacker.id), "name": attacker.name}
    ]
    assert harness.evolution.calls == positive_calls
    # The denied mutation cannot disrupt the victim's valid session or owned operation.
    assert (
        victim_client.post(
            f"{victim_path}/connect", headers={"x-csrf-token": victim_csrf}
        ).status_code
        == 200
    )
    assert harness.evolution.calls[-1] == ("connect", victim.external_id)
