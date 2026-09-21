"""Agents primitive — multi-turn reasoning and tool use."""

from __future__ import annotations

import logging

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)

logger = logging.getLogger(__name__)

# Import agent modules to trigger @AgentRegistry.register() decorators.
# Optional deps may make some unavailable; failures are recorded (not
# silently discarded) so jarvis doctor can report exactly what and why.
import importlib as _importlib

IMPORT_FAILURES: dict[str, str] = {}

_AGENT_MODULES = (
    "openjarvis.agents.simple",
    "openjarvis.agents.orchestrator",
    "openjarvis.agents.native_react",
    "openjarvis.agents.native_openhands",
    "openjarvis.agents.react",  # backward-compat shim
    "openjarvis.agents.openhands",
    "openjarvis.agents.rlm",
    "openjarvis.agents.claude_code",
    "openjarvis.agents.opencode",
    "openjarvis.agents.operative",
    "openjarvis.agents.monitor",
    "openjarvis.agents.monitor_operative",
    "openjarvis.agents.deep_research",
    "openjarvis.agents.morning_digest",
    # Hybrid local+cloud paradigm agents (Minions, Conductor, Archon,
    # Advisors, SkillOrchestra, ToolOrchestra) each register under their
    # own name via @AgentRegistry.register().
    "openjarvis.agents.hybrid",
)

for _modname in _AGENT_MODULES:
    try:
        _importlib.import_module(_modname)
    except ImportError as _exc:
        IMPORT_FAILURES[_modname] = str(_exc)
        logger.debug("Agent module %s unavailable: %s", _modname, _exc)

# Registry alias: "react" -> NativeReActAgent (for backward compat)
try:
    from openjarvis.core.registry import AgentRegistry

    if AgentRegistry.contains("native_react") and not AgentRegistry.contains("react"):
        AgentRegistry.register_value("react", AgentRegistry.get("native_react"))
except Exception as exc:
    logger.debug("Registry alias 'react' creation skipped: %s", exc)

__all__ = ["AgentContext", "AgentResult", "BaseAgent", "ToolUsingAgent"]
