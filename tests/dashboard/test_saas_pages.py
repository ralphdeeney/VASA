"""Exercise public page delivery and first-party SaaS UI security boundaries."""

from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vasa.dashboard.router import router

ROOT = Path(__file__).parents[2] / "src/vasa/dashboard"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(saas_enabled=False)
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/features",
        "/how-it-works",
        "/pricing",
        "/contact",
        "/login",
        "/signup",
        "/verify-email",
        "/forgot-password",
        "/reset-password",
        "/accept-invitation",
        "/logout",
    ],
)
def test_public_pages_enforce_first_party_csp(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert '<html lang="en">' in response.text
    assert 'name="viewport"' in response.text


@pytest.mark.parametrize(
    "path,code", [("/403", 403), ("/404", 404), ("/admin", 404), ("/dashboard", 401)]
)
def test_protected_and_error_pages(client: TestClient, path: str, code: int) -> None:
    assert client.get(path).status_code == code


@pytest.mark.parametrize("asset", ["site.js", "identity.js", "workspace.js", "admin.js"])
def test_scripts_are_served_without_html_injection(client: TestClient, asset: str) -> None:
    response = client.get(f"/dashboard/assets/{asset}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "innerHTML" not in response.text
    assert "insertAdjacentHTML" not in response.text
    assert "eval(" not in response.text


class AccessibleForms(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.controls: set[str] = set()
        self.labels: set[str] = set()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.ids.append(identifier)
            if tag in {"input", "select", "textarea"}:
                self.controls.add(identifier)
        if tag == "label" and (identifier := values.get("for")):
            self.labels.add(identifier)


@pytest.mark.parametrize(
    "template", ["login.html", "identity.html", "dashboard.html", "admin.html", "site.html"]
)
def test_form_controls_have_unique_ids_and_labels(template: str) -> None:
    parser = AccessibleForms()
    parser.feed((ROOT / "templates" / template).read_text())
    assert len(parser.ids) == len(set(parser.ids))
    assert parser.controls <= parser.labels


def test_account_tokens_are_removed_and_sensitive_changes_require_confirmation() -> None:
    identity = (ROOT / "assets/identity.js").read_text()
    assert "window.location.hash" in identity
    assert 'history.replaceState(null, "", window.location.pathname)' in identity
    assert "window.location.search" not in identity
    for asset in ["workspace.js", "admin.js"]:
        script = (ROOT / "assets" / asset).read_text()
        assert "window.confirm(" in script
        assert "confirm: true" in script
        assert '"x-csrf-token": csrf' in script


def test_marketing_does_not_present_mock_metrics_or_invented_billing(client: TestClient) -> None:
    text = " ".join(client.get("/").text.split())
    assert "not live account statuses" in text
    assert "billing and self-service payments are not available" in text
    assert "128" not in text


def test_scoped_integrations_and_guided_onboarding_are_wired() -> None:
    page = (ROOT / "templates/dashboard.html").read_text()
    script = (ROOT / "assets/workspace.js").read_text()
    assert 'id="onboarding-heading"' in page
    assert 'id="integrations-list"' in page
    assert 'fetch("/api/saas/integrations"' in script
    assert "No Tool Gateway actions are configured" in script
    assert "Only workspace owners and admins" in script
    assert "name.textContent = item.name" in script


def test_contact_form_requires_capability_and_posts_only_bounded_fields() -> None:
    page = (ROOT / "templates/site.html").read_text()
    script = (ROOT / "assets/site.js").read_text()
    assert 'id="contact-submit"' in page and 'maxlength="4000"' in page
    assert "contact_available" in script
    assert 'fetch("/api/site/contact"' in script
    assert "response.status === 429" in script
    assert "response.status === 503" in script
