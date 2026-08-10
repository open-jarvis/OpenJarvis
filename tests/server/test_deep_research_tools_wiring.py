"""Test that _build_deep_research_tools works correctly."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

try:
    import fastapi  # noqa: F401

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import Role, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


class _ConfiguredResearchProbe(BaseTool):
    """Configured native tool used to exercise the Deep Research SSE path."""

    tool_id = "configured_research_probe_682"
    calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Configured Deep Research probe",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )

    def execute(self, **params) -> ToolResult:
        type(self).calls += 1
        return ToolResult(
            tool_name=self.tool_id,
            content=f"configured:{params['value']}",
        )


class _MCPResearchProbe(BaseTool):
    """MCP-shaped adapter that must be merged into the same toolkit."""

    tool_id = "mcp_research_probe_682"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.tool_id, description="MCP Deep Research probe")

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content="mcp")


class _ScriptedDeepResearchEngine:
    """Call the configured probe once, then return a final answer."""

    def __init__(self) -> None:
        self.turns = 0
        self.advertised_names: list[str] = []
        self.observed_tool_result = ""

    def generate(self, messages, *, model, **kwargs):
        self.turns += 1
        self.advertised_names = [
            spec["function"]["name"] for spec in kwargs.get("tools", [])
        ]
        if self.turns == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-configured-research-probe",
                        "type": "function",
                        "function": {
                            "name": _ConfiguredResearchProbe.tool_id,
                            "arguments": json.dumps({"value": "sentinel"}),
                        },
                    }
                ],
                "usage": {},
            }

        tool_messages = [message for message in messages if message.role is Role.TOOL]
        self.observed_tool_result = tool_messages[-1].content
        return {"content": "complete", "tool_calls": [], "usage": {}}


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_deep_research_agent_gets_tools(tmp_path: Path) -> None:
    """When knowledge.db exists, returns 4 tools."""
    db_path = tmp_path / "knowledge.db"
    store = KnowledgeStore(str(db_path))
    store.store("test content", source="test", doc_type="note")

    from openjarvis.server.agent_manager_routes import _build_deep_research_tools

    tools = _build_deep_research_tools(
        engine=MagicMock(),
        model="test-model",
        knowledge_db_path=str(db_path),
    )

    tool_ids = [t.tool_id for t in tools]
    assert "knowledge_search" in tool_ids
    assert "knowledge_sql" in tool_ids
    assert "scan_chunks" in tool_ids
    assert "think" in tool_ids
    assert len(tools) == 4
    store.close()


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_deep_research_tools_returns_empty_when_no_db() -> None:
    """When knowledge.db doesn't exist, returns empty list."""
    from openjarvis.server.agent_manager_routes import _build_deep_research_tools

    tools = _build_deep_research_tools(
        engine=MagicMock(),
        model="test-model",
        knowledge_db_path="/nonexistent/path/knowledge.db",
    )

    assert tools == []


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "with_knowledge_db",
    [False, True],
    ids=["without-knowledge-db", "with-knowledge-db"],
)
async def test_server_deep_research_merges_and_executes_all_tool_sources(
    tmp_path: Path,
    with_knowledge_db: bool,
    monkeypatch,
) -> None:
    """Configured and MCP tools reach Deep Research with or without its DB."""

    from openjarvis.server import agent_manager_routes as routes

    start_worker = MagicMock(wraps=routes._start_managed_worker)
    monkeypatch.setattr(routes, "_start_managed_worker", start_worker)

    db_path = tmp_path / "knowledge.db"
    if with_knowledge_db:
        store = KnowledgeStore(str(db_path))
        store.store("test content", source="test", doc_type="note")
        store.close()

    if not ToolRegistry.contains(_ConfiguredResearchProbe.tool_id):
        ToolRegistry.register_value(
            _ConfiguredResearchProbe.tool_id,
            _ConfiguredResearchProbe,
        )
    _ConfiguredResearchProbe.calls = 0

    mcp_tool = _MCPResearchProbe()
    app_state = SimpleNamespace(
        config=SimpleNamespace(memory_files=None, system_prompt=None),
        memory_backend=None,
        channel_backend=None,
        channel_bridge=None,
        knowledge_db_path=str(db_path),
        _mcp_clients=[object()],
        _mcp_tools_cache=(
            [mcp_tool.to_openai_function()],
            {mcp_tool.spec.name: mcp_tool},
        ),
    )
    manager = MagicMock()
    manager.list_messages.return_value = []
    engine = _ScriptedDeepResearchEngine()

    response = await routes._stream_managed_agent(
        manager=manager,
        agent_record={
            "id": "agent-deep-research-682",
            "name": "Deep Research Agent",
            "agent_type": "deep_research",
            "config": {
                "model": "test-model",
                "max_turns": 3,
                "tools": [_ConfiguredResearchProbe.tool_id],
            },
        },
        user_content="Use the configured research probe",
        message_id="message-deep-research-682",
        engine=engine,
        bus=None,
        app_state=app_state,
    )

    body_parts: list[str] = []
    async for part in response.body_iterator:
        body_parts.append(part.decode() if isinstance(part, bytes) else part)

    expected_names = {
        _ConfiguredResearchProbe.tool_id,
        _MCPResearchProbe.tool_id,
    }
    knowledge_names = {
        "knowledge_search",
        "knowledge_sql",
        "scan_chunks",
        "think",
    }
    if with_knowledge_db:
        expected_names.update(knowledge_names)

    assert set(engine.advertised_names) == expected_names
    assert len(engine.advertised_names) == len(expected_names)
    assert not with_knowledge_db or knowledge_names.issubset(engine.advertised_names)
    assert with_knowledge_db or knowledge_names.isdisjoint(engine.advertised_names)
    assert engine.turns == 2
    assert _ConfiguredResearchProbe.calls == 1
    assert engine.observed_tool_result == "configured:sentinel"
    assert "data: [DONE]" in "".join(body_parts)
    start_worker.assert_called_once()
    assert start_worker.call_args.kwargs["name"].startswith(
        "managed-agent-deep-research-"
    )
    assert app_state._managed_workers == set()

    manager.store_agent_response.assert_called_once()
    stored = manager.store_agent_response.call_args
    assert stored.args[:2] == ("agent-deep-research-682", "complete")
    persisted_calls = stored.kwargs["tool_calls"]
    assert persisted_calls[0]["tool"] == _ConfiguredResearchProbe.tool_id
    assert persisted_calls[0]["result"] == "configured:sentinel"
    assert persisted_calls[0]["success"] is True
