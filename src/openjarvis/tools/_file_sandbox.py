"""Shared filesystem sandbox policy for the file_read / file_write tools.

The executor instantiates tools with no constructor arguments, so a sandbox
configured in ``config.toml`` could never reach the tool. These helpers close
that gap by resolving the policy from (in priority order) an explicit argument,
an environment variable, and finally the loaded config — all without requiring
the executor to know anything about file-tool wiring.

Defaults are intentionally non-breaking: with nothing configured the allow-list
is empty (no path restriction) and writes do not require confirmation, matching
historical behavior. Sensitive files are always blocked separately by
``openjarvis.security.file_policy`` regardless of these settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

_TRUTHY = {"1", "true", "yes", "on"}

WORKSPACE_ENV = "OPENJARVIS_WORKSPACE"
CONFIRM_WRITE_ENV = "OPENJARVIS_CONFIRM_FILE_WRITE"


def _config_tools():
    """Return the loaded ``tools`` config, or ``None`` if unavailable."""
    try:
        from openjarvis.core.config import load_config

        return load_config().tools
    except Exception:
        return None


def resolve_allowed_dirs(explicit: Optional[List[str]]) -> List[Path]:
    """Resolve sandbox roots for a file tool.

    Resolution order:
      1. ``explicit`` argument (used by callers/tests that pass ``allowed_dirs``).
      2. ``OPENJARVIS_WORKSPACE`` env var (``os.pathsep``-separated paths).
      3. ``[tools] file_allowed_dirs`` from the loaded config.

    An empty list means "no path restriction" (legacy behavior).
    """
    if explicit is not None:
        return [Path(d).expanduser().resolve() for d in explicit]

    raw: List[str] = []
    env = os.environ.get(WORKSPACE_ENV, "").strip()
    if env:
        raw.extend(part for part in env.split(os.pathsep) if part.strip())

    if not raw:
        tools = _config_tools()
        cfg_dirs = getattr(tools, "file_allowed_dirs", None) or []
        raw.extend(str(d) for d in cfg_dirs if str(d).strip())

    return [Path(d).expanduser().resolve() for d in raw]


def write_requires_confirmation() -> bool:
    """Whether file_write should be gated behind the confirmation callback."""
    env = os.environ.get(CONFIRM_WRITE_ENV, "").strip().lower()
    if env:
        return env in _TRUTHY

    tools = _config_tools()
    return bool(getattr(tools, "file_write_confirm", False))


__all__ = [
    "resolve_allowed_dirs",
    "write_requires_confirmation",
    "WORKSPACE_ENV",
    "CONFIRM_WRITE_ENV",
]
