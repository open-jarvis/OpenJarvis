"""Security data types — threat levels, scan findings, and security events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ThreatLevel(str, Enum):
    """Severity classification for security findings."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RedactionMode(str, Enum):
    """Action mode when findings are detected."""

    WARN = "warn"
    REDACT = "redact"
    BLOCK = "block"


class SecurityEventType(str, Enum):
    """Categories of security events."""

    SECRET_DETECTED = "secret_detected"
    PII_DETECTED = "pii_detected"
    SENSITIVE_FILE_BLOCKED = "sensitive_file_blocked"
    TOOL_BLOCKED = "tool_blocked"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ScanFinding:
    """A single finding from a security scanner."""

    pattern_name: str
    matched_text: str
    threat_level: ThreatLevel
    start: int
    end: int
    description: str = ""


@dataclass(slots=True)
class ScanResult:
    """Aggregated result from one or more scanners."""

    findings: List[ScanFinding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Return ``True`` if no findings were detected."""
        return len(self.findings) == 0

    @property
    def highest_threat(self) -> Optional[ThreatLevel]:
        """Return the highest threat level among findings, or ``None``."""
        if not self.findings:
            return None
        order = [
            ThreatLevel.LOW,
            ThreatLevel.MEDIUM,
            ThreatLevel.HIGH,
            ThreatLevel.CRITICAL,
        ]
        best = max(
            self.findings,
            key=lambda f: order.index(f.threat_level),
        )
        return best.threat_level


@dataclass(slots=True)
class SecurityEvent:
    """A recorded security event for audit logging."""

    event_type: SecurityEventType
    timestamp: float
    findings: List[ScanFinding] = field(default_factory=list)
    content_preview: str = ""
    action_taken: str = ""


__all__ = [
    "RedactionMode",
    "ScanFinding",
    "ScanResult",
    "SecurityEvent",
    "SecurityEventType",
    "ThreatLevel",
]
