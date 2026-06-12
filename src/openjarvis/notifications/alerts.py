"""Outbound alert helpers — email (SMTP), SMS (Twilio), push (ntfy/Pushover).

These are small, dependency-light helpers designed for *alerting* (one-way
notifications), distinct from the richer two-way ``channels`` adapters. Every
function:

* reads its settings from environment variables (load a ``.env`` first with
  :func:`load_env_file` if you keep secrets in a file),
* applies a network timeout so a slow provider can never hang the app,
* catches all errors and returns a :class:`NotificationResult` instead of
  raising, so a failed alert never crashes the caller, and
* never logs or returns secret values (passwords, tokens, API keys).

Environment variables
---------------------
Email:   EMAIL_FROM, EMAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
SMS:     TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, MY_PHONE_NUMBER
Push:    NTFY_TOPIC (+ optional NTFY_SERVER, NTFY_TOKEN)
         or PUSHOVER_TOKEN + PUSHOVER_USER (fallback when no NTFY_TOPIC)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Network timeout (seconds) shared by every provider call.
_TIMEOUT = 15.0
_TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
_NTFY_DEFAULT_SERVER = "https://ntfy.sh"
_PUSHOVER_API = "https://api.pushover.net/1/messages.json"


# ---------------------------------------------------------------------------
# Result + secret-safety helpers
# ---------------------------------------------------------------------------
@dataclass
class NotificationResult:
    """Outcome of one alert send. Never carries secret values."""

    channel: str
    success: bool
    detail: str = ""
    error: str = ""

    def __bool__(self) -> bool:  # truthy iff the send succeeded
        return self.success


def _mask(value: str) -> str:
    """Mask a secret for safe display: keep last 2 chars, redact the rest.

    Used only for *non-secret* diagnostics (e.g. confirming a topic/number is
    set). Secrets like passwords/tokens are never passed through here for
    output — they are only ever checked for presence.
    """
    if not value:
        return "(unset)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 2)}{value[-2:]}"


def _missing(names: Sequence[str]) -> List[str]:
    """Return the subset of env var *names* that are unset/empty."""
    return [n for n in names if not os.environ.get(n, "").strip()]


def load_env_file(path: str | os.PathLike[str] = ".env") -> int:
    """Load ``KEY=VALUE`` pairs from a ``.env`` file into ``os.environ``.

    Minimal, stdlib-only loader (no python-dotenv dependency). Existing
    environment variables always win, so real deployment secrets are never
    overwritten by a checked-in file. Returns the number of keys set.
    Missing file is not an error (returns 0).
    """
    p = Path(path)
    if not p.is_file():
        return 0
    loaded = 0
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[len("export ") :].lstrip()
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
    except OSError as exc:
        logger.warning("Could not read env file %s: %s", p, exc)
    return loaded


# ---------------------------------------------------------------------------
# Email (SMTP, stdlib only)
# ---------------------------------------------------------------------------
def send_email_alert(
    subject: str,
    message: str,
    *,
    to: Optional[str] = None,
) -> NotificationResult:
    """Send an email alert over SMTP.

    Uses ``SMTP_PORT`` to decide transport: 465 → implicit TLS (SMTP_SSL),
    anything else → STARTTLS. Credentials are optional (relay servers may not
    need them). The password is never logged.
    """
    missing = _missing(["SMTP_HOST", "EMAIL_FROM"])
    sender = os.environ.get("EMAIL_FROM", "").strip()
    recipient = (to or os.environ.get("EMAIL_TO", "")).strip()
    if not recipient:
        missing.append("EMAIL_TO")
    if missing:
        return NotificationResult(
            "email", False,
            error=f"Email not configured. Set: {', '.join(sorted(set(missing)))}",
        )

    host = os.environ["SMTP_HOST"].strip()
    try:
        port = int(os.environ.get("SMTP_PORT", "587").strip() or "587")
    except ValueError:
        port = 587
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject or "(no subject)"
    msg.set_content(message or "")

    try:
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT, context=context) as srv:
                if username:
                    srv.login(username, password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=_TIMEOUT) as srv:
                srv.starttls(context=context)
                if username:
                    srv.login(username, password)
                srv.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        # Deliberately do not echo the server message (can include the account).
        return NotificationResult(
            "email", False,
            error="SMTP authentication failed. Check SMTP_USERNAME / SMTP_PASSWORD.",
        )
    except Exception as exc:  # noqa: BLE001 - never let an alert crash the app
        logger.debug("email alert failed: %s", type(exc).__name__)
        return NotificationResult(
            "email", False, error=f"Email send failed: {type(exc).__name__}: {exc}"
        )

    return NotificationResult("email", True, detail=f"Sent to {recipient}")


# ---------------------------------------------------------------------------
# SMS (Twilio REST API via httpx — no twilio package needed)
# ---------------------------------------------------------------------------
def send_sms_alert(message: str, *, to: Optional[str] = None) -> NotificationResult:
    """Send an SMS alert through Twilio's REST API.

    Calls the REST endpoint directly with HTTP basic auth so the heavy
    ``twilio`` SDK is not required. The auth token is never logged.
    """
    missing = _missing(
        ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"]
    )
    recipient = (to or os.environ.get("MY_PHONE_NUMBER", "")).strip()
    if not recipient:
        missing.append("MY_PHONE_NUMBER")
    if missing:
        return NotificationResult(
            "sms", False,
            error=f"SMS not configured. Set: {', '.join(sorted(set(missing)))}",
        )

    try:
        import httpx
    except ImportError:
        return NotificationResult(
            "sms", False, error="httpx is required for SMS alerts (pip install httpx)."
        )

    sid = os.environ["TWILIO_ACCOUNT_SID"].strip()
    token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_FROM_NUMBER"].strip()

    try:
        resp = httpx.post(
            _TWILIO_API.format(sid=sid),
            auth=(sid, token),
            data={"From": from_number, "To": recipient, "Body": message or ""},
            timeout=_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("sms alert transport error: %s", type(exc).__name__)
        return NotificationResult(
            "sms", False, error=f"SMS send failed: {type(exc).__name__}: {exc}"
        )

    if resp.status_code in (200, 201):
        return NotificationResult("sms", True, detail=f"Sent to {recipient}")

    # Surface Twilio's error message but never the auth token.
    detail = ""
    try:
        detail = str(resp.json().get("message", "")).strip()
    except Exception:  # noqa: BLE001
        detail = resp.text[:200]
    return NotificationResult(
        "sms", False,
        error=f"Twilio returned HTTP {resp.status_code}: {detail or 'unknown error'}",
    )


# ---------------------------------------------------------------------------
# Push (ntfy preferred, Pushover fallback)
# ---------------------------------------------------------------------------
def send_push_alert(title: str, message: str) -> NotificationResult:
    """Send a push notification.

    Prefers ntfy (set ``NTFY_TOPIC``) because it needs no account. Falls back
    to Pushover when ``NTFY_TOPIC`` is unset but ``PUSHOVER_TOKEN`` /
    ``PUSHOVER_USER`` are present.
    """
    try:
        import httpx
    except ImportError:
        return NotificationResult(
            "push", False,
            error="httpx is required for push alerts (pip install httpx).",
        )

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if topic:
        return _send_ntfy(httpx, topic, title, message)

    if os.environ.get("PUSHOVER_TOKEN", "").strip() and os.environ.get(
        "PUSHOVER_USER", ""
    ).strip():
        return _send_pushover(httpx, title, message)

    return NotificationResult(
        "push", False,
        error="Push not configured. Set NTFY_TOPIC (recommended) "
        "or PUSHOVER_TOKEN + PUSHOVER_USER.",
    )


def _send_ntfy(httpx, topic: str, title: str, message: str) -> NotificationResult:  # noqa: ANN001
    server = os.environ.get("NTFY_SERVER", _NTFY_DEFAULT_SERVER).strip().rstrip("/")
    headers: Dict[str, str] = {}
    if title:
        # Header must be latin-1 encodable; fall back to the body otherwise.
        try:
            title.encode("latin-1")
            headers["Title"] = title
        except UnicodeEncodeError:
            message = f"{title}\n\n{message}"
    token = os.environ.get("NTFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.post(
            f"{server}/{topic}",
            content=(message or "").encode("utf-8"),
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.debug("ntfy push failed: %s", type(exc).__name__)
        return NotificationResult(
            "push", False, error=f"ntfy send failed: {type(exc).__name__}: {exc}"
        )
    return NotificationResult("push", True, detail=f"ntfy topic '{topic}'")


def _send_pushover(httpx, title: str, message: str) -> NotificationResult:  # noqa: ANN001
    try:
        resp = httpx.post(
            _PUSHOVER_API,
            data={
                "token": os.environ["PUSHOVER_TOKEN"].strip(),
                "user": os.environ["PUSHOVER_USER"].strip(),
                "title": title or "",
                "message": message or "",
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.debug("pushover push failed: %s", type(exc).__name__)
        return NotificationResult(
            "push", False, error=f"Pushover send failed: {type(exc).__name__}: {exc}"
        )
    return NotificationResult("push", True, detail="Pushover")


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------
def send_alert(
    title: str,
    message: str,
    *,
    channels: Sequence[str] = ("push",),
) -> Dict[str, NotificationResult]:
    """Send the same alert across one or more channels.

    ``channels`` may include any of ``"email"``, ``"sms"``, ``"push"``, or the
    special value ``"all"``. For email, ``title`` is the subject. SMS combines
    title + message into one body. Returns a ``{channel: NotificationResult}``
    map; unconfigured channels simply report a failure result (no exception).
    """
    requested = ["email", "sms", "push"] if "all" in channels else list(
        dict.fromkeys(channels)
    )
    results: Dict[str, NotificationResult] = {}
    for ch in requested:
        if ch == "email":
            results[ch] = send_email_alert(title, message)
        elif ch == "sms":
            body = f"{title}: {message}" if title else message
            results[ch] = send_sms_alert(body)
        elif ch == "push":
            results[ch] = send_push_alert(title, message)
        else:
            results[ch] = NotificationResult(
                ch, False, error=f"Unknown channel '{ch}'."
            )
    return results


__all__ = [
    "NotificationResult",
    "load_env_file",
    "send_email_alert",
    "send_sms_alert",
    "send_push_alert",
    "send_alert",
]
