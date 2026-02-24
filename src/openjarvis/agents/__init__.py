"""Agents pillar — multi-turn reasoning and tool use."""

from __future__ import annotations

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    BaseAgent,
    ToolUsingAgent,
)

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

# Registry alias: "react" -> NativeReActAgent (for backward compat)
try:
    from openjarvis.core.registry import AgentRegistry

    if AgentRegistry.contains("native_react") and not AgentRegistry.contains("react"):
        AgentRegistry.register_value("react", AgentRegistry.get("native_react"))
except Exception:
    pass

__all__ = ["AgentContext", "AgentResult", "BaseAgent", "ToolUsingAgent"]
