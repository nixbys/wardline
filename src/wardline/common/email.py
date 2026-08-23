"""Outbound transactional email — verification links, password resets,
invites (governance/accounts.py is the only caller).

`EMAIL_MODE=mock` (default) logs the message instead of sending it, exactly
this project's existing `LLM_CLIENT_MODE=mock` convention: local dev and CI
never need real SMTP credentials, and every account flow that "sends" mail
during a unit/integration test run is fully exercised without touching a
network. Set `EMAIL_MODE=smtp` + the `SMTP_*` settings to send for real
against any standard provider (Postmark, SES, Sendgrid, ...) — nothing here
is provider-specific.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from wardline.common.config import get_settings
from wardline.common.logging import get_logger

logger = get_logger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_mode != "smtp":
        logger.info("email.mock_send", to=to, subject=subject, body=body)
        return

    if not settings.smtp_host:
        raise RuntimeError("EMAIL_MODE=smtp requires SMTP_HOST to be set")

    message = EmailMessage()
    message["From"] = settings.email_from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)
