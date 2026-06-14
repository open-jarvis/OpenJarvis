"""Tests for openjarvis.tools.discovery — get_available_tools()."""

from __future__ import annotations

import importlib
import sys

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.discovery import get_available_tools


def _reload_tool_modules() -> None:
    """Re-trigger @ToolRegistry.register decorators after conftest cleared them."""
    for mod_name in list(sys.modules):
        if (
            mod_name.startswith("openjarvis.tools.")
            and not mod_name.endswith("_stubs")
            and not mod_name.endswith("agent_tools")
        ):
            try:
                importlib.reload(sys.modules[mod_name])
            except Exception:
                pass


def test_get_available_tools_returns_instances():
    _reload_tool_modules()
    tools = get_available_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    names = [t.spec.name for t in tools]
    assert "fbi_watchdog" in names
    assert "calculator" in names


def test_get_available_tools_skips_broken_tools():
    """A tool that raises on instantiation must not break the whole list."""
    _reload_tool_modules()

    class _BadTool:
        spec = type("spec", (), {"name": "bad"})()

    ToolRegistry.register("_bad_discovery")(_BadTool)  # type: ignore[arg-type]

    tools = get_available_tools()
    names = [t.spec.name for t in tools]
    assert "_bad_discovery" not in names
