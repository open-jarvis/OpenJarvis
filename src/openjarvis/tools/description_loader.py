"""Load tool description overrides from $OPENJARVIS_HOME/tools/descriptions.toml.

LLM-guided spec search (M1) proposes tool description edits that get written to disk by
``EditToolDescriptionApplier``.  This module loads those overrides so agents
see the improved descriptions at runtime.

The TOML file format (written by the applier) is::

    [web_search]
    description = "Search the web for recent information only"

    [llm]
    description = "Call a sub-LM. Has no internet access."
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_cache: Optional[Dict[str, str]] = None


def _load_overrides() -> Dict[str, str]:
    """Parse descriptions.toml and return {tool_name: description}."""
    home = Path(os.environ.get("OPENJARVIS_HOME", "~/.openjarvis")).expanduser()
    desc_path = home / "tools" / "descriptions.toml"
    if not desc_path.exists():
        return {}
    try:
        content = desc_path.read_text(encoding="utf-8")
    except Exception:
        logger.warning(
            "Failed to read tool description overrides at %s",
            desc_path,
            exc_info=True,
        )
        return {}

    overrides: Dict[str, str] = {}
    current_tool: Optional[str] = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_tool = stripped[1:-1]
        elif current_tool and stripped.startswith("description"):
            # Parse: description = "..."
            _, _, value = stripped.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                overrides[current_tool] = value
    if overrides:
        logger.info(
            "Loaded %d tool description overrides from %s",
            len(overrides),
            desc_path,
        )
    return overrides


def get_tool_description_override(tool_name: str) -> Optional[str]:
    """Return the override description for *tool_name*, or ``None``.

    Results are cached for the lifetime of the process.
    """
    global _cache  # noqa: PLW0603
    if _cache is None:
        _cache = _load_overrides()
    return _cache.get(tool_name)


def clear_cache() -> None:
    """Clear the cached overrides (useful for testing)."""
    global _cache  # noqa: PLW0603
    _cache = None
