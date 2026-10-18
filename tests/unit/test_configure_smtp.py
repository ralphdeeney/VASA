"""Private operator entry must not echo, overwrite, attest or spread a key."""

import os
import stat
from types import SimpleNamespace

import pytest

from scripts import configure_smtp as setup


@pytest.fixture
def private_project(tmp_path, monkeypatch):
    (tmp_path / ".local").mkdir(mode=0o700)
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="vasa-builder"))
    monkeypatch.setattr(
        setup,
        "sys",
        SimpleNamespace(
            stdin=SimpleNamespace(isatty=lambda: True), stderr=SimpleNamespace(isatty=lambda: True)
        ),
    )
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda args, **kw: SimpleNamespace(returncode=0 if args[1] == "check-ignore" else 1),
    )
    return tmp_path


def test_masked_entry_creates_only_private_web_file_without_attesting(
    private_project, monkeypatch, capsys
):
    key = "test-only-reloop-key-not-real"
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: key)
    assert setup.main() == 0
    path = private_project / ".local/smtp.env"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_uid == os.getuid()
    assert path.read_text().count(key) == 2
    assert "VASA_SMTP_SENDER='VASA <noreply@send.litatech.xyz>'" in path.read_text()
    assert "VASA_SMTP_DELIVERY_VERIFIED=false" in path.read_text()
    assert list((private_project / ".local").iterdir()) == [path]
    output = capsys.readouterr().out
    assert "VASA_SMTP_PRIVATE_CONFIG_WRITTEN" in output and key not in output


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_existing_operator_file_is_never_overwritten(private_project, monkeypatch, kind, capsys):
    path = private_project / ".local/smtp.env"
    original = "operator-owned-config"
    if kind == "file":
        path.write_text(original)
    else:
        other = private_project / "operator-config"
        other.write_text(original)
        path.symlink_to(other)
    monkeypatch.setattr(
        setup.getpass, "getpass", lambda prompt: pytest.fail("Must not ask for key")
    )
    assert setup.main() == 1
    assert path.read_text() == original
    assert "existing_configuration_preserved" in capsys.readouterr().out


def test_noninteractive_entry_refused_without_reading_secret(private_project, monkeypatch, capsys):
    monkeypatch.setattr(setup.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(
        setup.getpass, "getpass", lambda prompt: pytest.fail("Must use private TTY")
    )
    assert setup.main() == 1
    assert "private_terminal_required" in capsys.readouterr().out
    assert not (private_project / ".local/smtp.env").exists()


@pytest.mark.parametrize(
    "key", ["", "short", "private\nVASA_SAAS_ENABLED=true", "bad'$(private-secret)"]
)
def test_invalid_or_injectable_key_is_not_written_or_reflected(
    private_project, monkeypatch, key, capsys
):
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: key)
    assert setup.main() == 1
    assert capsys.readouterr().out == "SMTP_PRIVATE_CONFIG_FAILED=invalid_key_format\n"
    assert not (private_project / ".local/smtp.env").exists()


def test_unignored_file_refused_before_prompt(private_project, monkeypatch, capsys):
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(
        setup.getpass, "getpass", lambda prompt: pytest.fail("Git exclusion required")
    )
    assert setup.main() == 1
    assert "private_path_not_ignored" in capsys.readouterr().out


def test_provider_or_terminal_exception_body_is_suppressed(private_project, monkeypatch, capsys):
    def fail(prompt):
        raise OSError("credential=private-test-key raw provider body")

    monkeypatch.setattr(setup.getpass, "getpass", fail)
    assert setup.main() == 1
    assert capsys.readouterr().out == "SMTP_PRIVATE_CONFIG_FAILED=configuration_unavailable\n"


def test_world_writable_private_directory_refused(private_project, monkeypatch, capsys):
    (private_project / ".local").chmod(0o777)
    assert setup.main() == 1
    assert "unsafe_private_directory" in capsys.readouterr().out
