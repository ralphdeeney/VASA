"""Real anonymous API probes are strict, fixed and secret-safe."""

import io
import ssl
import urllib.error
import urllib.request
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from deploy import health_diagnostics as health

SECRET = "private-api-key response-body https://credentials/"


def test_public_and_private_auth_boundaries(monkeypatch, capsys):
    calls = []
    actual_build = urllib.request.build_opener

    def build(*handlers):
        opener = actual_build(*handlers)
        https = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
        context = https._context or ssl._create_default_https_context()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        redirect = next(
            h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
        )
        assert redirect.redirect_request(None, None, 302, SECRET, {}, SECRET) is None

        def open_request(req, timeout):
            calls.append(req.full_url)
            assert req.get_method() == "GET"
            assert req.header_items() == [("User-agent", health.UA)]
            assert req.data is None
            assert timeout == health.TIMEOUT
            raise urllib.error.HTTPError(req.full_url, 401, SECRET, {}, io.BytesIO(SECRET.encode()))

        opener.open = open_request
        return opener

    monkeypatch.setattr(health.request, "build_opener", build)
    health.verify_auth_boundaries("vps", True)
    assert calls == [
        origin + path
        for origin in (health.PUBLIC, health.PRIVATE)
        for path in ("/api/auth/me", "/api/whatsapp/instances", "/api/saas/admin/users")
    ]
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 7
    assert all(health.safe_line(line) for line in output.splitlines())
    assert SECRET not in output


@pytest.mark.parametrize("status", [200, 302, 403, 404, 500, "401"])
def test_wrong_auth_response_blocks(monkeypatch, capsys, status):
    monkeypatch.setattr(
        health.request,
        "build_opener",
        lambda *args: SimpleNamespace(
            open=lambda *args, **kwargs: nullcontext(SimpleNamespace(status=status))
        ),
    )
    with pytest.raises(ValueError, match="^authentication_boundary$"):
        health.verify_auth_boundaries("github")
    output = capsys.readouterr().out
    assert "VASA_AUTH_BOUNDARIES_OK" not in output
    assert all(health.safe_line(line) for line in output.splitlines())


def test_auth_transport_failure_is_sanitized(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise urllib.error.URLError(SECRET)

    monkeypatch.setattr(health.request, "build_opener", lambda *args: SimpleNamespace(open=fail))
    with pytest.raises(ValueError, match="^authentication_boundary$"):
        health.verify_auth_boundaries("github")
    assert capsys.readouterr().out == "VASA_AUTH_BOUNDARY_FAILED=github:transport\n"


@pytest.mark.parametrize(
    "line",
    [
        "VASA_AUTH_BOUNDARY=github:public:admin:401 " + SECRET,
        "VASA_AUTH_BOUNDARY=github:public:credentials:401",
        "VASA_AUTH_BOUNDARIES_OK=attacker",
        "VASA_AUTH_BOUNDARY_FAILED=vps:" + SECRET,
    ],
)
def test_auth_marker_allowlist_rejects_payloads(line):
    assert not health.safe_line(line)


def test_independent_identified_readiness_contract(monkeypatch, capsys):
    calls = []

    def probe(vantage, endpoint, **kwargs):
        calls.append((vantage, endpoint, kwargs))
        record = health.base(vantage, endpoint, "urllib", "diagnostic", "GET", "auto", False)
        record["status"] = 401 if endpoint == "dashboard" else 200
        return record

    monkeypatch.setattr(health, "probe", probe)
    health.verify_identified_public_health("github")
    assert calls == [
        ("github", endpoint, {"ua": "diagnostic"}) for endpoint in ("login", "ready", "dashboard")
    ]
    assert all(health.safe_line(line) for line in capsys.readouterr().out.splitlines())


@pytest.mark.parametrize("status,error", [(403, "none"), (200, "network"), (0, "timeout")])
def test_independent_readiness_failure_blocks(monkeypatch, status, error):
    monkeypatch.setattr(health, "probe", lambda *a, **k: {"status": status, "error": error})
    monkeypatch.setattr(health, "emit", lambda records: None)
    with pytest.raises(ValueError, match="^public_health$"):
        health.verify_identified_public_health("github")
