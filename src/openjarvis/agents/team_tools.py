"""Runtime-bound managed messaging and private per-team MCP connections.

Not registered as ambient tools: only the resolver can bind the real source agent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Any

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


class ManagedPeersTool(BaseTool):
    def __init__(self, manager: Any, source_id: str):
        self.manager, self.source_id = manager, source_id

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_peers",
            description=(
                "List managed agents you may message under current team policy. "
                "Does not reveal their configuration, private memory or history."
            ),
            parameters={"type": "object", "properties": {}},
            category="agents",
        )

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=json.dumps(self.manager.list_agent_peers(self.source_id)),
        )


class ManagedSendTool(ManagedPeersTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_agent_message",
            description=(
                "Queue a message to an allowed managed agent. "
                "The runtime supplies your identity and checks both teams' "
                "current permission. Queued, not auto-run."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target_agent_id": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["target_agent_id", "message"],
                "additionalProperties": False,
            },
            category="agents",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            if set(params) != {"target_agent_id", "message"}:
                raise ValueError("Supply target_agent_id and message only")
            result = self.manager.send_agent_message(
                self.source_id, params["target_agent_id"], params["message"]
            )
            return ToolResult(
                tool_name=self.spec.name, success=True, content=json.dumps(result)
            )
        except (ValueError, PermissionError) as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))


class TeamMCPTool(BaseTool):
    """Keep credentials out of results; recheck ownership on every execution."""

    is_local = False

    def __init__(
        self,
        tool: Any,
        manager: Any,
        agent_id: str,
        *,
        connection_id: str,
    ):
        self._tool, self._manager, self._agent_id = tool, manager, agent_id
        self._connection_id = connection_id

    @property
    def spec(self) -> ToolSpec:
        original = self._tool.spec
        suffix = hashlib.sha256(original.name.encode()).hexdigest()[:8]
        readable = re.sub(r"[^a-zA-Z0-9_-]", "_", original.name)[:36]
        name = f"team_{self._connection_id[:10]}_{readable}_{suffix}"
        return replace(original, name=name)

    def execute(self, **params: Any) -> ToolResult:
        allowed = self._manager.team_connection_allowed(
            self._agent_id, self._connection_id
        )
        if not allowed:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="This connection is no longer allowed for your team.",
            )
        result = self._tool.execute(**params)
        if not result.success:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="The team's MCP connection failed. "
                "Check its authentication and endpoint.",
            )
        return replace(result, tool_name=self.spec.name)


class GlobalMCPTool(BaseTool):
    """Do not retain a global account if an unassigned agent joins a team mid-turn."""

    is_local = False

    def __init__(self, tool: Any, manager: Any, agent_id: str):
        self._tool, self._manager, self._agent_id = tool, manager, agent_id

    @property
    def spec(self) -> ToolSpec:
        return self._tool.spec

    def execute(self, **params: Any) -> ToolResult:
        agent = self._manager.get_agent(self._agent_id)
        if (
            not agent
            or agent.get("team_id")
            or agent.get("team_scoped")
            or agent["status"] == "archived"
            or agent["config"].get("mcp_tools", True) is False
        ):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Global connections are not available to this agent.",
            )
        return self._tool.execute(**params)


class ManagedConnectionStatusTool(ManagedPeersTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="managed_connection_status",
            description=(
                "Show your team's connection names and configuration readiness. "
                "Configured does not mean account access has been verified. "
                "No credential values are returned."
            ),
            parameters={"type": "object", "properties": {}},
            category="agents",
        )

    def execute(self, **params: Any) -> ToolResult:
        agent = self.manager.get_agent(self.source_id)
        connections = (
            self.manager.list_team_connections(agent["team_id"])
            if agent and agent.get("team_id")
            else []
        )
        public = [
            {k: c[k] for k in ("name", "provider", "status")} for c in connections
        ]
        return ToolResult(
            tool_name=self.spec.name, success=True, content=json.dumps(public)
        )


def discover_team_connections(
    manager: Any, agent_id: str
) -> tuple[list[Any], list[Any]]:
    """Create isolated clients, never fall back to a global account on failure."""
    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.transport import StreamableHTTPTransport
    from openjarvis.tools.mcp_adapter import MCPToolProvider

    agent = manager.get_agent(agent_id)
    if not agent or not agent.get("team_id"):
        return [], []
    tools, clients = [], []
    for connection in manager.list_team_connections(agent["team_id"]):
        if connection["status"] != "configured":
            continue
        client = None
        try:
            token = (
                manager._team_connection_token(connection["id"])
                if connection["auth_type"] == "bearer"
                else None
            )
            client = MCPClient(
                StreamableHTTPTransport(
                    connection["url"],
                    token=token,
                    connect_timeout=10,
                    request_timeout=30,
                )
            )
            client.initialize()
            discovered = MCPToolProvider(client).discover()
            for tool in discovered:
                tools.append(
                    TeamMCPTool(tool, manager, agent_id, connection_id=connection["id"])
                )
            clients.append(client)
        except Exception:
            # External error text may contain an auth token: never echo or log it.
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
    return tools, clients
