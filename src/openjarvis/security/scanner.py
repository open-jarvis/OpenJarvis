"""Concrete security scanners — secrets and PII detection."""

from __future__ import annotations

import logging
import re
from typing import Dict, Tuple

from openjarvis import _rust_bridge
from openjarvis.security._stubs import BaseScanner
from openjarvis.security.types import ScanFinding, ScanResult, ThreatLevel

logger = logging.getLogger(__name__)


class _RegexScanner(BaseScanner):
    """Prefer the native scanner and fall back to equivalent Python regexes."""

    PATTERNS: Dict[str, Tuple[str, ThreatLevel, str]] = {}
    PYTHON_PATTERN_PREFIXES: Dict[str, str] = {}
    _rust_class_name = ""

    def __init__(self) -> None:
        self._patterns = [
            (
                name,
                re.compile(self.PYTHON_PATTERN_PREFIXES.get(name, "") + pattern),
                threat,
                description,
            )
            for name, (pattern, threat, description) in self.PATTERNS.items()
        ]
        self._rust_impl = None
        if _rust_bridge.RUST_AVAILABLE:
            try:
                rust_class = getattr(
                    _rust_bridge.get_rust_module(), self._rust_class_name
                )
                self._rust_impl = rust_class()
            except Exception:  # noqa: BLE001 - Python scanner remains available
                logger.warning(
                    "Rust %s unavailable; using Python fallback",
                    self.scanner_id,
                    exc_info=True,
                )

    @staticmethod
    def _valid_match(name: str, text: str, match: re.Match[str]) -> bool:
        if name != "ipv4_address":
            return True
        octets = match.group(0).split(".")
        if any(
            not octet.isascii() or not octet.isdigit() or int(octet) > 255
            for octet in octets
        ):
            return False
        start, end = match.span()
        joined_before = (
            start >= 2 and text[start - 1] == "." and text[start - 2] in "0123456789"
        )
        joined_after = (
            end + 1 < len(text) and text[end] == "." and text[end + 1] in "0123456789"
        )
        return not (joined_before or joined_after)

    def _scan_python(self, text: str) -> ScanResult:
        findings = []
        for name, regex, threat, description in self._patterns:
            for match in regex.finditer(text):
                if not self._valid_match(name, text, match):
                    continue
                findings.append(
                    ScanFinding(
                        pattern_name=name,
                        matched_text=match.group(0),
                        threat_level=threat,
                        start=match.start(),
                        end=match.end(),
                        description=description,
                    )
                )
        return ScanResult(findings=findings)

    def _redact_python(self, text: str) -> str:
        result = text
        for name, regex, _threat, _description in self._patterns:
            marker = f"[REDACTED:{name}]"

            def replace(match: re.Match[str]) -> str:
                if self._valid_match(name, result, match):
                    return marker
                return match.group(0)

            result = regex.sub(replace, result)
        return result

    def scan(self, text: str) -> ScanResult:
        """Scan *text* with Rust when available, otherwise use Python."""
        if self._rust_impl is not None:
            try:
                return _rust_bridge.scan_result_from_json(self._rust_impl.scan(text))
            except Exception:  # noqa: BLE001 - fail over to equivalent patterns
                logger.warning(
                    "Rust %s scan failed; using Python fallback",
                    self.scanner_id,
                    exc_info=True,
                )
                self._rust_impl = None
        return self._scan_python(text)

    def redact(self, text: str) -> str:
        """Redact *text* with Rust when available, otherwise use Python."""
        if self._rust_impl is not None:
            try:
                return self._rust_impl.redact(text)
            except Exception:  # noqa: BLE001 - fail over to equivalent patterns
                logger.warning(
                    "Rust %s redaction failed; using Python fallback",
                    self.scanner_id,
                    exc_info=True,
                )
                self._rust_impl = None
        return self._redact_python(text)


# ---------------------------------------------------------------------------
# SecretScanner
# ---------------------------------------------------------------------------


class SecretScanner(_RegexScanner):
    """Detect API keys, tokens, passwords, and other secrets in text."""

    scanner_id = "secrets"
    _rust_class_name = "SecretScanner"

    PATTERNS: Dict[str, Tuple[str, ThreatLevel, str]] = {
        "openai_key": (
            r"sk-[A-Za-z0-9_-]{20,}",
            ThreatLevel.CRITICAL,
            "OpenAI API key",
        ),
        "anthropic_key": (
            r"sk-ant-[A-Za-z0-9_-]{20,}",
            ThreatLevel.CRITICAL,
            "Anthropic API key",
        ),
        "aws_access_key": (
            r"AKIA[0-9A-Z]{16}",
            ThreatLevel.CRITICAL,
            "AWS access key",
        ),
        "github_token": (
            r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}",
            ThreatLevel.CRITICAL,
            "GitHub token",
        ),
        "password_assignment": (
            r"""(?:password|passwd|pwd)\s*[=:]\s*['"]([^'"]{4,})['"]""",
            ThreatLevel.HIGH,
            "Password assignment",
        ),
        "db_connection_string": (
            r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}",
            ThreatLevel.HIGH,
            "Database connection string",
        ),
        "private_key": (
            r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
            ThreatLevel.CRITICAL,
            "Private key",
        ),
        "slack_token": (
            r"xox[bpors]-[A-Za-z0-9\-]{10,}",
            ThreatLevel.HIGH,
            "Slack token",
        ),
        "stripe_key": (
            r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}",
            ThreatLevel.CRITICAL,
            "Stripe key",
        ),
        "generic_api_key": (
            r"""(?:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]""",
            ThreatLevel.HIGH,
            "Generic API key/secret",
        ),
    }


# ---------------------------------------------------------------------------
# PIIScanner
# ---------------------------------------------------------------------------


class PIIScanner(_RegexScanner):
    """Detect personally identifiable information in text."""

    scanner_id = "pii"
    _rust_class_name = "PIIScanner"

    # Python's backtracking regex engine otherwise retries the unbounded email
    # local-part at every character in long non-email input. Restricting starts
    # to the beginning of each local-part run preserves matches and linearizes
    # that adversarial case; Rust's regex engine does not need this guard.
    PYTHON_PATTERN_PREFIXES = {"email": r"(?<![a-zA-Z0-9._%+-])"}

    PATTERNS: Dict[str, Tuple[str, ThreatLevel, str]] = {
        "email": (
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            ThreatLevel.MEDIUM,
            "Email address",
        ),
        "us_ssn": (
            r"\b\d{3}-\d{2}-\d{4}\b",
            ThreatLevel.CRITICAL,
            "US Social Security Number",
        ),
        "credit_card_visa": (
            r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            ThreatLevel.CRITICAL,
            "Visa credit card",
        ),
        "credit_card_mastercard": (
            r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            ThreatLevel.CRITICAL,
            "Mastercard credit card",
        ),
        "credit_card_amex": (
            r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b",
            ThreatLevel.CRITICAL,
            "Amex credit card",
        ),
        "us_phone": (
            r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            ThreatLevel.MEDIUM,
            "US phone number",
        ),
        "ipv4_address": (
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            ThreatLevel.LOW,
            "IPv4 address",
        ),
    }


__all__ = ["PIIScanner", "SecretScanner"]
