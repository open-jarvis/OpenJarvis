"""Single point of contact between Python and the Rust ``openjarvis_rust`` module.

Every Python module that wants to delegate to Rust should import helpers from
here rather than importing ``openjarvis_rust`` directly.  This keeps the
try/except logic in one place, honours the ``OPENJARVIS_NO_RUST`` env-var
override, and provides JSON-to-dataclass converters.
"""

from __future__ import annotations

import functools
import json
import os
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    import types as _types

# ---------------------------------------------------------------------------
# Cached import
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_rust_module() -> Optional[_types.ModuleType]:
    """Return the ``openjarvis_rust`` module, or ``None`` if unavailable.

    Setting ``OPENJARVIS_NO_RUST=1`` forces pure-Python mode regardless of
    whether the compiled extension is importable.
    """
    if os.environ.get("OPENJARVIS_NO_RUST", "").strip() in (
        "1",
        "true",
        "yes",
    ):
        return None
    try:
        import openjarvis_rust  # type: ignore[import-untyped]

        return openjarvis_rust
    except ImportError:
        return None


RUST_AVAILABLE: bool = get_rust_module() is not None


# ---------------------------------------------------------------------------
# JSON -> Python dataclass converters
# ---------------------------------------------------------------------------


def scan_result_from_json(json_str: str) -> object:
    """Convert a Rust scanner JSON string to a Python ``ScanResult``."""
    from openjarvis.security.types import (
        ScanFinding,
        ScanResult,
        ThreatLevel,
    )

    data = json.loads(json_str)
    findings: List[ScanFinding] = []
    for f in data.get("findings", []):
        findings.append(
            ScanFinding(
                pattern_name=f.get("pattern_name", ""),
                matched_text=f.get("matched_text", ""),
                threat_level=ThreatLevel(
                    f.get("threat_level", "low").lower(),
                ),
                start=f.get("start", 0),
                end=f.get("end", 0),
                description=f.get("description", ""),
            )
        )
    return ScanResult(findings=findings)


def injection_result_from_json(json_str: str) -> object:
    """Convert Rust ``InjectionScanner.scan()`` JSON to dataclass."""
    from openjarvis.security.injection_scanner import (
        InjectionScanResult,
    )
    from openjarvis.security.types import ScanFinding, ThreatLevel

    data = json.loads(json_str)
    findings: List[ScanFinding] = []
    for f in data.get("findings", []):
        findings.append(
            ScanFinding(
                pattern_name=f.get("pattern_name", ""),
                matched_text=f.get("matched_text", ""),
                threat_level=ThreatLevel(
                    f.get("threat_level", "low").lower(),
                ),
                start=f.get("start", 0),
                end=f.get("end", 0),
                description=f.get("description", ""),
            )
        )

    threat_raw = data.get("threat_level", "low").lower()
    try:
        threat = ThreatLevel(threat_raw)
    except ValueError:
        threat = ThreatLevel.LOW

    return InjectionScanResult(
        is_clean=data.get("is_clean", True),
        findings=findings,
        threat_level=threat,
    )


def retrieval_results_from_json(json_str: str) -> list:
    """Convert Rust memory ``retrieve()`` JSON to a list of results."""
    from openjarvis.tools.storage._stubs import RetrievalResult

    items = json.loads(json_str)
    results: List[RetrievalResult] = []
    for item in items:
        meta = item.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        results.append(
            RetrievalResult(
                content=item.get("content", ""),
                score=float(item.get("score", 0.0)),
                source=item.get("source", ""),
                metadata=meta,
            )
        )
    return results


__all__ = [
    "RUST_AVAILABLE",
    "get_rust_module",
    "injection_result_from_json",
    "retrieval_results_from_json",
    "scan_result_from_json",
]
