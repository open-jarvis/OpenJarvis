"""Anonymous identity for external analytics.

One UUID v4 per install, persisted to disk on first use. The same file
is referenced by ``scripts/install/install.sh`` so install-time beacon
events tie back to the same person across the install→first-run funnel.

No email, no name, no hardware fingerprint — just an opaque UUID.
"""

from __future__ import annotations

import os
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


def do_not_track() -> bool:
    """Return True if the ``DO_NOT_TRACK`` environment kill-switch is set.

    Honors the console ``DO_NOT_TRACK`` standard (https://consoledonottrack.com):
    a value of ``1`` / ``true`` / ``yes`` (case-insensitive) signals that the
    user does not want telemetry. Any other value — including unset or ``0`` —
    leaves the decision to config.
    """
    return os.environ.get("DO_NOT_TRACK", "").strip().lower() in ("1", "true", "yes")


def is_analytics_enabled(cfg: AnalyticsConfig) -> bool:
    """Return True if analytics is enabled.

    ``DO_NOT_TRACK`` is an env-level override: when set, analytics is disabled
    regardless of config, so privacy-conscious users have a kill-switch that
    does not require editing config files. Otherwise the config value wins.
    """
    if do_not_track():
        return False
    return cfg.enabled
