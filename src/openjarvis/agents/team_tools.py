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


class TeamAssignTasksTool(ManagedPeersTool):
    """Lead-only: assign tasks that run the receiving members automatically."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="team_assign_tasks",
            description=(
                "أنت منسّق الفريق: أسند مهام لأعضاء فريقك (حتى 4 في كل تشغيل). "
                "كل مهمة تشغّل الوكيل المستلِم تلقائيًا، ونتيجته ترجع إليك كتقرير. "
                "اكتب التعليمات كاملة بالعربية، وأرفق مسارات ملفات الطلب النسبية. "
                "استخدم managed_agent_peers لمعرفة المعرّفات."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_agent_id": {"type": "string"},
                                "title": {"type": "string"},
                                "instructions": {"type": "string"},
                                "files": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["target_agent_id", "title", "instructions"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["tasks"],
                "additionalProperties": False,
            },
            category="agents",
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.agents.campaigns import HandoffRejected

        try:
            if set(params) != {"tasks"}:
                raise HandoffRejected("أرسل قائمة tasks فقط.")
            created = self.manager.campaigns.assign_tasks(
                self.source_id, params["tasks"]
            )
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content=json.dumps(
                    [
                        {
                            "task_id": item["id"],
                            "target_agent_id": item["target_agent_id"],
                            "status": "pending",
                        }
                        for item in created
                    ],
                    ensure_ascii=False,
                ),
            )
        except HandoffRejected as exc:
            return ToolResult(tool_name=self.spec.name, success=False, content=str(exc))


class CampaignFilesTool(ManagedPeersTool):
    """List files of the team request this agent is working on now."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="campaign_files",
            description=(
                "اعرض ملفات الطلب الحالي (الأصول والمسودات والصور النهائية) "
                "بمساراتها النسبية، أو مرّر path لقراءة ملف نصي صغير منها "
                "(.json أو .html أو .md أو .txt)، مثل بيانات تصدير "
                "final/creative-....png.json. متاح أثناء تنفيذ مهمة للفريق فقط."
            ),
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
            category="agents",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = self.manager.campaigns
        batch = store.running_batch_for(self.source_id)
        if not batch:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="لا يوجد طلب فريق قيد التنفيذ لهذا الوكيل.",
            )
        campaign = store.get_campaign(batch[0]["campaign_id"])
        path = params.get("path")
        if path:
            from openjarvis.agents.campaigns import HandoffRejected

            try:
                file = store.resolve_campaign_file(campaign, str(path))
            except HandoffRejected as exc:
                return ToolResult(
                    tool_name=self.spec.name, success=False, content=str(exc)
                )
            if file.suffix.lower() not in {".json", ".html", ".md", ".txt"}:
                return ToolResult(
                    tool_name=self.spec.name,
                    success=False,
                    content="يمكن قراءة ملفات .json و.html و.md و.txt فقط.",
                )
            text = file.read_text(encoding="utf-8", errors="replace")
            if file.suffix.lower() == ".html":
                # Drop embedded images: the layout text is what reviewers need.
                import re

                text = re.sub(r"data:image/[^\"']+", "data:image/…", text)
            return ToolResult(
                tool_name=self.spec.name, success=True, content=text[:20000]
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=json.dumps(store.list_files(campaign), ensure_ascii=False),
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
        if connection.get("kind", "mcp") != "mcp":
            continue  # Publisher-only credentials are never agent tools.
        if connection["status"] not in {"configured", "verified"}:
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
