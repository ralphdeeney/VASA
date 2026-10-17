"""Read-only, bounded HTTP evidence. These diagnostics never change health policy."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

PUBLIC = "https://vasa.litatech.xyz"
PRIVATE = "http://172.16.2.1:18081"
UA = "VASA-Health-Diagnostic/1.0"
LIMIT = 65536
TIMEOUT = 7
ENDPOINTS = {
    "login": "/login",
    "ready": "/health/ready",
    "dashboard": "/dashboard",
    "trace": "/cdn-cgi/trace",
}
ERRORS = {
    "none",
    "http",
    "network",
    "timeout",
    "client_unavailable",
    "oversize",
    "invalid_metadata",
}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def address_hash(value: str) -> str:
    try:
        return fingerprint(str(ipaddress.ip_address(value.strip())))
    except ValueError:
        return "unavailable"


def proxy_present() -> bool:
    return any(key.lower() in {"http", "https", "all"} for key in request.getproxies())


def base(
    vantage: str, endpoint: str, client: str, ua: str, method: str, family: str, private: bool
) -> dict[str, object]:
    return {
        "vantage": vantage,
        "endpoint": endpoint,
        "client": client,
        "ua": ua,
        "method": method,
        "family": family,
        "origin": "private" if private else "public",
        "host_sni": "private_http" if private else "vasa_public_tls",
        "tls_verified": False,
        "proxy_present": proxy_present(),
        "http_version": "unavailable",
        "timestamp": timestamp(),
        "status": 0,
        "elapsed_ms": 0,
        "error": "none",
        "cloudflare": False,
        "ray_id": "unavailable",
        "content_type": "other",
        "challenge": False,
        "proxy_headers": False,
        "source_ip_hash": "unavailable",
        "destination_ip_hash": "unavailable",
    }


def headers_into(record: dict[str, object], headers: dict[str, str]) -> None:
    h = {k.lower(): v for k, v in headers.items()}
    ray = h.get("cf-ray", "")
    if re.fullmatch(r"[0-9a-fA-F]{16,32}-[A-Z]{3}", ray):
        record["ray_id"] = ray
    record["cloudflare"] = (
        h.get("server", "").lower() == "cloudflare" or record["ray_id"] != "unavailable"
    )
    record["challenge"] = h.get("cf-mitigated", "").lower() == "challenge"
    record["proxy_headers"] = any(
        k in h for k in ("via", "x-cache", "x-served-by", "cf-cache-status")
    )
    ct = h.get("content-type", "").split(";", 1)[0].strip().lower()
    record["content_type"] = (
        ct if ct in {"text/html", "application/json", "text/plain"} else "other"
    )


def trace_into(record: dict[str, object], body: bytes) -> None:
    for line in body.decode("ascii", errors="ignore").splitlines():
        if line.startswith("ip="):
            record["source_ip_hash"] = address_hash(line[3:])


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(
        self, req: request.Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        return None


def probe(
    vantage: str,
    endpoint: str,
    client: str = "urllib",
    ua: str = "default",
    method: str = "GET",
    family: str = "auto",
    private: bool = False,
) -> dict[str, object]:
    record = base(vantage, endpoint, client, ua, method, family, private)
    url = (PRIVATE if private else PUBLIC) + ENDPOINTS[endpoint]
    started = time.monotonic()
    try:
        if client == "urllib":
            req = request.Request(
                url, method=method, headers={"User-Agent": UA} if ua == "diagnostic" else {}
            )
            try:
                response = request.build_opener(NoRedirect()).open(req, timeout=TIMEOUT)
            except error.HTTPError as exc:
                response = exc
            with response:
                record["status"] = response.code
                version = getattr(response, "version", None)
                record["http_version"] = {10: "1.0", 11: "1.1", 20: "2", 30: "3"}.get(
                    version if isinstance(version, int) else 0, "unavailable"
                )
                headers_into(record, dict(response.headers.items()))
                if endpoint == "trace":
                    body = response.read(LIMIT + 1)
                    if len(body) > LIMIT:
                        record["error"] = "oversize"
                    else:
                        trace_into(record, body)
        else:
            with tempfile.TemporaryDirectory(prefix="vasa-health-") as directory:
                header = Path(directory) / "headers"
                bodyfile = Path(directory) / "body"
                args = [
                    "curl",
                    "--disable",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    str(TIMEOUT),
                    "--connect-timeout",
                    "4",
                    "--max-filesize",
                    str(LIMIT),
                    "--max-redirs",
                    "0",
                    "--dump-header",
                    str(header),
                    "--output",
                    str(bodyfile),
                    "--write-out",
                    "%{http_code}\n%{remote_ip}\n%{http_version}",
                ]
                if ua == "diagnostic":
                    args += ["--user-agent", UA]
                if method == "HEAD":
                    args += ["--head"]
                if family != "auto":
                    args += ["--ipv4" if family == "ipv4" else "--ipv6"]
                result = subprocess.run(
                    args + [url], capture_output=True, timeout=TIMEOUT + 2, check=False
                )
                meta = result.stdout[:256].decode("ascii", errors="ignore").splitlines()
                if meta and re.fullmatch(r"[0-9]{3}", meta[0]):
                    record["status"] = int(meta[0])
                if len(meta) > 1:
                    record["destination_ip_hash"] = address_hash(meta[1])
                if len(meta) > 2 and meta[2] in {"1.0", "1.1", "2", "3"}:
                    record["http_version"] = meta[2]
                if header.exists() and header.stat().st_size <= LIMIT:
                    values = {}
                    for line in header.read_bytes().decode("latin1").splitlines():
                        if ":" in line:
                            key, val = line.split(":", 1)
                            values[key.strip()] = val.strip()
                    headers_into(record, values)
                if endpoint == "trace" and bodyfile.exists() and bodyfile.stat().st_size <= LIMIT:
                    trace_into(record, bodyfile.read_bytes())
                if result.returncode:
                    record["error"] = "timeout" if result.returncode == 28 else "network"
        if (
            isinstance(record["status"], int)
            and record["status"] >= 400
            and record["error"] == "none"
        ):
            record["error"] = "http"
    except FileNotFoundError:
        record["error"] = "client_unavailable"
    except (TimeoutError, subprocess.TimeoutExpired):
        record["error"] = "timeout"
    except Exception:
        record["error"] = "network"
    record["tls_verified"] = not private and bool(record["status"])
    record["elapsed_ms"] = min(999999, max(0, round((time.monotonic() - started) * 1000)))
    return record


def run(vantage: str, include_private: bool = False) -> list[dict[str, object]]:
    if vantage not in {"github", "vps", "cloud"}:
        raise ValueError("invalid vantage")
    records = []
    for endpoint in ("login", "ready", "dashboard"):
        for client in ("urllib", "curl"):
            for ua in ("default", "diagnostic"):
                records.append(probe(vantage, endpoint, client, ua))
    records.extend(
        probe(vantage, "login", "curl", "diagnostic", method, family)
        for method, family in (("HEAD", "auto"), ("GET", "ipv4"), ("GET", "ipv6"))
    )
    records.extend(probe(vantage, "trace", client, "diagnostic") for client in ("urllib", "curl"))
    if include_private:
        records.extend(
            probe(vantage, endpoint, private=True) for endpoint in ("login", "ready", "dashboard")
        )
    # DNS records contain only address-family counts and stable private fingerprints.
    try:
        addresses = socket.getaddrinfo("vasa.litatech.xyz", 443, type=socket.SOCK_STREAM)
        counts: dict[int, set[str]] = {socket.AF_INET: set(), socket.AF_INET6: set()}
        for family, _, _, _, address in addresses:
            if family in counts:
                counts[family].add(address_hash(str(address[0])))
        for family, label in ((socket.AF_INET, "ipv4"), (socket.AF_INET6, "ipv6")):
            records.append(
                {
                    "vantage": vantage,
                    "dns_family": label,
                    "count": min(len(counts[family]), 100),
                    "timestamp": timestamp(),
                }
            )
    except OSError:
        records.append(
            {"vantage": vantage, "dns_family": "unavailable", "count": 0, "timestamp": timestamp()}
        )
    return records


def valid(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    common = {"vantage", "timestamp"}
    if (
        record.get("vantage") not in {"github", "vps", "cloud"}
        or not isinstance(record.get("timestamp"), str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["timestamp"])
    ):
        return False
    if "dns_family" in record:
        return (
            set(record) == common | {"dns_family", "count"}
            and record["dns_family"] in {"ipv4", "ipv6", "unavailable"}
            and type(record["count"]) is int
            and 0 <= record["count"] <= 100
        )
    enums = {
        "endpoint": set(ENDPOINTS),
        "http_version": {"unavailable", "1.0", "1.1", "2", "3"},
        "client": {"urllib", "curl"},
        "ua": {"default", "diagnostic"},
        "method": {"GET", "HEAD"},
        "family": {"auto", "ipv4", "ipv6"},
        "origin": {"private", "public"},
        "host_sni": {"private_http", "vasa_public_tls"},
        "error": ERRORS,
        "content_type": {"text/html", "text/plain", "application/json", "other"},
    }
    booleans = {"tls_verified", "proxy_present", "cloudflare", "challenge", "proxy_headers"}
    hashes = {"source_ip_hash", "destination_ip_hash"}
    expected = common | set(enums) | booleans | hashes | {"status", "elapsed_ms", "ray_id"}
    return (
        set(record) == expected
        and all(isinstance(record[k], str) and record[k] in values for k, values in enums.items())
        and all(type(record[k]) is bool for k in booleans)
        and all(
            isinstance(record[k], str) and re.fullmatch(r"unavailable|[0-9a-f]{16}", record[k])
            for k in hashes
        )
        and type(record["status"]) is int
        and 0 <= record["status"] <= 599
        and type(record["elapsed_ms"]) is int
        and 0 <= record["elapsed_ms"] <= 999999
        and isinstance(record["ray_id"], str)
        and re.fullmatch(r"unavailable|[0-9a-fA-F]{16,32}-[A-Z]{3}", record["ray_id"]) is not None
    )


def safe_line(line: str) -> bool:
    prefix = "VASA_HEALTH_DIAGNOSTIC="
    if not line.startswith(prefix) or len(line) > 2048:
        return False
    try:
        pairs = json.loads(line[len(prefix) :], object_pairs_hook=lambda values: values)
        if not isinstance(pairs, list) or any(
            not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs
        ):
            return False
        if len({pair[0] for pair in pairs}) != len(pairs):
            return False
        return valid(dict(pairs))
    except (ValueError, TypeError, KeyError):
        return False


def emit(records: list[dict[str, object]]) -> None:
    for record in records:
        if not valid(record):
            raise ValueError("invalid diagnostic record")
        print("VASA_HEALTH_DIAGNOSTIC=" + json.dumps(record, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vantage", choices=("github", "vps", "cloud"), required=True)
    parser.add_argument("--include-private", action="store_true")
    options = parser.parse_args()
    emit(run(options.vantage, options.include_private))
