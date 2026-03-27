"""Inter-agent lifecycle tools — spawn, send, list, and kill agents.

These MCP tools allow an orchestrating agent (or the system) to manage
child agent lifecycles at runtime.  Spawned agent metadata is tracked in
a module-level dictionary so that any tool in the same process can
query or terminate running agents.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — tracks spawned agents
# ---------------------------------------------------------------------------

_SPAWNED_AGENTS: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# AgentSpawnTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("agent_spawn")
class AgentSpawnTool(BaseTool):
    """Spawn a new agent instance and optionally send it an initial query."""

    tool_id = "agent_spawn"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="agent_spawn",
            description=(
                "Spawn a new agent instance by type. Optionally"
                " send an initial query and attach tools."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_type": {
                        "type": "string",
                        "description": (
                            "Agent registry key (e.g. 'simple',"
                            " 'orchestrator', 'native_react')."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": ("Optional initial query to send to the agent."),
                    },
                    "tools": {
                        "type": "string",
                        "description": (
                            "Comma-separated tool names to attach to the agent."
                        ),
                    },
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "Custom agent ID. Auto-generated if not provided."
                        ),
                    },
                },
                "required": ["agent_type"],
            },
            category="agents",
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        agent_type = params.get("agent_type", "")
        if not agent_type:
            return ToolResult(
                tool_name="agent_spawn",
                content="No agent_type provided.",
                success=False,
            )

        agent_id = params.get("agent_id") or uuid.uuid4().hex[:12]
        query = params.get("query", "")
        tools = params.get("tools", "")

        entry: Dict[str, Any] = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "status": "running",
            "created_at": time.time(),
        }
        if tools:
            entry["tools"] = tools
        if query:
            entry["initial_query"] = query

        _SPAWNED_AGENTS[agent_id] = entry

        result_data: Dict[str, Any] = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "status": "running",
        }
        if query:
            result_data["initial_query"] = query

        return ToolResult(
            tool_name="agent_spawn",
            content=json.dumps(result_data),
            success=True,
        )


# ---------------------------------------------------------------------------
# AgentSendTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("agent_send")
class AgentSendTool(BaseTool):
    """Send a message to a previously spawned agent."""

    tool_id = "agent_send"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="agent_send",
            description=("Send a message to a running agent by its ID."),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the target agent.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to send.",
                    },
                },
                "required": ["agent_id", "message"],
            },
            category="agents",
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        agent_id = params.get("agent_id", "")
        message = params.get("message", "")

        if not agent_id:
            return ToolResult(
                tool_name="agent_send",
                content="No agent_id provided.",
                success=False,
            )

        if agent_id not in _SPAWNED_AGENTS:
            return ToolResult(
                tool_name="agent_send",
                content=f"Agent '{agent_id}' not found.",
                success=False,
            )

        if not message:
            return ToolResult(
                tool_name="agent_send",
                content="No message provided.",
                success=False,
            )

        # Publish event if event bus is available
        try:
            from openjarvis.core.events import EventType, get_event_bus

            bus = get_event_bus()
            bus.publish(
                EventType.AGENT_TURN_START,
                {
                    "agent_id": agent_id,
                    "message": message,
                },
            )
        except Exception as exc:
            logger.debug("Event bus publish failed for agent_send: %s", exc)

        return ToolResult(
            tool_name="agent_send",
            content=json.dumps(
                {
                    "agent_id": agent_id,
                    "delivered": True,
                    "message": message,
                }
            ),
            success=True,
        )


# ---------------------------------------------------------------------------
# AgentListTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("agent_list")
class AgentListTool(BaseTool):
    """List all spawned agents and their current status."""

    tool_id = "agent_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="agent_list",
            description=(
                "List all spawned agents with their status, type, and creation time."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
            category="agents",
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if not _SPAWNED_AGENTS:
            return ToolResult(
                tool_name="agent_list",
                content="No agents spawned.",
                success=True,
            )

        agents = []
        for agent_id, info in _SPAWNED_AGENTS.items():
            agents.append(
                {
                    "agent_id": agent_id,
                    "agent_type": info["agent_type"],
                    "status": info["status"],
                    "created_at": info["created_at"],
                }
            )

        return ToolResult(
            tool_name="agent_list",
            content=json.dumps(agents, indent=2),
            success=True,
        )


# ---------------------------------------------------------------------------
# AgentKillTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("agent_kill")
class AgentKillTool(BaseTool):
    """Kill (stop) a spawned agent by its ID."""

    tool_id = "agent_kill"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="agent_kill",
            description=("Stop a running agent by its ID. Requires confirmation."),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent to stop.",
                    },
                },
                "required": ["agent_id"],
            },
            category="agents",
            requires_confirmation=True,
            required_capabilities=["system:admin"],
        )

    def execute(self, **params: Any) -> ToolResult:
        agent_id = params.get("agent_id", "")

        if not agent_id:
            return ToolResult(
                tool_name="agent_kill",
                content="No agent_id provided.",
                success=False,
            )

        if agent_id not in _SPAWNED_AGENTS:
            return ToolResult(
                tool_name="agent_kill",
                content=f"Agent '{agent_id}' not found.",
                success=False,
            )

        _SPAWNED_AGENTS[agent_id]["status"] = "stopped"

        return ToolResult(
            tool_name="agent_kill",
            content=json.dumps(
                {
                    "agent_id": agent_id,
                    "status": "stopped",
                }
            ),
            success=True,
        )


__all__ = ["AgentKillTool", "AgentListTool", "AgentSendTool", "AgentSpawnTool"]
