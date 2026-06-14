"""Tool discovery — collect all registered tool instances."""

from __future__ import annotations

from typing import List

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool

# Trigger registration of all built-in tools via the package __init__.
import openjarvis.tools  # noqa: F401


def get_available_tools() -> List[BaseTool]:
    """Return instantiated tools for every entry in ``ToolRegistry``.

    Tools that fail instantiation are silently skipped so a single
    broken tool does not prevent the rest from loading.
    """
    tools: List[BaseTool] = []
    for name, tool_cls in ToolRegistry.items():
        try:
            tools.append(tool_cls())
        except Exception:
            continue
    return tools
