"""Prepare reviewed vendor patches without touching legacy source or secrets."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import prepare_evolution as preparation


@pytest.fixture
def isolated_source(tmp_path, monkeypatch):
    root = tmp_path / "project"
    local = root / ".local"
    old = local / "evolution-source"
    old.mkdir(parents=True)
    (old / "legacy.go").write_text("legacy byte-for-byte")
    (local / "evolution-source-manifest.json").write_text("legacy manifest bytes")
    (local / "vasa.env").write_text("SECRET=do-not-read")
    (local / "evolution.env").write_text("SECRET=do-not-read")
    docker = root / "docker"
    docker.mkdir()
    source = tmp_path / "vendor"
    source.mkdir()
    (source / "main.go").write_text("logging-original\npool-original\n")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    log = docker / "evolution-log-redaction.patch"
    log.write_text(
        "--- a/main.go\n+++ b/main.go\n@@ -1,2 +1,2 @@\n"
        "-logging-original\n+logging-safe\n pool-original\n"
    )
    pool = docker / "evolution-db-pool.patch"
    pool.write_text(
        "--- a/main.go\n+++ b/main.go\n@@ -1,2 +1,2 @@\n"
        " logging-safe\n-pool-original\n+pool-bounded\n"
    )
    monkeypatch.setattr(preparation, "ROOT", root)
    monkeypatch.setattr(preparation, "COMMIT", commit)
    monkeypatch.setattr(
        preparation, "LOG_PATCH_SHA256", hashlib.sha256(log.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(
        preparation, "POOL_PATCH_SHA256", hashlib.sha256(pool.read_bytes()).hexdigest()
    )
    return root, source, local / "evolution-pool-source"


def test_isolated_applies_both_patches_and_preserves_legacy_files(isolated_source, monkeypatch):
    root, source, destination = isolated_source
    before = preparation.fingerprints(root / ".local")
    secret_paths = {root / ".local/vasa.env", root / ".local/evolution.env"}
    original = Path.read_bytes

    def no_secret_reads(path):
        if path in secret_paths:
            pytest.fail("Isolated preparation accessed runtime secrets")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_secret_reads)
    monkeypatch.setattr(
        preparation.secrets, "token_hex", lambda *_: pytest.fail("Secret generation forbidden")
    )
    preparation.prepare(source, destination=destination, isolated=True)
    assert (destination / "main.go").read_text() == "logging-safe\npool-bounded\n"
    manifest = json.loads((root / ".local/evolution-pool-source-manifest.json").read_text())
    assert set(manifest["patches"]) == {"evolution-log-redaction.patch", "evolution-db-pool.patch"}
    for name, digest in before.items():
        assert hashlib.sha256(original(root / ".local" / name)).hexdigest() == digest
    prepared = preparation.fingerprints(destination)
    preparation.prepare(source, destination=destination, isolated=True)
    assert preparation.fingerprints(destination) == prepared


@pytest.mark.parametrize("tamper", ["patch", "cache"])
def test_isolated_refuses_changed_patch_or_cache(isolated_source, tamper):
    root, source, destination = isolated_source
    preparation.prepare(source, destination=destination, isolated=True)
    if tamper == "patch":
        (root / "docker/evolution-db-pool.patch").write_text("unreviewed")
    else:
        (destination / "main.go").write_text("unreviewed")
    with pytest.raises(SystemExit, match="checksum differs|differs from its verified manifest"):
        preparation.prepare(source, destination=destination, isolated=True)


def test_isolated_requires_explicit_safe_destination(isolated_source):
    root, source, destination = isolated_source
    with pytest.raises(SystemExit, match="explicit destination"):
        preparation.prepare(source, isolated=True)
    with pytest.raises(SystemExit, match="isolated pool source"):
        preparation.prepare(source, destination=root / ".local/evolution-source", isolated=True)
    assert not destination.exists()


def test_cli_help_runs_without_site_packages():
    import sys

    result = subprocess.run(
        [sys.executable, "-S", str(Path(preparation.__file__)), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--isolated" in result.stdout and "--destination" in result.stdout


def test_rollback_source_retains_original_pool_code_and_preserves_existing_files(isolated_source):
    root, source, _ = isolated_source
    before = preparation.fingerprints(root / ".local")
    destination = root / ".local/evolution-rollback-source"
    preparation.prepare(source, destination=destination, isolated=True, rollback_source=True)
    assert (destination / "main.go").read_text() == "logging-safe\npool-original\n"
    manifest = json.loads((root / ".local/evolution-rollback-source-manifest.json").read_text())
    assert set(manifest["patches"]) == {"evolution-log-redaction.patch"}
    for name, digest in before.items():
        assert hashlib.sha256((root / ".local" / name).read_bytes()).hexdigest() == digest
    preparation.prepare(source, destination=destination, isolated=True, rollback_source=True)
    with pytest.raises(SystemExit, match="isolated preparation"):
        preparation.prepare(source, rollback_source=True)


def test_portable_python_uses_existing_system_ca_bundle(isolated_source, monkeypatch):
    from types import SimpleNamespace

    _, source, destination = isolated_source
    monkeypatch.setattr(
        preparation.ssl, "get_default_verify_paths", lambda: SimpleNamespace(cafile=None)
    )
    preparation.prepare(source, destination=destination, isolated=True)
    assert b"BEGIN CERTIFICATE" in (destination / "vasa-host-trust.pem").read_bytes()
    assert b"PRIVATE KEY" not in (destination / "vasa-host-trust.pem").read_bytes()
