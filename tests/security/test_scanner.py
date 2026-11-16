"""Tests for SecretScanner and PIIScanner."""

from __future__ import annotations

import subprocess
import sys
from collections import Counter

import pytest

import openjarvis.security.scanner as scanner_module
from openjarvis.security.scanner import PIIScanner, SecretScanner
from openjarvis.security.types import ThreatLevel


@pytest.mark.parametrize("scanner_class", [SecretScanner, PIIScanner])
@pytest.mark.parametrize(
    "text",
    [
        "ordinary text without sensitive values",
        "sk-" + "a" * 24 + " sk-ant-" + "b" * 24,
        "AKIA" + "A" * 16 + " ghp_" + "x" * 36,
        "xoxb-1234567890abcdef sk_test_" + "a" * 24,
        "password = 'example-password' api_key='example-api-token'",
        "postgres://user:password@db.example/database",
        "-----BEGIN RSA PRIVATE KEY-----",
        "email first.last+tag@example.com and first.last+tag@example.com",
        "🙂 user@example.com 001.002.003.004 8.8.8.8 192.168.1.1",
        "invalid 999.1.1.1 and version 1.2.3.4.5 and ١.٢.٣.٤",
        "123-45-6789 4242 4242 4242 4242 202-555-0123",
    ],
)
def test_fallback_matches_native_findings_and_redaction(
    scanner_class, text, monkeypatch
):
    if not scanner_module._rust_bridge.RUST_AVAILABLE:
        pytest.skip("Native comparison requires the Rust extension")
    native = scanner_class()
    assert native._rust_impl is not None
    monkeypatch.setattr(scanner_module._rust_bridge, "RUST_AVAILABLE", False)
    fallback = scanner_class()

    def findings(scanner):
        return Counter(
            (f.pattern_name, f.matched_text, f.threat_level)
            for f in scanner.scan(text).findings
        )

    assert findings(fallback) == findings(native)
    assert fallback.redact(text) == native.redact(text)


@pytest.mark.parametrize("scanner_class", [SecretScanner, PIIScanner])
@pytest.mark.parametrize("operation", ["scan", "redact"])
def test_native_failure_does_not_log_the_scanned_payload(
    scanner_class, operation, caplog
):
    key = "sk-" + "a" * 24
    email = "private-user@example.com"
    text = f"key {key} email {email}"

    class BrokenNative:
        def scan(self, value):
            raise RuntimeError(value)

        def redact(self, value):
            raise RuntimeError(value)

    scanner = scanner_class()
    scanner._rust_impl = BrokenNative()
    result = getattr(scanner, operation)(text)
    if operation == "scan":
        assert not result.clean
    else:
        sensitive = key if scanner_class is SecretScanner else email
        assert sensitive not in result
    assert "using Python fallback" in caplog.text
    assert key not in caplog.text
    assert email not in caplog.text


def test_long_non_email_input_does_not_stall_the_fallback():
    code = """\
from openjarvis import _rust_bridge
_rust_bridge.RUST_AVAILABLE = False
from openjarvis.security.scanner import PIIScanner
assert PIIScanner().scan('a' * 100000).clean
"""
    subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, timeout=10
    )


# ---------------------------------------------------------------------------
# SecretScanner tests
# ---------------------------------------------------------------------------


