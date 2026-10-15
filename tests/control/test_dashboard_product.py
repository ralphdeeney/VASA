"""Check first-party product assets and accessible form wiring without services."""

from html.parser import HTMLParser
from pathlib import Path

from vasa.dashboard.router import dashboard_script, stylesheet

ROOT = Path(__file__).parents[2] / "src" / "vasa" / "dashboard"


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.controls: list[str] = []
        self.labels: set[str] = set()
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("id")
        if identifier:
            self.ids.append(identifier)
            if tag in {"input", "textarea"}:
                self.controls.append(identifier)
        label_for = attributes.get("for")
        if tag == "label" and label_for:
            self.labels.add(label_for)
        source = attributes.get("src")
        if tag == "script" and source:
            self.scripts.append(source)


def test_product_forms_have_unique_ids_and_labels_and_first_party_scripts() -> None:
    parser = FormParser()
    parser.feed((ROOT / "templates" / "dashboard.html").read_text())
    assert len(parser.ids) == len(set(parser.ids))
    assert set(parser.controls) <= parser.labels
    assert {"agent-form", "knowledge-form", "upload-form", "call-detail"} <= set(parser.ids)
    assert parser.scripts == ["/dashboard/assets/dashboard.js"]


def test_product_requests_use_shared_csrf_and_render_untrusted_content_as_text() -> None:
    script = (ROOT / "assets" / "dashboard.js").read_text()
    assert 'headers["x-csrf-token"] = csrfToken' in script
    assert 'credentials: "same-origin"' in script
    assert "AbortSignal.timeout(15000)" in script
    assert "innerHTML" not in script and "insertAdjacentHTML" not in script
    assert "description.textContent = `${source.name}" in script
    assert "content.textContent = message.content" in script
    assert '"Content-Type": "application/octet-stream"' in script
    assert 'if (typeof options.body === "string")' in script


async def test_product_assets_keep_restrictive_security_headers() -> None:
    for response in (await dashboard_script(), await stylesheet()):
        assert str(response.path).startswith(str(ROOT))
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert "unsafe-inline" not in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
