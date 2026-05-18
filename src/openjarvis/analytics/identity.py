"""Anonymous identity for external analytics.

One UUID v4 per install, persisted to disk on first use. The same file
is referenced by ``scripts/install/install.sh`` so install-time beacon
events tie back to the same person across the install→first-run funnel.

No email, no name, no hardware fingerprint — just an opaque UUID.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from openjarvis.core.config import AnalyticsConfig


def get_or_create_anon_id(path: Path | str) -> str:
    """Return the persisted anon ID, generating one on first call.

    Idempotent across processes — if the file already exists with a
    non-empty value, return it; otherwise generate a fresh UUID v4 and
    write atomically (rename-after-write so a crashed write leaves no
    half-file).
    """
    p = Path(path)
    if p.exists():
        existing = p.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    new_id = str(uuid.uuid4())
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new_id + "\n", encoding="utf-8")
    tmp.replace(p)
    return new_id


def reset_anon_id(path: Path | str) -> str:
    """Delete the persisted ID and generate a fresh one (privacy reset)."""
    p = Path(path)
    if p.exists():
        p.unlink()
    return get_or_create_anon_id(p)


def is_analytics_enabled(cfg: AnalyticsConfig) -> bool:
    """Return True if analytics is enabled in config.

    Always disabled when running under pytest. The PostHog SDK registers
    an ``atexit`` hook that synchronously joins its consumer thread; if
    the host is unreachable (CI runners can't reach the analytics endpoint),
    each queued batch retries for ``timeout * max_retries`` seconds and the
    interpreter never exits. Detect pytest via ``PYTEST_CURRENT_TEST``
    (set per test) and ``"pytest" in sys.modules`` (covers the collection
    phase before the first test runs).
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        return False
    return cfg.enabled
