"""Single point of contact between Python and the Rust ``openjarvis_rust`` module.

Every Python module that wants to delegate to Rust should import helpers from
here rather than importing ``openjarvis_rust`` directly.  The Rust extension is
optional — if it cannot be imported, ``get_rust_module()`` returns ``None`` and
``RUST_AVAILABLE`` is set to ``False`` so callers can fall back to Python
implementations.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    import types as _types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — Rust backend is not required
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_rust_module() -> Optional[_types.ModuleType]:
    """Return the ``openjarvis_rust`` module, or ``None`` if unavailable.

    The Rust extension is optional.  Callers should check the return value
    and fall back to a pure-Python implementation when ``None`` is returned.
    """
    try:
        import openjarvis_rust  # type: ignore[import-untyped]

        return openjarvis_rust
    except ImportError:
        return None


def _check_rust_available() -> bool:
    try:
        import openjarvis_rust  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        logger.info(
            "Rust extension (openjarvis_rust) not available — "
            "using pure-Python fallbacks for memory and security backends"
        )
        return False


RUST_AVAILABLE: bool = _check_rust_available()


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


# ---------------------------------------------------------------------------
# Phase 2 converters — optimization & engine types
# ---------------------------------------------------------------------------


def optimization_store_from_rust(path: str = ":memory:") -> object | None:
    """Get a Rust-backed OptimizationStore, or None if Rust unavailable."""
    mod = get_rust_module()
    if mod is None:
        return None
    try:
        return mod.OptimizationStore(path)
    except Exception:
        return None


def trial_result_from_json(json_str: str) -> dict:
    """Convert Rust TrialResult JSON to a Python dict."""
    return json.loads(json_str)


def optimization_run_from_json(json_str: str) -> dict:
    """Convert Rust OptimizationRun JSON to a Python dict."""
    return json.loads(json_str)


def generate_result_from_json(json_str: str) -> dict:
    """Convert Rust GenerateResult JSON to a Python dict."""
    data = json.loads(json_str)
    return {
        "content": data.get("content", ""),
        "model": data.get("model", ""),
        "finish_reason": data.get("finish_reason", "stop"),
        "usage": data.get("usage", {}),
        "tool_calls": data.get("tool_calls"),
        "ttft": data.get("ttft", 0.0),
        "cost_usd": data.get("cost_usd", 0.0),
        "metadata": data.get("metadata", {}),
    }


__all__ = [
    "RUST_AVAILABLE",
    "generate_result_from_json",
    "get_rust_module",
    "injection_result_from_json",
    "optimization_run_from_json",
    "optimization_store_from_rust",
    "retrieval_results_from_json",
    "scan_result_from_json",
    "trial_result_from_json",
]
