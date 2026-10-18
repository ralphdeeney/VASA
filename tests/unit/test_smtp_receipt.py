"""Delivery attestation changes only the flag in an exact owned private binding."""

import stat

import pytest

from scripts import configure_smtp as setup
from tests.unit.test_configure_smtp import private_project  # noqa: F401

KEY = "test-only-receipt-key-not-real"


def test_receipt_changes_only_flag_atomically_with_private_mode(private_project):  # noqa: F811
    root = private_project
    assert setup.configure(root, secret=KEY)
    path = root / ".local/smtp.env"
    before = path.read_bytes()
    before_stat = path.stat()
    assert setup.configure(root, secret=KEY, delivery_verified=True)
    assert path.read_bytes() == before.replace(
        b"VASA_SMTP_DELIVERY_VERIFIED=false\n", b"VASA_SMTP_DELIVERY_VERIFIED=true\n"
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_uid == before_stat.st_uid
    assert path.stat().st_ino != before_stat.st_ino
    assert list((root / ".local").iterdir()) == [path]


def test_verified_receipt_retry_is_idempotent(private_project):  # noqa: F811
    setup.configure(private_project, secret=KEY)
    setup.configure(private_project, secret=KEY, delivery_verified=True)
    path = private_project / ".local/smtp.env"
    before = (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
    assert not setup.configure(private_project, secret=KEY, delivery_verified=True)
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("change", ["key", "sender", "unknown_field", "mode", "symlink"])
def test_unknown_or_unsafe_binding_cannot_be_attested(private_project, change):  # noqa: F811
    setup.configure(private_project, secret=KEY)
    path = private_project / ".local/smtp.env"
    secret = KEY
    if change == "key":
        secret = "test-only-different-key-not-real"
    elif change == "sender":
        path.write_text(
            path.read_text().replace("noreply@send.litatech.xyz", "other@example.invalid")
        )
    elif change == "unknown_field":
        path.write_text(path.read_text() + "VASA_SAAS_ENABLED=true\n")
    elif change == "mode":
        path.chmod(0o644)
    else:
        target = private_project / ".local/operator.env"
        path.rename(target)
        path.symlink_to(target)
    before = (path.read_bytes(), path.lstat().st_mode)
    with pytest.raises(setup.ConfigurationRefused):
        setup.configure(private_project, secret=secret, delivery_verified=True)
    assert (path.read_bytes(), path.lstat().st_mode) == before
    assert b"VASA_SMTP_DELIVERY_VERIFIED=false\n" in path.read_bytes()


def test_attestation_never_creates_missing_configuration(private_project):  # noqa: F811
    with pytest.raises(setup.ConfigurationRefused):
        setup.configure(private_project, secret=KEY, delivery_verified=True)
    assert not (private_project / ".local/smtp.env").exists()


def test_attestation_requires_protected_credential(private_project, monkeypatch):  # noqa: F811
    setup.configure(private_project, secret=KEY)
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: pytest.fail("Must not prompt"))
    path = private_project / ".local/smtp.env"
    before = path.read_bytes()
    with pytest.raises(setup.ConfigurationRefused):
        setup.configure(private_project, delivery_verified=True)
    assert path.read_bytes() == before


def test_default_terminal_setup_never_attests_receipt(private_project, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: KEY)
    assert setup.main() == 0
    path = private_project / ".local/smtp.env"
    assert "VASA_SMTP_DELIVERY_VERIFIED=false\n" in path.read_text()
    assert "SMTP_MAILBOX_VERIFIED=false" in capsys.readouterr().out
