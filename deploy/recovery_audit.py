"""Read-only, content-free evidence for release recovery; never authorizes rollout."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

PREFIX = "VASA_RECOVERY_AUDIT="
PATHS = ("edge/Caddyfile", "edge/docker-compose.edge.yml", "tunnel/docker-compose.yml")
SERVICES = ("postgres", "redis", "evolution", "vasa", "voice")
REQUEST = "6e1328c2-3554-4c2d-8153-5639304a6b18"
UPSTREAM = "e21ce0dd7634f3047410c893b5e4d1c082034b84"


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate audit field.")
        result[key] = value
    return result


def read_private(path: Path) -> dict[str, Any]:
    """Bounded owner-only journal access, with no symlink traversal at the leaf."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError()
        if info.st_mode & 0o077 or info.st_size > 65536:
            raise ValueError()
        result = json.loads(stream.read(65537), object_pairs_hook=strict_object)
        if not isinstance(result, dict):
            raise ValueError("Invalid private journal structure.")
        return result


def safe_line(line: str) -> bool:
    if not line.startswith(PREFIX) or len(line) > 8192:
        return False
    try:
        item = json.loads(line[len(PREFIX) :], object_pairs_hook=strict_object)
        if not isinstance(item, dict) or item.get("kind") not in {
            "operator",
            "inventory",
            "service",
            "release",
            "evolution",
            "preservation",
        }:
            return False
        schemas = {
            "operator": {
                "kind",
                "path",
                "tracked",
                "present",
                "regular",
                "fingerprint",
                "reverse_proxy",
                "tunnel",
                "external_network",
                "private_origin",
            },
            "inventory": {"kind", "tracked_changes", "untracked", "unknown_paths_hash"},
            "service": {"kind", "service", "container_hash", "image", "restarts"},
            "release": {"kind", "canonical_sha", "active_sha", "journal_known"},
            "evolution": {
                "kind",
                "image",
                "upstream",
                "upstream_matches",
                "grant_consumed",
                "original_image_known",
                "original_image_matches",
                "rollback_image_matches",
                "identity_baseline",
            },
            "preservation": {
                "kind",
                "containers_unchanged",
                "private_files_unchanged",
                "operator_files_unchanged",
                "database_identity_unchanged",
            },
        }
        if set(item) != schemas[item["kind"]]:
            return False
        booleans = {
            "tracked",
            "present",
            "regular",
            "reverse_proxy",
            "tunnel",
            "external_network",
            "private_origin",
            "journal_known",
            "upstream_matches",
            "grant_consumed",
            "original_image_known",
            "original_image_matches",
            "rollback_image_matches",
            "containers_unchanged",
            "private_files_unchanged",
            "operator_files_unchanged",
            "database_identity_unchanged",
        }
        for key, value in item.items():
            if key in booleans:
                if type(value) is not bool:
                    return False
            elif key in {"tracked_changes", "untracked", "restarts"}:
                if type(value) is not int or not 0 <= value <= 100000:
                    return False
            elif key in {"fingerprint", "unknown_paths_hash", "container_hash"}:
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}|unknown", value):
                    return False
            elif key in {"image"}:
                if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                    return False
            elif key in {"canonical_sha", "active_sha", "upstream"}:
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|unknown", value):
                    return False
            elif key == "path" and value not in PATHS:
                return False
            elif key == "service" and value not in SERVICES:
                return False
            elif key == "identity_baseline" and value not in {"matches", "differs", "unknown"}:
                return False
        return True
    except (ValueError, TypeError, KeyError):
        return False


def emit(**item: Any) -> None:
    line = PREFIX + json.dumps(item, sort_keys=True, separators=(",", ":"))
    if not safe_line(line):
        raise ValueError("Recovery audit output invalid.")
    print(line, flush=True)


def operator_files(ns: dict[str, Any]) -> list[dict[str, Any]]:
    root = ns["ROOT"]
    records = []
    for name in PATHS:
        path = root / name
        regular = present = False
        content = b""
        # Parent symlinks must not escape into unrelated/private infrastructure.
        if not path.parent.is_symlink():
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    present = True
                    regular = stat.S_ISREG(info.st_mode) and info.st_size <= 1024**2
                    if regular:
                        content = stream.read(1024**2 + 1)
            except (OSError, ValueError):
                present = path.exists() or path.is_symlink()
        tracked = (
            ns["capture"](
                "git", "-C", str(root), "ls-files", "--error-unmatch", "--", name
            ).returncode
            == 0
        )
        records.append(
            dict(
                kind="operator",
                path=name,
                tracked=tracked,
                present=present,
                regular=regular,
                fingerprint=digest(content) if regular else "unknown",
                reverse_proxy=b"reverse_proxy" in content,
                tunnel=b"cloudflared" in content or b"tunnel:" in content,
                external_network=b"external:" in content,
                private_origin=b"172.16.2.1:18081" in content,
            )
        )
    return records


