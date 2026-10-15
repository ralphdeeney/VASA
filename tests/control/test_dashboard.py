import pytest

from tests.control.fixtures import PASSWORD, ControlHarness

pytestmark = pytest.mark.integration


async def test_dashboard_requires_session_and_serves_first_party_pages_and_assets(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    assert client.get("/dashboard").status_code == 401
    public_login = client.get("/login")
    assert public_login.status_code == 200
    csrf = harness.login(client)
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    for response in (public_login, dashboard):
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        policy = response.headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert "frame-ancestors 'none'" in policy
        assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
        assert PASSWORD not in response.text
        assert csrf not in response.text
        token = client.cookies.get("vasa_session")
        assert token is not None and token not in response.text
    for asset, content_type in (
        ("styles.css", "text/css"),
        ("login.js", "text/javascript"),
        ("dashboard.js", "text/javascript"),
    ):
        response = client.get(f"/dashboard/assets/{asset}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)
        assert response.headers["x-content-type-options"] == "nosniff"
    assert harness.evolution.calls == []
