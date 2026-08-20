"""Taint tracking — information flow control.

Prevents data leakage through tool chains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, Optional, Set


class TaintLabel(str, Enum):
    """Labels for tainted data."""

    PII = "pii"
    SECRET = "secret"
    USER_PRIVATE = "user_private"
    EXTERNAL = "external"


@dataclass(frozen=True)
class TaintSet:
    """Immutable set of taint labels attached to data."""

    labels: FrozenSet[TaintLabel] = field(default_factory=frozenset)

    def union(self, other: TaintSet) -> TaintSet:
        """Merge two taint sets."""
        return TaintSet(labels=self.labels | other.labels)

    def has(self, label: TaintLabel) -> bool:
        """Check if a specific label is present."""
        return label in self.labels

    def __bool__(self) -> bool:
        return bool(self.labels)

    @classmethod
    def from_labels(cls, *labels: TaintLabel) -> TaintSet:
        """Create from one or more labels."""
        return cls(labels=frozenset(labels))


# Sink policy: which taint labels are forbidden for each tool
# If a tool appears here, data with any of the listed labels MUST NOT
# be passed to that tool.
SINK_POLICY: Dict[str, Set[TaintLabel]] = {
    "web_search": {TaintLabel.PII, TaintLabel.SECRET},
    "channel_send": {TaintLabel.SECRET},
    "code_interpreter": {TaintLabel.SECRET},
}

# Patterns for auto-detecting taint in text
_PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),  # credit card
    re.compile(r"\b\+?1?\s*\(?[2-9]\d{2}\)?\s*[-.\s]?\d{3}\s*[-.\s]?\d{4}\b"),  # phone
]

_SECRET_PATTERNS = [
    re.compile(r"(?:sk|pk|api)[_-][a-zA-Z0-9]{20,}"),  # API keys
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"),  # GitHub tokens
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),  # Private keys
    re.compile(
        r"(?:bearer|token|password|secret|key)\s*[=:]\s*\S{8,}",
        re.IGNORECASE,
    ),  # Generic secrets
]


def check_taint(tool_name: str, taint: TaintSet) -> Optional[str]:
    """Check if *taint* labels violate the sink policy for *tool_name*.

    Returns a violation description string, or None if clean.
    """
    forbidden = SINK_POLICY.get(tool_name)
    if forbidden is None:
        return None
    violations = taint.labels & forbidden
    if violations:
        labels_str = ", ".join(
            v.value for v in sorted(violations, key=lambda x: x.value)
        )
        return f"Data with labels [{labels_str}] cannot be sent to '{tool_name}'."
    return None


def declassify(taint: TaintSet, remove: TaintLabel, reason: str) -> TaintSet:
    """Remove a taint label with an explicit reason (for audit).

    The *reason* is not stored on the TaintSet itself but should be
    logged externally for accountability.
    """
    return TaintSet(labels=taint.labels - {remove})


def auto_detect_taint(text: str) -> TaintSet:
    """Auto-detect taint labels in text content.

    Uses regex patterns to detect PII and secrets in tool output.
    """
    labels: set[TaintLabel] = set()

    for pattern in _PII_PATTERNS:
        if pattern.search(text):
            labels.add(TaintLabel.PII)
            break

    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            labels.add(TaintLabel.SECRET)
            break

    return TaintSet(labels=frozenset(labels))


def propagate_taint(
    input_taint: TaintSet,
    output_text: str,
) -> TaintSet:
    """Propagate taint: union of input taint with auto-detected output taint."""
    output_taint = auto_detect_taint(output_text)
    return input_taint.union(output_taint)


__all__ = [
    "SINK_POLICY",
    "TaintLabel",
    "TaintSet",
    "auto_detect_taint",
    "check_taint",
    "declassify",
    "propagate_taint",
]