def optional(path: Path) -> dict[str, Any]:
    try:
        result = read_private(path)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def git_status(ns: dict[str, Any]) -> str:
    result = ns["capture"](
        "git", "-C", str(ns["ROOT"]), "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    ns["require"](
        result.returncode == 0 and len(result.stdout) <= 1024**2,
        "Git recovery inventory unavailable.",
    )
    return str(result.stdout)


def run(ns: dict[str, Any], evolution: dict[str, Any], sources: dict[str, str]) -> None:
    """Use existing controller identity checks; preserve every file/container unchanged."""
    del evolution
    root = ns["ROOT"]
    before = ns["snapshot_services"](SERVICES)
    hashes = ns["private_hashes"]()
    files = operator_files(ns)
    status = git_status(ns)
    canonical = ns["git"]("rev-parse", "HEAD")
    back: dict[str, Any] = {"__name__": "vasa_recovery_backup_identity"}
    exec(compile(sources["backups"], "backups", "exec"), back)
    identity = back["snapshot"](ns)
    for record in files:
        emit(**record)
    entries = status.split("\0")
    # Rename paths are not parsed as records: classify using status prefixes only.
    tracked = sum(
        bool(re.match(r"[ MADRCUT?!]{2} ", entry)) and not entry.startswith("?? ")
        for entry in entries
    )
    untracked = sum(entry.startswith("?? ") for entry in entries)
    emit(
        kind="inventory",
        tracked_changes=tracked,
        untracked=untracked,
        unknown_paths_hash=digest(status),
    )
    for service in SERVICES:
        item = before[service]
        emit(
            kind="service",
            service=service,
            container_hash=digest(item["id"]),
            image=item["image"],
            restarts=item["restarts"],
        )
    release = optional(root / ".local/actions-release.json")
    active = release.get("active_sha", "unknown")
    if not isinstance(active, str) or not re.fullmatch(r"[0-9a-f]{40}", active):
        active = "unknown"
    emit(
        kind="release",
        canonical_sha=canonical,
        active_sha=active,
        journal_known=active != "unknown",
    )
    ledger = optional(root / (".local/deployment-requests/" + REQUEST + ".json"))
    prior_services = ledger.get("before", {})
    prior_evolution = (
        prior_services.get("evolution", {}) if isinstance(prior_services, dict) else {}
    )
    original = prior_evolution.get("image") if isinstance(prior_evolution, dict) else None
    image = before["evolution"]["image"]
    result = ns["capture"](
        "docker",
        "image",
        "inspect",
        "--format",
        '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        image,
    )
    upstream = result.stdout.strip() if result.returncode == 0 else "unknown"
    if not re.fullmatch(r"[0-9a-f]{40}", upstream):
        upstream = "unknown"
    rollback = ns["capture"](
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        "vasa-evolution:rollback-7a76620d3e670b3e52152ffd313308bb2045861e",
    )
    rollback_matches = rollback.returncode == 0 and rollback.stdout.strip() == image
    baseline = "unknown"
    candidates = sorted((root / ".local/backups").glob("evolution-*/receipt.json"))[-100:]
    # Compare private identities internally; never publish credential-derived hashes.
    receipts = [optional(path) for path in candidates if not path.parent.is_symlink()]
    valid = [receipt for receipt in receipts if isinstance(receipt.get("identity"), dict)]
    if valid:
        baseline = "matches" if any(r["identity"] == identity for r in valid) else "differs"
    emit(
        kind="evolution",
        image=image,
        upstream=upstream,
        upstream_matches=upstream == UPSTREAM,
        grant_consumed=(
            root / ".local/deployment-requests/grant-evolution-pool-2026-10-17.json"
        ).exists(),
        original_image_known=isinstance(original, str)
        and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", original)),
        original_image_matches=original == image,
        rollback_image_matches=rollback_matches,
        identity_baseline=baseline,
    )
    ns["assert_unchanged"](before)
    checks = dict(
        containers_unchanged=True,
        private_files_unchanged=hashes == ns["private_hashes"](),
        operator_files_unchanged=files == operator_files(ns)
        and status == git_status(ns)
        and canonical == ns["git"]("rev-parse", "HEAD"),
        database_identity_unchanged=identity == back["snapshot"](ns),
    )
    emit(kind="preservation", **checks)
    ns["require"](all(checks.values()), "Read-only recovery audit invariants changed.")
