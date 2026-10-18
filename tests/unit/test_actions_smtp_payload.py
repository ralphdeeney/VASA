"""Protected setup payload never leaks a key through diagnostics or changes services."""

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import actions_smtp_payload as payload

KEY = "test-only-reloop-api-key-no-real-secret"


@pytest.fixture
def protected(tmp_path, monkeypatch):
    import pwd
    import subprocess
    import sys

    (tmp_path / ".local").mkdir(mode=0o700)
    (tmp_path / ".local/vps.env").write_text("unchanged-private-file")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("VASA_RECOVERY", "smtp_configure")
    monkeypatch.setenv("VASA_RELOOP_API_KEY", KEY)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="vasa-builder"))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kw: SimpleNamespace(returncode=0 if args[1] == "check-ignore" else 1),
    )
    monkeypatch.setattr(sys, "argv", ["controller", "check", "a" * 40, "false", "smtp_configure"])
    original_read = Path.read_text
    stub = f"""import os,fcntl,hashlib
from pathlib import Path
ROOT=Path({str(tmp_path)!r})
DEPENDENCIES=("postgres","redis","evolution")
SERVICES=("vasa","voice")
def preflight(): pass
def snapshot_services(services): return {{"unchanged":"all-five"}}
def assert_unchanged(value): assert value=={{"unchanged":"all-five"}}
def private_hashes():
    return {{".local/"+p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/".local").glob("*.env")}}
def git(*args): return "canonical-operator-state"
def require(value,message):
    if not value: raise ValueError("private-key-error-should-not-escape")
"""

    def source(path, *args, **kwargs):
        if path == Path("deploy/actions_vps.py"):
            return stub
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", source)
    return tmp_path


def test_round_trip_creates_only_0600_smtp_and_preserves_other_state(protected, capsys):
    code = payload.build()
    ast.parse(code)
    assert code.count(KEY) == 1  # The private stdin payload is the sole transfer.
    before = (protected / ".local/vps.env").read_bytes()
    exec(compile(code, "private-stdin", "exec"), {})
    path = protected / ".local/smtp.env"
    assert path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 == 0o600
    assert path.read_text().count(KEY) == 2
    assert "VASA_SMTP_DELIVERY_VERIFIED=false" in path.read_text()
    assert (protected / ".local/vps.env").read_bytes() == before
    assert (
        capsys.readouterr().out == "VASA_SMTP_PRIVATE_CONFIG_WRITTEN\nSMTP_MAILBOX_VERIFIED=false\n"
    )
    exec(compile(code, "private-stdin", "exec"), {})
    assert (
        capsys.readouterr().out == "VASA_SMTP_PRIVATE_CONFIG_PRESENT\nSMTP_MAILBOX_VERIFIED=false\n"
    )


def test_conflicting_existing_configuration_is_preserved_without_key_reflection(protected, capsys):
    path = protected / ".local/smtp.env"
    path.write_text("operator-setting-do-not-overwrite")
    path.chmod(0o600)
    with pytest.raises(SystemExit):
        exec(compile(payload.build(), "private-stdin", "exec"), {})
    assert path.read_text() == "operator-setting-do-not-overwrite"
    assert (
        capsys.readouterr().out == "SMTP_PRIVATE_CONFIG_FAILED=existing_configuration_preserved\n"
    )


@pytest.mark.parametrize("key", ["", "short", "private\nAPI_KEY=secret"])
def test_invalid_or_missing_github_binding_never_prints_input(protected, monkeypatch, capsys, key):
    monkeypatch.setenv("VASA_RELOOP_API_KEY", key)
    assert payload.main() == 1
    result = capsys.readouterr()
    assert result.out == "" and result.err == "SMTP_GITHUB_SECRET_REQUIRED\n"


def test_non_setup_operation_is_refused_before_remote_changes(protected, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["controller", "deploy", "a" * 40, "false", "smtp_configure"])
    with pytest.raises(SystemExit):
        exec(compile(payload.build(), "private-stdin", "exec"), {})
    assert not (protected / ".local/smtp.env").exists()


def test_non_actions_environment_refused(protected, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError):
        payload.build()
