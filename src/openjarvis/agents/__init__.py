"""Agents primitive — multi-turn reasoning and tool use."""

from __future__ import annotations

import logging

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)
from openjarvis.agents.memory import AgentMemoryManager

logger = logging.getLogger(__name__)

# Import agent modules to trigger @AgentRegistry.register() decorators
try:
    import openjarvis.agents.simple  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.orchestrator  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.native_react  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.native_openhands  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.react  # noqa: F401 -- backward-compat shim
except ImportError:
    pass

try:
    import openjarvis.agents.openhands  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.rlm  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.claude_code  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.operative  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.monitor  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.monitor_operative  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.deep_research  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.morning_digest  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.proactive_agent  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.bavaria_booking  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.legal_assistant  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.marketing_assistant  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.operations_assistant  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.security_assistant  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.calendar  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.email  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.inventory  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.agents.memory  # noqa: F401
except ImportError:
    pass

# Hybrid local+cloud paradigm agents (Minions, Conductor, Archon, Advisors,
# SkillOrchestra, ToolOrchestra). Each module registers under its own name
# via @AgentRegistry.register(). Optional deps may make some unavailable.
try:
    import openjarvis.agents.hybrid  # noqa: F401
except ImportError:
    pass

# Registry alias: "react" -> NativeReActAgent (for backward compat)
try:
    from openjarvis.core.registry import AgentRegistry

    if AgentRegistry.contains("native_react") and not AgentRegistry.contains("react"):
        AgentRegistry.register_value("react", AgentRegistry.get("native_react"))
except Exception as exc:
    logger.debug("Registry alias 'react' creation skipped: %s", exc)

__all__ = [
    "AgentContext",
    "AgentResult",
    "AgentMemoryManager",
    "BaseAgent",
    "ToolUsingAgent",
]
