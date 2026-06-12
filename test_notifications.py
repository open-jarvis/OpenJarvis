#!/usr/bin/env python3
"""Manual smoke test for OpenJarvis notifications.

Loads ``.env`` (if present), then sends ONE test email, ONE test SMS, and ONE
test push notification. Prints a clean PASS/SKIP/FAIL line per channel.

    python test_notifications.py                # try all three channels
    python test_notifications.py email push     # only the named channels

Channels with missing configuration are reported as SKIP (not FAIL), so you can
set up one provider at a time. Secrets are never printed — only a masked hint of
which settings were detected.
"""

from __future__ import annotations

import os
import sys

# Make the package importable when run from the repo root without install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from openjarvis.notifications import (  # noqa: E402
    load_env_file,
    send_email_alert,
    send_push_alert,
    send_sms_alert,
)


def _mask(name: str) -> str:
    """Show only whether a secret is set, plus a 2-char tail — never the value."""
    val = os.environ.get(name, "")
    if not val:
        return f"{name}=(unset)"
    if len(val) <= 4:
        return f"{name}=set"
    return f"{name}=…{val[-2:]}"


def _configured(names: list[str]) -> bool:
    return all(os.environ.get(n, "").strip() for n in names)


def main(argv: list[str]) -> int:
    loaded = load_env_file(".env")
    if loaded:
        print(f"Loaded {loaded} setting(s) from .env\n")
    else:
        print("No .env loaded (using existing environment)\n")

    selected = [a.lower() for a in argv[1:]] or ["email", "sms", "push"]
    statuses: dict[str, str] = {}

    if "email" in selected:
        required = ["SMTP_HOST", "EMAIL_FROM", "EMAIL_TO"]
        shown = required + ["SMTP_USERNAME"]
        print("[email] config:", ", ".join(_mask(n) for n in shown))
        if not _configured(required):
            statuses["email"] = "SKIP (not configured)"
        else:
            res = send_email_alert(
                "OpenJarvis test email",
                "This is a test email alert from test_notifications.py.",
            )
            statuses["email"] = f"PASS — {res.detail}" if res else f"FAIL — {res.error}"
        print()

    if "sms" in selected:
        required = [
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_FROM_NUMBER",
            "MY_PHONE_NUMBER",
        ]
        print("[sms] config:", ", ".join(_mask(n) for n in required))
        if not _configured(required):
            statuses["sms"] = "SKIP (not configured)"
        else:
            res = send_sms_alert("OpenJarvis test SMS from test_notifications.py.")
            statuses["sms"] = f"PASS — {res.detail}" if res else f"FAIL — {res.error}"
        print()

    if "push" in selected:
        ntfy = bool(os.environ.get("NTFY_TOPIC", "").strip())
        pushover = _configured(["PUSHOVER_TOKEN", "PUSHOVER_USER"])
        print("[push] config:", _mask("NTFY_TOPIC"),
              "| pushover:", "set" if pushover else "(unset)")
        if not (ntfy or pushover):
            statuses["push"] = "SKIP (not configured)"
        else:
            res = send_push_alert(
                "OpenJarvis", "This is a test push notification."
            )
            statuses["push"] = f"PASS — {res.detail}" if res else f"FAIL — {res.error}"
        print()

    print("=" * 56)
    print("NOTIFICATION TEST RESULTS")
    print("=" * 56)
    for ch in selected:
        print(f"  {ch:<6} {statuses.get(ch, 'SKIP')}")
    print("=" * 56)

    # Non-zero exit only if a configured channel actually FAILED.
    return 1 if any(s.startswith("FAIL") for s in statuses.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
