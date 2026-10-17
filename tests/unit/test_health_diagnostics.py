"""Structural diagnostics cannot become a raw log channel or a health override."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from deploy import health_diagnostics as h


def test_safe_roundtrip(capsys):
    record = h.base("vps", "login", "curl", "default", "GET", "auto", False)
    h.emit([record])
    assert h.safe_line(capsys.readouterr().out.strip())


@pytest.mark.parametrize(
    "field,value",
    [
        ("ray_id", "secret-key"),
        ("error", "Authorization: secret"),
        ("status", True),
        ("elapsed_ms", -1),
        ("source_ip_hash", "1.2.3.4"),
        ("endpoint", "https://secret"),
        ("timestamp", "secret"),
        ("unknown", "secret"),
    ],
)
def test_reject_malicious_fields(field, value):
    record = h.base("cloud", "login", "urllib", "default", "GET", "auto", False)
    record[field] = value
    line = "VASA_HEALTH_DIAGNOSTIC=" + json.dumps(record)
    assert not h.safe_line(line)
    with pytest.raises(ValueError, match="invalid diagnostic"):
        h.emit([record])


def test_no_raw_headers_or_body():
    record = h.base("github", "login", "curl", "diagnostic", "GET", "auto", False)
    h.headers_into(
        record,
        {
            "Server": "cloudflare",
            "CF-Ray": "0123456789abcdef-LHR",
            "CF-Mitigated": "challenge",
            "Authorization": "Bearer secret",
            "Content-Type": "text/html;secret",
            "Location": "https://user:pass@example.test",
        },
    )
    h.trace_into(record, b"ip=1.2.3.4\ntoken=secret\n")
    text = json.dumps(record)
    assert "secret" not in text and "1.2.3.4" not in text and "pass" not in text
    assert record["cloudflare"] and record["challenge"]
    assert record["source_ip_hash"] == h.address_hash("1.2.3.4")
    assert h.valid(record)


def test_safe_line_rejects_duplicates_and_non_objects():
    assert not h.safe_line('VASA_HEALTH_DIAGNOSTIC={"vantage":"vps","vantage":"cloud"}')
    for value in ("[]", "null", '"secret"', "{" + "x" * 3000):
        assert not h.safe_line("VASA_HEALTH_DIAGNOSTIC=" + value)


def test_probe_curl_preserves_security(monkeypatch):
    called = []

    def execute(args, **kwargs):
        called.append((args, kwargs))
        return subprocess.CompletedProcess(args, 28, b"000\n", b"secret key response")

    monkeypatch.setattr(h.subprocess, "run", execute)
    record = h.probe("vps", "login", "curl", "diagnostic", "HEAD", "ipv6")
    args, kwargs = called[0]
    assert args[-1] == "https://vasa.litatech.xyz/login"
    assert args[1] == "--disable"
    assert "--insecure" not in args and "--location" not in args
    assert "--ipv6" in args and "--head" in args and h.UA in args
    assert kwargs["timeout"] == 9
    assert record["error"] == "timeout"
    assert "secret" not in json.dumps(record)


@pytest.mark.parametrize(
    "exception,expected",
    [
        (FileNotFoundError("secret"), "client_unavailable"),
        (TimeoutError("secret"), "timeout"),
        (RuntimeError("secret"), "network"),
    ],
)
def test_probe_exception_never_emitted(monkeypatch, exception, expected):
    monkeypatch.setattr(h.subprocess, "run", Mock(side_effect=exception))
    record = h.probe("vps", "ready", "curl")
    assert record["error"] == expected
    assert "secret" not in json.dumps(record)


def test_urllib_uses_fixed_url_and_no_redirect(monkeypatch):
    response = Mock()
    response.code = 200
    response.headers = {"Content-Type": "text/html"}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(h.request, "build_opener", Mock(return_value=opener))
    record = h.probe("vps", "login", ua="diagnostic", private=True)
    req = opener.open.call_args.args[0]
    assert req.full_url == "http://172.16.2.1:18081/login"
    assert req.get_header("User-agent") == h.UA
    assert opener.open.call_args.kwargs["timeout"] == 7
    assert record["status"] == 200
    assert not record["tls_verified"]


def test_run_bounded_fixed_matrix(monkeypatch):
    probes = []

    def probe(*args, **kwargs):
        probes.append((args, kwargs))
        return {}

    monkeypatch.setattr(h, "probe", probe)
    monkeypatch.setattr(h.socket, "getaddrinfo", Mock(return_value=[]))
    h.run("vps", True)
    assert len(probes) == 20
    assert sum(kwargs.get("private", False) for _, kwargs in probes) == 3
    assert {args[1] for args, _ in probes} == set(h.ENDPOINTS)
    with pytest.raises(ValueError):
        h.run("arbitrary")


def test_dns_only_hashes_and_counts(monkeypatch):
    monkeypatch.setattr(h, "probe", Mock(return_value={}))
    monkeypatch.setattr(
        h.socket, "getaddrinfo", Mock(return_value=[(h.socket.AF_INET, 1, 0, "", ("1.2.3.4", 443))])
    )
    records = h.run("github")
    assert records[-2]["count"] == 1
    assert "1.2.3.4" not in json.dumps(records)


def test_trace_read_limit_and_no_body_logging(monkeypatch):
    response = Mock()
    response.code = 200
    response.headers = {}
    response.read.return_value = b"x" * (h.LIMIT + 1)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(h.request, "build_opener", Mock(return_value=opener))
    record = h.probe("cloud", "trace")
    response.read.assert_called_once_with(h.LIMIT + 1)
    assert record["error"] == "oversize"
    assert h.valid(record)


def test_curl_never_reads_oversize_header_or_body(monkeypatch):
    def execute(args, **kwargs):
        from pathlib import Path

        Path(args[args.index("--dump-header") + 1]).write_bytes(b"X-Secret:" + b"x" * h.LIMIT)
        Path(args[args.index("--output") + 1]).write_bytes(b"ip=1.2.3.4\n" + b"x" * h.LIMIT)
        return subprocess.CompletedProcess(args, 0, b"200\n1.2.3.4", b"secret")

    monkeypatch.setattr(h.subprocess, "run", execute)
    record = h.probe("vps", "trace", "curl")
    assert record["source_ip_hash"] == "unavailable"
    assert "secret" not in json.dumps(record)


def test_redirects_never_followed():
    assert (
        h.NoRedirect().redirect_request(None, None, 302, "secret", None, "https://user:secret@test")
        is None
    )


def test_no_proxy_alone_is_not_a_proxy(monkeypatch):
    monkeypatch.setattr(h.request, "getproxies", lambda: {"no": "secret"})
    assert not h.proxy_present()
    monkeypatch.setattr(h.request, "getproxies", lambda: {"https": "secret"})
    assert h.proxy_present()


def test_curl_protocol_is_fixed_metadata(monkeypatch):
    monkeypatch.setattr(
        h.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, b"200\n1.2.3.4\n2", b""),
    )
    record = h.probe("github", "login", "curl")
    assert record["http_version"] == "2"
    assert h.valid(record)


def test_failed_connection_never_claims_verified_tls(monkeypatch):
    monkeypatch.setattr(h.subprocess, "run", Mock(side_effect=TimeoutError("private")))
    record = h.probe("vps", "login", "curl")
    assert record["status"] == 0
    assert record["tls_verified"] is False


def test_verified_public_http_response_records_tls_success(monkeypatch):
    monkeypatch.setattr(
        h.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, b"200\n1.2.3.4\n1.1", b""),
    )
    record = h.probe("vps", "login", "curl")
    assert record["status"] == 200
    assert record["tls_verified"] is True
