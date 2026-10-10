"""Default directory allow-list for the filesystem tools."""

from __future__ import annotations

from typing import List, Optional


def resolve_allowed_dirs(allowed_dirs: Optional[List[str]]) -> List[str]:
    """Return *allowed_dirs*, or ``[security] allowed_dirs`` from the config.

    An empty result keeps the historical behaviour (no directory restriction).
    """
    if allowed_dirs:
        return list(allowed_dirs)
    try:
        from openjarvis.core.config import load_config

        return [str(d) for d in (load_config().security.allowed_dirs or [])]
    except Exception:
        return []
