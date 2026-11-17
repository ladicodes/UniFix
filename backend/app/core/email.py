"""Provider-agnostic outbound email.

``console`` (development/test only) writes messages to the log. ``smtp`` works with any
provider via standard SMTP settings. Nothing here is specific to one vendor.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.core.config import EmailBackend, Environment, Settings, SmtpTlsMode

logger = logging.getLogger("unifix.email")


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to: str
    subject: str
    text_body: str


class EmailSender(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


class ConsoleEmailSender:
    """Development/test sender: logs the message instead of delivering it."""

    async def send(self, message: OutgoingEmail) -> None:
        # Logged unredacted on purpose so developers can follow links; never used in production.
        logger.warning(
            "DEV EMAIL (not delivered) to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.text_body,
            extra={"dev_unredacted": True},
        )


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        assert settings.smtp_host is not None
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
        self._tls_mode = settings.smtp_tls_mode
        self._timeout = settings.smtp_timeout_seconds
        self._from = settings.email_from

    def build(self, message: OutgoingEmail) -> EmailMessage:
        email = EmailMessage()
        email["From"] = self._from
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.text_body)
        return email

    def _send_blocking(self, email: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._tls_mode is SmtpTlsMode.TLS:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout, context=context) as client:
                self._login_and_send(client, email)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
                client.starttls(context=context)
                self._login_and_send(client, email)

    def _login_and_send(self, client: smtplib.SMTP, email: EmailMessage) -> None:
        if self._username and self._password:
            client.login(self._username, self._password)
        client.send_message(email)

    async def send(self, message: OutgoingEmail) -> None:
        await asyncio.to_thread(self._send_blocking, self.build(message))


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend is EmailBackend.SMTP:
        return SmtpEmailSender(settings)
    if settings.env is Environment.PRODUCTION:  # also rejected by Settings validation
        raise RuntimeError("Console email is not allowed in production")
    return ConsoleEmailSender()


async def deliver(sender: EmailSender, message: OutgoingEmail) -> None:
    """Background-task entry point: failures are logged, never raised into the request."""
    try:
        await sender.send(message)
    except Exception:
        logger.exception("Email delivery failed (subject=%s)", message.subject)
