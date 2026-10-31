"""SMTP sending for generic IMAP accounts.

SMTP is blocking; all calls run in a worker thread so the event loop stays
responsive. Credentials are never logged.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from nexapilot.core.errors import ConfigurationError, IntegrationError


class SmtpClient:
    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str,
        password: str,
        use_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        if not host or not username:
            raise ConfigurationError(
                "SMTP is not configured for this account.",
                setup_hint="Add the SMTP host and port when connecting the IMAP account.",
            )
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.timeout = timeout

    async def send_message(self, *, to: list[str], subject: str, body: str) -> str:
        message = EmailMessage()
        message["From"] = self.username
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=self.username.split("@")[-1] or "nexapilot.local")
        message.set_content(body)
        try:
            await asyncio.to_thread(self._send_sync, message)
        except (smtplib.SMTPException, OSError) as exc:
            raise IntegrationError(
                f"The mail server rejected the message: {type(exc).__name__}",
                details={"host": self.host, "port": self.port},
            ) from exc
        return str(message["Message-ID"])

    def _send_sync(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self.use_ssl:
            with smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            ) as server:
                server.login(self.username, self.password)
                server.send_message(message)
            return
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
            server.login(self.username, self.password)
            server.send_message(message)
