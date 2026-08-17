"""Browser is a tool capability, not an agent.

No Python here drives a browser: config names the server, native discovery
produces MCPToolAdapters, and the orchestrator calls them through
ToolExecutor like any other tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjarvis.core.config import load_config
from openjarvis.system import SystemBuilder
from openjarvis.tools.mcp_adapter import MCPToolAdapter

PRESET = Path("configs/openjarvis/examples/browser-agent-playwright-mcp.toml")

EXPECTED_TOOLS = {
    "browser_snapshot",
    "browser_find",
    "browser_navigate",
    "browser_navigate_back",
    "browser_tabs",
    "browser_click",
    "browser_type",
    "browser_fill_form",
    "browser_select_option",
    "browser_hover",
    "browser_press_key",
    "browser_wait_for",
    "browser_handle_dialog",
    "browser_drag",
    "browser_drop",
    "browser_resize",
    "browser_close",
    "browser_verify_element_visible",
    "browser_verify_text_visible",
    "browser_verify_value",
    "browser_verify_list_visible",
}

# Pre-existing upstream modules that import Playwright directly. Neither is on
# the browser preset's path: `tools/browser.py` is never imported by the tool
# registry (no builtin tool name starts with "browser_", asserted below) and
# webchorearena_env.py is an eval harness. Listed so a THIRD driver still trips
# the test.
PREEXISTING_PLAYWRIGHT_IMPORTERS = {
    "src/openjarvis/tools/browser.py",
    "src/openjarvis/evals/execution/webchorearena_env.py",
}


def test_preset_allowlists_exactly_the_approved_tools():
    """No integration cost: the allowlist is a config fact."""
    config = load_config(PRESET)
    servers = json.loads(config.tools.mcp.servers)
    assert len(servers) == 1
    playwright = servers[0]
    assert set(playwright["include_tools"]) == EXPECTED_TOOLS
    assert "--snapshot-mode" in playwright["args"]
    assert playwright["args"][playwright["args"].index("--snapshot-mode") + 1] == "none"


def test_preset_serialises_tool_calls():
    config = load_config(PRESET)
    assert config.agent.parallel_tools is False


def test_grounding_prompt_carries_the_no_memory_rule():
    config = load_config(PRESET)
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    prompt = resolve_agent_system_prompt(config.agent)
    assert prompt is not None
    for clause in (
        "no memory of the page",
        "browser_snapshot",
        "evidence that the objective is done",
    ):
        assert clause in prompt


def test_no_second_browser_controller_in_the_tree():
    root = Path("src/openjarvis")
    banned = ("class BrowserAgent", "class BrowserController", "playwright.sync_api")
    offenders = [
        f"{path}: {needle}"
        for path in root.rglob("*.py")
        for needle in banned
        if needle in path.read_text(encoding="utf-8")
        and path.as_posix() not in PREEXISTING_PLAYWRIGHT_IMPORTERS
    ]
    assert not offenders


def test_no_builtin_tool_shadows_an_mcp_browser_tool():
    """`tools/browser.py` registers a builtin named `browser_navigate`.

    If anything ever imports that module at registry-build time, the preset's
    allowlist would resolve to the local Playwright tool AND the MCP one, so the
    agent would see two tools with the same name.
    """
    from openjarvis.mcp.server import MCPServer

    builtin = {tool.spec.name for tool in MCPServer().get_tools()}
    assert not (builtin & EXPECTED_TOOLS)


@pytest.mark.integration
def test_discovery_produces_mcp_tool_adapters():
    """Launches the Playwright MCP subprocess. Needs npx on PATH.

    The engine is injected: ``conftest`` clears ``EngineRegistry`` for every
    test, so discovery would find nothing, and this test is about MCP tools —
    no model is ever called.
    """
    from unittest.mock import MagicMock

    engine = MagicMock()
    engine.health.return_value = True
    engine.list_models.return_value = [load_config(PRESET).intelligence.default_model]

    config = load_config(PRESET)
    system = SystemBuilder(config).engine_instance(engine, key="ollama").build()
    try:
        names = {t.spec.name for t in system.tools if isinstance(t, MCPToolAdapter)}
        assert names == EXPECTED_TOOLS
    finally:
        system.close()