class TestSecretScanner:
    def test_python_fallback_without_rust(self, monkeypatch) -> None:
        monkeypatch.setattr(scanner_module._rust_bridge, "RUST_AVAILABLE", False)

        scanner = SecretScanner()
        text = "my key is sk-abc123def456ghi789jkl012"

        result = scanner.scan(text)

        assert not result.clean
        assert result.findings[0].pattern_name == "openai_key"
        assert scanner.redact(text) == "my key is [REDACTED:openai_key]"

    def test_python_fallback_after_native_scan_failure(
        self, monkeypatch, caplog
    ) -> None:
        class BrokenNativeScanner:
            def scan(self, text: str) -> str:
                raise RuntimeError("native scanner failed")

        class FakeRustModule:
            SecretScanner = BrokenNativeScanner

        monkeypatch.setattr(scanner_module._rust_bridge, "RUST_AVAILABLE", True)
        monkeypatch.setattr(
            scanner_module._rust_bridge,
            "get_rust_module",
            lambda: FakeRustModule,
        )

        scanner = SecretScanner()
        result = scanner.scan("key sk-abc123def456ghi789jkl012")

        assert not result.clean
        assert result.findings[0].pattern_name == "openai_key"
        assert scanner._rust_impl is None
        assert "using Python fallback" in caplog.text

    def test_secret_scanner_openai_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("my key is sk-abc123def456ghi789jkl012")
        assert not result.clean
        assert any(f.pattern_name == "openai_key" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.CRITICAL for f in result.findings)

    def test_secret_scanner_anthropic_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("key=sk-ant-abc123def456ghi789jkl012")
        assert not result.clean
        assert any(f.pattern_name == "anthropic_key" for f in result.findings)

    def test_secret_scanner_aws_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("AKIA1234567890ABCDEF")
        assert not result.clean
        assert any(f.pattern_name == "aws_access_key" for f in result.findings)

    def test_secret_scanner_github_token(self) -> None:
        scanner = SecretScanner()
        token = "ghp_" + "a" * 36
        result = scanner.scan(f"token = {token}")
        assert not result.clean
        assert any(f.pattern_name == "github_token" for f in result.findings)

    def test_secret_scanner_private_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        assert not result.clean
        assert any(f.pattern_name == "private_key" for f in result.findings)

    def test_secret_scanner_password(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan('password = "mysecretpass"')
        assert not result.clean
        assert any(f.pattern_name == "password_assignment" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.HIGH for f in result.findings)

    def test_secret_scanner_db_string(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("postgres://user:pass@host:5432/mydb")
        assert not result.clean
        assert any(f.pattern_name == "db_connection_string" for f in result.findings)

    def test_secret_scanner_clean(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("This is a perfectly normal text with no secrets.")
        assert result.clean
        assert result.highest_threat is None

    def test_secret_scanner_redact(self) -> None:
        scanner = SecretScanner()
        text = "my key is sk-abc123def456ghi789jkl012"
        redacted = scanner.redact(text)
        assert "[REDACTED:openai_key]" in redacted
        assert "sk-abc123" not in redacted

    def test_secret_scanner_slack_token(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("slack: xoxb-123456789-abcde")
        assert not result.clean
        assert any(f.pattern_name == "slack_token" for f in result.findings)

    def test_secret_scanner_stripe_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("sk_test_abcdefghijklmnopqrst")
        assert not result.clean
        assert any(f.pattern_name == "stripe_key" for f in result.findings)

    def test_secret_scanner_generic_api_key(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan('api_key = "my_super_secret_key_1234"')
        assert not result.clean
        assert any(f.pattern_name == "generic_api_key" for f in result.findings)


# ---------------------------------------------------------------------------
# PIIScanner tests
# ---------------------------------------------------------------------------


class TestPIIScanner:
    def test_python_fallback_without_rust(self, monkeypatch) -> None:
        monkeypatch.setattr(scanner_module._rust_bridge, "RUST_AVAILABLE", False)

        scanner = PIIScanner()
        text = "email user@example.com from 8.8.8.8"

        result = scanner.scan(text)

        assert {finding.pattern_name for finding in result.findings} == {
            "email",
            "ipv4_address",
        }
        assert scanner.redact(text) == (
            "email [REDACTED:email] from [REDACTED:ipv4_address]"
        )

    def test_pii_scanner_email(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("contact me at user@example.com please")
        assert not result.clean
        assert any(f.pattern_name == "email" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.MEDIUM for f in result.findings)

    def test_pii_scanner_email_starts_at_full_local_part(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("contact first.last+tag@example.com")
        email = next(f for f in result.findings if f.pattern_name == "email")
        assert email.matched_text == "first.last+tag@example.com"

    def test_pii_scanner_ssn(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("My SSN is 123-45-6789")
        assert not result.clean
        assert any(f.pattern_name == "us_ssn" for f in result.findings)
        assert any(f.threat_level == ThreatLevel.CRITICAL for f in result.findings)

    def test_pii_scanner_visa(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("card: 4111 1111 1111 1111")
        assert not result.clean
        assert any(f.pattern_name == "credit_card_visa" for f in result.findings)

    def test_pii_scanner_mastercard(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("card: 5111 1111 1111 1111")
        assert not result.clean
        assert any(f.pattern_name == "credit_card_mastercard" for f in result.findings)

    def test_pii_scanner_amex(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("card: 3411 123456 12345")
        assert not result.clean
        assert any(f.pattern_name == "credit_card_amex" for f in result.findings)

    def test_pii_scanner_phone(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("Call me at (555) 123-4567")
        assert not result.clean
        assert any(f.pattern_name == "us_phone" for f in result.findings)

    def test_pii_scanner_clean(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("This is a perfectly normal text with no PII.")
        assert result.clean

    def test_pii_scanner_redact(self) -> None:
        scanner = PIIScanner()
        text = "email me at user@example.com"
        redacted = scanner.redact(text)
        assert "[REDACTED:email]" in redacted
        assert "user@example.com" not in redacted

    def test_pii_scanner_ssn_redact(self) -> None:
        scanner = PIIScanner()
        text = "SSN: 123-45-6789"
        redacted = scanner.redact(text)
        assert "[REDACTED:us_ssn]" in redacted
        assert "123-45-6789" not in redacted

    def test_pii_scanner_public_ipv4_redacted(self) -> None:
        scanner = PIIScanner()
        assert not scanner.scan("server at 8.8.8.8 is up").clean
        assert scanner.redact("ping 8.8.8.8") == "ping [REDACTED:ipv4_address]"

    def test_pii_scanner_ipv4_ignores_long_dotted_numbers(self) -> None:
        scanner = PIIScanner()
        # 20! written with European thousands separators is not an IP address.
        text = "20! = 2.432.902.008.176.640.000"
        assert scanner.scan(text).clean
        assert scanner.redact(text) == text

    def test_pii_scanner_ipv4_rejects_out_of_range_octets(self) -> None:
        scanner = PIIScanner()
        assert scanner.scan("version 999.1.1.1").clean
        assert scanner.scan("build 1.2.3.4.5").clean

    def test_pii_scanner_ipv4_rejects_unicode_digits(self) -> None:
        scanner = PIIScanner()
        text = "not an IPv4 address: ١.٢.٣.٤"
        assert scanner.scan(text).clean
        assert scanner.redact(text) == text


# ---------------------------------------------------------------------------
# ScanResult property tests
# ---------------------------------------------------------------------------


class TestScanResult:
    def test_highest_threat_critical(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("sk-abc123def456ghi789jkl012")
        assert result.highest_threat == ThreatLevel.CRITICAL

    def test_highest_threat_none_when_clean(self) -> None:
        scanner = SecretScanner()
        result = scanner.scan("clean text")
        assert result.highest_threat is None

    def test_multiple_findings(self) -> None:
        scanner = SecretScanner()
        text = 'password = "secret123" and key sk-abc123def456ghi789jkl012'
        result = scanner.scan(text)
        assert len(result.findings) >= 2
