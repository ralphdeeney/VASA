"""Private, bounded transactional email delivery. Never log message material."""

import asyncio
import smtplib
import ssl
import threading
from email.message import EmailMessage
from typing import Protocol

from vasa.config import Settings

_DELIVERY_SLOTS = threading.BoundedSemaphore(4)


class MailUnavailable(Exception):
    """Delivery is unavailable; no provider exception material is public."""


class Mailer(Protocol):
    def configured(self) -> bool: ...

    async def send(self, recipient: str, subject: str, body: str) -> None: ...


class SMTPMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_sender)

    async def send(self, recipient: str, subject: str, body: str) -> None:
        if not self.configured() or not _DELIVERY_SLOTS.acquire(blocking=False):
            raise MailUnavailable()
        try:
            await asyncio.to_thread(self._deliver, recipient, subject, body)
        except Exception:
            raise MailUnavailable() from None

    def _deliver(self, recipient: str, subject: str, body: str) -> None:
        try:
            self._send(recipient, subject, body)
        finally:
            _DELIVERY_SLOTS.release()

    def _send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as client:
            client.ehlo()
            if self.settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if self.settings.smtp_username:
                client.login(
                    self.settings.smtp_username,
                    self.settings.smtp_password.get_secret_value(),
                )
            client.send_message(message)
