"""Approved client identification preserves real public readiness and TLS gates."""

import io
import socket
import ssl
import urllib.error
import urllib.request
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from deploy import actions_evolution_pool as pool

SECRET = "private-key response-body credential-url caller-id"
PUBLIC_HEALTH = pool.public_health


def install_responses(monkeypatch, statuses):
    responses = iter(statuses)
    requests = []

    def open_request(request, timeout):
        requests.append((request, timeout))
        status = next(responses)
        if status >= 300:
            raise urllib.error.HTTPError(
                request.full_url, status, SECRET, {"private": SECRET}, io.BytesIO(SECRET.encode())
            )
        return nullcontext(SimpleNamespace(status=status))

    monkeypatch.setattr(
        pool.urllib.request, "build_opener", lambda *handlers: SimpleNamespace(open=open_request)
    )
    return requests


def test_identified_get_checks_exact_contract(monkeypatch, capsys):
    requests = install_responses(monkeypatch, (200, 200, 401))
    PUBLIC_HEALTH()
    assert [request.full_url for request, _ in requests] == [
        "https://vasa.litatech.xyz/login",
        "https://vasa.litatech.xyz/health/ready",
        "https://vasa.litatech.xyz/dashboard",
    ]
    for request, timeout in requests:
        assert request.get_method() == "GET"
        assert request.get_header("User-agent") == "VASA-Health-Diagnostic/1.0"
        assert request.data is None
        assert timeout == 15
        assert request.header_items() == [("User-agent", "VASA-Health-Diagnostic/1.0")]
    output = capsys.readouterr().out
    assert "EVOLUTION_PUBLIC_STATUS=dashboard:401" in output
    assert "EVOLUTION_PUBLIC_HEALTH_OK" in output
    assert SECRET not in output


@pytest.mark.parametrize("statuses", [(403,), (200, 500), (200, 502), (200, 503), (301,)])
def test_unexpected_status_is_not_success(monkeypatch, capsys, statuses):
    install_responses(monkeypatch, statuses)
    with pytest.raises(pool.Deferred, match="public_health"):
        PUBLIC_HEALTH()
    output = capsys.readouterr().out
    assert "EVOLUTION_PUBLIC_FAILURE=invalid_status" in output
    assert "EVOLUTION_PUBLIC_HEALTH_OK" not in output
    assert SECRET not in output


def test_verified_tls_and_no_redirect_handler_are_retained(monkeypatch):
    real_build = urllib.request.build_opener
    captured = []

    def inspect_opener(*handlers):
        opener = real_build(*handlers)
        captured.append(opener)
        opener.open = lambda *args, **kwargs: nullcontext(SimpleNamespace(status=200))
        return opener

    monkeypatch.setattr(pool.urllib.request, "build_opener", inspect_opener)
    with pytest.raises(pool.Deferred):  # Dashboard HTTP200 must still fail.
        PUBLIC_HEALTH()
    opener = captured[0]
    https = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
    # Python versions either construct the verified context here or delegate to
    # HTTPSConnection's default verified context; no unverified context is supplied.
    default_context = https._context or ssl._create_default_https_context()
    assert default_context.verify_mode == ssl.CERT_REQUIRED
    assert default_context.check_hostname is True
    redirect = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    assert redirect.redirect_request(None, None, 301, SECRET, {}, "https://private/") is None
    assert not any(type(h) is urllib.request.HTTPRedirectHandler for h in opener.handlers)


@pytest.mark.parametrize(
    "reason,category",
    [
        (socket.gaierror(SECRET), "network"),
        (TimeoutError(SECRET), "timeout"),
        (ssl.SSLCertVerificationError(SECRET), "certificate"),
    ],
)
def test_transport_errors_remain_fatal_and_sanitized(monkeypatch, capsys, reason, category):
    def fail(*args, **kwargs):
        raise urllib.error.URLError(reason)

    monkeypatch.setattr(
        pool.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=fail)
    )
    with pytest.raises(pool.Deferred, match="public_health"):
        PUBLIC_HEALTH()
    output = capsys.readouterr().out
    assert "EVOLUTION_PUBLIC_FAILURE=" + category in output
    assert "EVOLUTION_PUBLIC_HEALTH_OK" not in output
    assert SECRET not in output
