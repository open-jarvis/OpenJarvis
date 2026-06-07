"""Tests for outbound alert helpers — fully mocked, no real network or secrets."""

from __future__ import annotations

import sys
import types

import pytest

from openjarvis.notifications import alerts


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Start every test from a clean slate for all alert-related env vars."""
    for key in [
        "EMAIL_FROM", "EMAIL_TO", "SMTP_HOST", "SMTP_PORT",
        "SMTP_USERNAME", "SMTP_PASSWORD",
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
        "MY_PHONE_NUMBER",
        "NTFY_TOPIC", "NTFY_SERVER", "NTFY_TOKEN",
        "PUSHOVER_TOKEN", "PUSHOVER_USER",
    ]:
        monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# Unconfigured channels fail cleanly (never raise) and don't leak secret names
# ---------------------------------------------------------------------------
def test_email_unconfigured_returns_clean_failure():
    res = alerts.send_email_alert("hi", "body")
    assert res.success is False
    assert "Email not configured" in res.error
    assert "SMTP_HOST" in res.error


def test_sms_unconfigured_returns_clean_failure():
    res = alerts.send_sms_alert("body")
    assert res.success is False
    assert "SMS not configured" in res.error


def test_push_unconfigured_returns_clean_failure():
    res = alerts.send_push_alert("t", "m")
    assert res.success is False
    assert "Push not configured" in res.error


# ---------------------------------------------------------------------------
# Email via mocked smtplib
# ---------------------------------------------------------------------------
def test_email_starttls_path(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            sent["starttls"] = True

        def login(self, user, pw):
            sent["login"] = user

        def send_message(self, msg):
            sent["to"] = msg["To"]
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("EMAIL_TO", "to@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "supersecret")

    res = alerts.send_email_alert("Subject", "Body")
    assert res.success is True
    assert sent["starttls"] is True
    assert sent["to"] == "to@example.com"
    assert sent["subject"] == "Subject"
    # the password must never appear in the result
    assert "supersecret" not in (res.detail + res.error)


def test_email_ssl_port_465(monkeypatch):
    used = {}

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout=None, context=None):
            used["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, pw):
            pass

        def send_message(self, msg):
            used["sent"] = True

    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("EMAIL_TO", "to@example.com")

    res = alerts.send_email_alert("S", "B")
    assert res.success is True
    assert used["port"] == 465
    assert used["sent"] is True


def test_email_failure_is_caught(monkeypatch):
    class BoomSMTP:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(alerts.smtplib, "SMTP", BoomSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "from@example.com")
    monkeypatch.setenv("EMAIL_TO", "to@example.com")

    res = alerts.send_email_alert("S", "B")
    assert res.success is False
    assert "Email send failed" in res.error


# ---------------------------------------------------------------------------
# SMS + push via a fake httpx module
# ---------------------------------------------------------------------------
def _install_fake_httpx(monkeypatch, *, status=201, payload=None, capture=None):
    class FakeResp:
        def __init__(self):
            self.status_code = status
            self.text = "ok"

        def json(self):
            return payload or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    fake = types.ModuleType("httpx")

    def post(url, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture["kwargs"] = kwargs
        return FakeResp()

    fake.post = post
    monkeypatch.setitem(sys.modules, "httpx", fake)


def test_sms_success(monkeypatch):
    cap = {}
    _install_fake_httpx(monkeypatch, status=201, capture=cap)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok-secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    monkeypatch.setenv("MY_PHONE_NUMBER", "+15551234567")

    res = alerts.send_sms_alert("hello")
    assert res.success is True
    assert cap["kwargs"]["data"]["To"] == "+15551234567"
    # auth token must never be echoed in the result
    assert "tok-secret" not in (res.detail + res.error)


def test_sms_provider_error(monkeypatch):
    _install_fake_httpx(
        monkeypatch, status=400, payload={"message": "bad number"}
    )
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    monkeypatch.setenv("MY_PHONE_NUMBER", "+15551234567")

    res = alerts.send_sms_alert("hello")
    assert res.success is False
    assert "HTTP 400" in res.error
    assert "bad number" in res.error


def test_push_ntfy_success(monkeypatch):
    cap = {}
    _install_fake_httpx(monkeypatch, status=200, capture=cap)
    monkeypatch.setenv("NTFY_TOPIC", "my-secret-topic")

    res = alerts.send_push_alert("Title", "Message")
    assert res.success is True
    assert cap["url"].endswith("/my-secret-topic")
    assert cap["kwargs"]["headers"]["Title"] == "Title"


def test_push_pushover_fallback(monkeypatch):
    cap = {}
    _install_fake_httpx(monkeypatch, status=200, capture=cap)
    monkeypatch.setenv("PUSHOVER_TOKEN", "ptok")
    monkeypatch.setenv("PUSHOVER_USER", "puser")

    res = alerts.send_push_alert("Title", "Message")
    assert res.success is True
    assert "pushover" in cap["url"]


# ---------------------------------------------------------------------------
# Dispatcher + .env loader
# ---------------------------------------------------------------------------
def test_send_alert_dispatch(monkeypatch):
    _install_fake_httpx(monkeypatch, status=200)
    monkeypatch.setenv("NTFY_TOPIC", "topic")

    results = alerts.send_alert("T", "M", channels=["push", "email"])
    assert results["push"].success is True
    assert results["email"].success is False  # email not configured


def test_load_env_file_does_not_override_existing(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nNTFY_TOPIC=from-file\nEMAIL_FROM=a@b.com\n", encoding="utf-8"
    )
    monkeypatch.setenv("NTFY_TOPIC", "already-set")

    count = alerts.load_env_file(env)
    assert count == 1  # only EMAIL_FROM was set; NTFY_TOPIC kept its value
    import os
    assert os.environ["NTFY_TOPIC"] == "already-set"
    assert os.environ["EMAIL_FROM"] == "a@b.com"


def test_load_env_file_missing_is_noop(tmp_path):
    assert alerts.load_env_file(tmp_path / "nope.env") == 0
