"""SMTP email send (stdlib smtplib).

Read-only IMAP is intentionally deferred — most ad-hoc agent flows
("send a confirmation email", "notify ops") only need the send path.

Configuration env vars:
    SMTP_USER     username / from-address
    SMTP_PASSWORD password or app-specific password
    SMTP_HOST     defaults to deriving from SMTP_USER's domain
    SMTP_PORT     default 587 (STARTTLS); set to 465 for implicit TLS
    SMTP_USE_TLS  default true; set to "false" for plaintext (don't!)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


class SMTPUnavailableError(RuntimeError):
    """Raised when SMTP credentials are missing or send fails."""


_GMAIL_HOSTS = {"gmail.com", "googlemail.com"}
_OUTLOOK_HOSTS = {"outlook.com", "hotmail.com", "live.com", "msn.com"}


def _infer_host(user: str) -> str:
    """Best-effort SMTP host inference from the user's domain."""
    if "@" not in user:
        return ""
    domain = user.rsplit("@", 1)[1].lower()
    if domain in _GMAIL_HOSTS:
        return "smtp.gmail.com"
    if domain in _OUTLOOK_HOSTS:
        return "smtp-mail.outlook.com"
    return f"smtp.{domain}"


def send_email(
    *,
    to: list[str] | str,
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    html: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> dict[str, str]:
    """Send a single email via SMTP. Returns a small status dict.

    Raises :class:`SMTPUnavailableError` on missing credentials or send
    failure (including auth errors). Caller is responsible for catching
    and degrading.
    """
    user = user or os.environ.get("SMTP_USER", "")
    password = password or os.environ.get("SMTP_PASSWORD", "")
    if not (user and password):
        raise SMTPUnavailableError(
            "SMTP not configured — set SMTP_USER and SMTP_PASSWORD"
        )

    host = host or os.environ.get("SMTP_HOST") or _infer_host(user)
    if not host:
        raise SMTPUnavailableError(
            "Could not infer SMTP host; set SMTP_HOST explicitly"
        )
    port = int(port or os.environ.get("SMTP_PORT", 587))
    use_tls = os.environ.get("SMTP_USE_TLS", "true").strip().lower() != "false"

    to_list = [to] if isinstance(to, str) else list(to)
    cc_list = list(cc) if cc else []
    bcc_list = list(bcc) if bcc else []
    all_recipients = [*to_list, *cc_list, *bcc_list]

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg, from_addr=user, to_addrs=all_recipients)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                if use_tls:
                    s.starttls(context=ctx)
                s.login(user, password)
                s.send_message(msg, from_addr=user, to_addrs=all_recipients)
    except (smtplib.SMTPException, OSError) as exc:
        raise SMTPUnavailableError(f"SMTP send failed: {exc}") from exc

    return {
        "status": "sent",
        "from": user,
        "to": ",".join(to_list),
        "subject": subject,
    }


__all__ = ["send_email", "SMTPUnavailableError"]
