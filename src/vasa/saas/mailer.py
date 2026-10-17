"""Private, bounded transactional email delivery. Never log message material."""

import asyncio
import smtplib
import ssl
import threading
from email.message import EmailMessage
from typing import Literal, Protocol

from vasa.config import Settings

_DELIVERY_SLOTS = threading.BoundedSemaphore(4)
_DELIVERY_TASKS: set[asyncio.Task[None]] = set()
FailureCode = Literal[
    "missing_configuration",
    "delivery_unverified",
    "authentication_failed",
    "tls_failed",
    "connection_failed",
    "timeout",
    "recipient_refused",
    "delivery_failed",
    "busy",
]


class MailUnavailable(Exception):
    """Delivery is unavailable; no provider exception material is public."""

    def __init__(self, code: FailureCode = "delivery_failed") -> None:
        self.code = code
        super().__init__()


class Mailer(Protocol):
    def configured(self) -> bool: ...

    async def send(self, recipient: str, subject: str, body: str) -> None: ...


class SMTPMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return self.transport_configured() and self.settings.smtp_delivery_verified

    def transport_configured(self) -> bool:
        """Complete authenticated STARTTLS transport; not a mailbox-delivery claim."""
        values = (
            self.settings.smtp_host,
            self.settings.smtp_sender,
            self.settings.smtp_username.get_secret_value(),
            self.settings.smtp_password.get_secret_value(),
        )
        if self.settings.smtp_host.lower() == "smtp.reloop.sh" and (
            self.settings.smtp_port != 587 or values[2] != values[3]
        ):
            return False
        return bool(
            all(values)
            and self.settings.smtp_starttls
            and not any(any(ord(c) < 32 or ord(c) == 127 for c in v) for v in values)
        )

    async def send(self, recipient: str, subject: str, body: str) -> None:
        if not self.transport_configured():
            raise MailUnavailable("missing_configuration") from None
        if not self.configured():
            raise MailUnavailable("delivery_unverified") from None
        await self._submit(recipient, subject, body)

    async def acceptance_smoke(self, recipient: str) -> None:
        """Explicit operator test only; SMTP acceptance does not verify inbox delivery."""
        if not self.transport_configured():
            raise MailUnavailable("missing_configuration")
        if (
            len(recipient) > 254
            or recipient.count("@") != 1
            or not all(recipient.split("@"))
            or any(c.isspace() or ord(c) < 32 or c in ",;<>" for c in recipient)
        ):
            raise MailUnavailable("recipient_refused") from None
        await self._submit(
            recipient,
            "VASA SMTP acceptance test",
            "This is an operator-requested VASA SMTP test. "
            "Confirm receipt in the intended mailbox before enabling signup. "
            "This message contains no account tokens or customer data.",
        )

    async def _submit(self, recipient: str, subject: str, body: str) -> None:
        if not _DELIVERY_SLOTS.acquire(blocking=False):
            raise MailUnavailable("busy")
        try:
            task = asyncio.create_task(asyncio.to_thread(self._deliver, recipient, subject, body))
        except Exception:
            _DELIVERY_SLOTS.release()
            raise MailUnavailable() from None
        # Cancellation must not cancel queued executor work: only _deliver releases
        # its admission slot. Keep strong ownership until cleanup, even if the HTTP
        # request has gone away. At most four admitted deliveries can be retained.
        _DELIVERY_TASKS.add(task)

        def finished(completed: asyncio.Task[None]) -> None:
            _DELIVERY_TASKS.discard(completed)
            if not completed.cancelled():
                completed.exception()  # Retrieve sanitized background failure without logging.

        task.add_done_callback(finished)
        try:
            await asyncio.shield(task)
        except MailUnavailable:
            raise
        except Exception:
            raise MailUnavailable() from None

    def _deliver(self, recipient: str, subject: str, body: str) -> None:
        try:
            self._send(recipient, subject, body)
        except (TimeoutError, smtplib.SMTPServerDisconnected):
            raise MailUnavailable("timeout") from None
        except smtplib.SMTPAuthenticationError:
            raise MailUnavailable("authentication_failed") from None
        except (ssl.SSLError, smtplib.SMTPNotSupportedError):
            raise MailUnavailable("tls_failed") from None
        except smtplib.SMTPRecipientsRefused:
            raise MailUnavailable("recipient_refused") from None
        except (smtplib.SMTPConnectError, ConnectionError, OSError):
            raise MailUnavailable("connection_failed") from None
        except Exception:
            raise MailUnavailable("delivery_failed") from None
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
            if self.settings.smtp_username.get_secret_value():
                client.login(
                    self.settings.smtp_username.get_secret_value(),
                    self.settings.smtp_password.get_secret_value(),
                )
            if client.send_message(message):
                raise smtplib.SMTPRecipientsRefused({})
