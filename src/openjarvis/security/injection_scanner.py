"""Prompt injection scanner — detect malicious patterns in text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from openjarvis.security.types import ScanFinding, ThreatLevel

# Threat level ordering for comparison
_THREAT_ORDER = [
    ThreatLevel.LOW,
    ThreatLevel.MEDIUM,
    ThreatLevel.HIGH,
    ThreatLevel.CRITICAL,
]

# Injection patterns: (regex, name, threat_level, description)
_INJECTION_PATTERNS = [
    # System prompt override attempts
    (
        r"(?i)ignore\s+(all\s+)?(previous|prior|above)"
        r"\s+(instructions?|prompts?|rules?)",
        "prompt_override",
        ThreatLevel.HIGH,
        "Attempt to override system instructions",
    ),
    (
        r"(?i)you\s+are\s+now\s+(?:a\s+)?(?:different|new|my)",
        "identity_override",
        ThreatLevel.HIGH,
        "Attempt to change AI identity",
    ),
    (
        r"(?i)disregard\s+(?:all\s+)?(?:previous|prior|your)"
        r"\s+(?:instructions?|programming|rules?)",
        "prompt_override",
        ThreatLevel.HIGH,
        "Attempt to disregard instructions",
    ),
    # Shell/code injection via prompt
    (
        r"(?i)(?:execute|run|eval)\s*\(\s*['\"]",
        "code_injection",
        ThreatLevel.HIGH,
        "Code execution attempt in prompt",
    ),
    (
        r"(?:;|\||&&)\s*(?:rm|curl|wget|nc|ncat"
        r"|bash|sh|python|perl)\s",
        "shell_injection",
        ThreatLevel.HIGH,
        "Shell command injection",
    ),
    # Data exfiltration
    (
        r"(?i)(?:send|post|upload|exfiltrate|transmit)"
        r"\s+(?:(?:to|data|all|everything)\s+)*"
        r"(?:to\s+)?(?:https?://|my\s+server)",
        "exfiltration",
        ThreatLevel.HIGH,
        "Data exfiltration attempt",
    ),
    (
        r"(?i)base64\s+encode\s+(?:and\s+)?"
        r"(?:send|include|append)",
        "exfiltration",
        ThreatLevel.MEDIUM,
        "Encoded exfiltration attempt",
    ),
    # Jailbreak patterns
    (
        r"(?i)(?:DAN|do\s+anything\s+now)"
        r"\s+(?:mode|prompt|jailbreak)",
        "jailbreak",
        ThreatLevel.HIGH,
        "DAN jailbreak attempt",
    ),
    (
        r"(?i)pretend\s+(?:you\s+)?(?:have\s+)?no"
        r"\s+(?:restrictions?|limitations?|rules?|filters?)",
        "jailbreak",
        ThreatLevel.MEDIUM,
        "Restriction bypass attempt",
    ),
    # Delimiter injection
    (
        r"```(?:system|assistant)\b",
        "delimiter_injection",
        ThreatLevel.MEDIUM,
        "Role delimiter injection",
    ),
    (
        r"<\|(?:im_start|im_end|system|assistant)\|>",
        "delimiter_injection",
        ThreatLevel.HIGH,
        "Chat template injection",
    ),
]


@dataclass(slots=True)
class InjectionScanResult:
    """Result of an injection scan."""

    is_clean: bool
    findings: List[ScanFinding]
    threat_level: ThreatLevel  # highest threat found


class InjectionScanner:
    """Scan text for prompt injection patterns.

    Implements pattern-based detection for common injection techniques:
    - System prompt overrides
    - Shell/code injection
    - Data exfiltration attempts
    - Jailbreak patterns
    - Delimiter injection
    """

    def __init__(self) -> None:
        self._patterns = [
            (re.compile(pat), name, level, desc)
            for pat, name, level, desc in _INJECTION_PATTERNS
        ]
        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        self._rust_impl = _rust.InjectionScanner()

    def scan(self, text: str) -> InjectionScanResult:
        """Scan text for injection patterns — always via Rust backend."""
        from openjarvis._rust_bridge import injection_result_from_json

        return injection_result_from_json(self._rust_impl.scan(text))


__all__ = ["InjectionScanner", "InjectionScanResult"]
