import asyncio
import smtplib
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from vasa.config import Settings
from vasa.saas.mailer import MailUnavailable, SMTPMailer


def configured(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "smtp_host": "smtp.reloop.sh",
        "smtp_port": 587,
        "smtp_sender": "vasa@example.invalid",
        "smtp_username": "test-key",
        "smtp_password": "test-key",
        "smtp_delivery_verified": True,
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "changes",
    [
        {"smtp_host": ""},
        {"smtp_sender": ""},
        {"smtp_username": ""},
        {"smtp_password": ""},
        {"smtp_starttls": False},
        {"smtp_password": "different-key"},
        {"smtp_port": 25},
    ],
)
def test_complete_authenticated_tls_configuration_required(changes: dict[str, Any]) -> None:
    assert not SMTPMailer(configured(**changes)).configured()


async def test_mailbox_attestation_required_but_explicit_smoke_allowed(monkeypatch) -> None:
    mailer = SMTPMailer(configured(smtp_delivery_verified=False))
    assert mailer.transport_configured() and not mailer.configured()
    captured: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mailer, "_send", lambda *args: captured.append(args))
    with pytest.raises(MailUnavailable) as error:
        await mailer.send("test@example.invalid", "private", "secret-workflow-token-value")
    assert error.value.code == "delivery_unverified" and not captured
    await mailer.acceptance_smoke("test@example.invalid")
    assert len(captured) == 1 and "secret-workflow-token-value" not in captured[0][2]
    assert not mailer.configured()


async def test_smtp_tls_auth_message_and_context_cleanup(monkeypatch) -> None:
    events: list[Any] = []

    class Client:
        def __init__(self, host, port, *, timeout):
            events.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("closed")

        def ehlo(self):
            events.append("ehlo")

        def starttls(self, *, context):
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            events.append("tls")

        def login(self, username, password):
            assert username == password == "test-key"
            events.append("auth")

        def send_message(self, message):
            assert message["From"] == "vasa@example.invalid"
            assert message["To"] == "test@example.invalid"
            events.append("send")
            return {}

    monkeypatch.setattr(smtplib, "SMTP", Client)
    await SMTPMailer(configured()).send("test@example.invalid", "Test", "Fixed content")
    assert events == [("smtp.reloop.sh", 587, 10), "ehlo", "tls", "ehlo", "auth", "send", "closed"]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (smtplib.SMTPAuthenticationError(535, b"private-key"), "authentication_failed"),
        (ssl.SSLError("private-key"), "tls_failed"),
        (smtplib.SMTPNotSupportedError("private-key"), "tls_failed"),
        (TimeoutError("private-key"), "timeout"),
        (ConnectionRefusedError("private-key"), "connection_failed"),
        (smtplib.SMTPRecipientsRefused({"private": (550, b"private-key")}), "recipient_refused"),
        (RuntimeError("private-key"), "delivery_failed"),
    ],
)
async def test_failures_are_fixed_codes_without_secret_material(monkeypatch, failure, code) -> None:
    mailer = SMTPMailer(configured())

    def fail(*args):
        raise failure

    monkeypatch.setattr(mailer, "_send", fail)
    with pytest.raises(MailUnavailable) as result:
        await mailer.send("test@example.invalid", "private subject", "private token")
    assert result.value.code == code and str(result.value) == ""
    assert result.value.__suppress_context__


async def test_smoke_helper_never_reports_delivery_or_prints_config(monkeypatch, capsys) -> None:
    from scripts.check_smtp import check

    async def smoke(self, recipient):
        assert recipient == "test@example.invalid"

    monkeypatch.setattr(SMTPMailer, "acceptance_smoke", smoke)
    assert await check("test@example.invalid") == 0
    output = capsys.readouterr().out
    assert '"mailbox_delivery_verified": false' in output and "test@example.invalid" not in output
    assert await check("test@example.invalid,private@example.invalid") == 2


def test_reloop_api_key_is_redacted_in_both_settings_fields() -> None:
    settings = configured()
    assert "test-key" not in repr(settings) + str(settings)
    assert settings.smtp_username.get_secret_value() == settings.smtp_password.get_secret_value()


async def test_smoke_helper_missing_configuration_is_fixed_code(monkeypatch, capsys) -> None:
    from scripts import check_smtp

    monkeypatch.setattr(check_smtp, "Settings", lambda: Settings(_env_file=None))
    assert await check_smtp.check("test@example.invalid") == 1
    assert '"code": "missing_configuration"' in capsys.readouterr().out


async def test_cancelled_request_keeps_thread_admission_until_smtp_finishes(monkeypatch) -> None:
    from vasa.saas import mailer as module

    slot = threading.BoundedSemaphore(1)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    mailer = SMTPMailer(configured())

    def slow_send(*args):
        entered.set()
        try:
            release.wait(timeout=5)
        finally:
            finished.set()

    monkeypatch.setattr(module, "_DELIVERY_SLOTS", slot)
    monkeypatch.setattr(mailer, "_send", slow_send)
    pending = asyncio.create_task(mailer.send("test@example.invalid", "Test", "Fixed"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(MailUnavailable) as error:
            await mailer.send("test@example.invalid", "Test", "Fixed")
        assert error.value.code == "busy"
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert await asyncio.to_thread(slot.acquire, True, 2)
    slot.release()


def test_cancelled_queued_executor_work_does_not_leak_admission(monkeypatch) -> None:
    from vasa.saas import mailer as module

    slot = threading.BoundedSemaphore(1)
    release = threading.Event()
    mailer = SMTPMailer(configured())
    monkeypatch.setattr(module, "_DELIVERY_SLOTS", slot)
    monkeypatch.setattr(mailer, "_send", lambda *args: None)

    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()

        def occupy_worker():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)

        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        blocker = loop.run_in_executor(None, occupy_worker)
        await asyncio.wait_for(entered.wait(), 2)
        pending = asyncio.create_task(mailer.send("test@example.invalid", "Test", "Fixed"))
        try:
            # Submission acquires admission synchronously before its first await.
            await asyncio.sleep(0)
            assert not slot.acquire(blocking=False)
            # Let the shielded coroutine queue its executor work behind the blocker.
            await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            release.set()
            await blocker
            # A FIFO executor barrier proves all earlier submitted work has finished.
            await loop.run_in_executor(None, lambda: None)
        assert slot.acquire(blocking=False), "Cancelled queued SMTP work leaked its slot"
        slot.release()

    asyncio.run(scenario())
