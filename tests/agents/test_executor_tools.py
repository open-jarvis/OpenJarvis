"""Tests for tool wiring in AgentExecutor."""

from __future__ import annotations

import gc
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.manager import AgentManager
from openjarvis.agents.tool_resolver import ResolvedAgentTools
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.config import MemoryFilesConfig, SystemPromptConfig
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry, ToolRegistry
from openjarvis.core.types import Role, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from tests.agents.fake_engine import FakeEngine
from tests.agents.scenario_harness import FakeSystem


class _CapturingToolAgent:
    """Minimal agent that exposes the toolkit received by AgentExecutor."""

    accepts_tools = True
    captured_tools = []
    captured_search_result = None

    def __init__(self, engine, model, *, tools=None, **kwargs):
        self.engine = engine
        self.model = model
        type(self).captured_tools = list(tools or [])

    def run(self, input_text, context=None):
        tools_by_name = {tool.spec.name: tool for tool in self.captured_tools}
        search = tools_by_name.get("knowledge_search")
        if search is not None:
            type(self).captured_search_result = search.execute(
                query="EXECUTOR_RESOLVER_SENTINEL"
            )
        return AgentResult(content="captured")


class _NonToolAgent:
    """Agent class whose run method must not swallow a configured toolkit."""

    accepts_tools = False
    supports_managed_tool_fallback = True
    runs = 0

    def __init__(self, engine, model, **kwargs):
        pass

    def run(self, input_text, context=None):
        type(self).runs += 1
        raise AssertionError("non-tool agent should use the managed tool loop")


class _SpecializedNonToolAgent:
    """Non-tool agent that must retain its specialized execution path."""

    accepts_tools = False
    runs = 0

    def __init__(self, engine, model, **kwargs):
        pass

    def run(self, input_text, context=None):
        type(self).runs += 1
        return AgentResult(content="specialized response")


class _ExecutorProbeTool(BaseTool):
    tool_id = "executor_probe"
    calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.tool_id, description="Executor parity probe")

    def execute(self, **params) -> ToolResult:
        type(self).calls += 1
        return ToolResult(tool_name=self.tool_id, content="probe-result")


def _register_agent():
    """Re-register MonitorOperativeAgent (cleared by autouse fixture)."""
    from openjarvis.agents.monitor_operative import MonitorOperativeAgent
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains("monitor_operative"):
        AgentRegistry.register("monitor_operative")(MonitorOperativeAgent)


def test_executor_runs_with_tools_from_config(tmp_path):
    """Executor should resolve tool names from config and complete tick."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["think"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()


def test_executor_handles_missing_tools(tmp_path):
    """Executor should not crash if tool names don't exist in registry."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["nonexistent_tool_xyz"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()


def test_executor_handles_string_tools(tmp_path):
    """Executor should handle comma-separated tool string as well as list."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": "think,calculator",
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    mgr.close()


def test_executor_uses_tool_loop_for_non_tool_agent_with_configured_tools(tmp_path):
    """Immediate/scheduled ticks match SSE instead of discarding tools."""

    AgentRegistry.register_value("non_tool_probe", _NonToolAgent)
    ToolRegistry.register_value(_ExecutorProbeTool.tool_id, _ExecutorProbeTool)
    _NonToolAgent.runs = 0
    _ExecutorProbeTool.calls = 0

    engine = FakeEngine(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-executor-probe",
                        "name": _ExecutorProbeTool.tool_id,
                        "arguments": "{}",
                    }
                ]
            },
            {"content": "tool-backed final response"},
        ]
    )
    system = FakeSystem(engine=engine)
    system.config = SimpleNamespace(
        agent=SimpleNamespace(default_system_prompt="GLOBAL_DEFAULT"),
        memory_files=MemoryFilesConfig(persona_name="none"),
        system_prompt=SystemPromptConfig(),
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "non-tool with tools",
        agent_type="non_tool_probe",
        config={
            "model": "test-model",
            "tools": [_ExecutorProbeTool.tool_id],
            "instruction": "Use the probe.",
            "system_prompt": "NON_TOOL_SYSTEM_SENTINEL",
        },
    )

    try:
        AgentExecutor(manager, EventBus(), system=system).execute_tick(agent["id"])

        assert _NonToolAgent.runs == 0
        assert _ExecutorProbeTool.calls == 1
        assert engine.call_count == 2
        assert any(
            message.role is Role.SYSTEM
            and message.content == "NON_TOOL_SYSTEM_SENTINEL"
            for message in engine.last_messages or []
        )
        refreshed = manager.get_agent(agent["id"])
        assert refreshed["status"] == "idle"
        assert refreshed["total_runs"] == 1
        responses = [
            message
            for message in manager.list_messages(agent["id"])
            if message["direction"] == "agent_to_user"
        ]
        assert responses[-1]["content"] == "tool-backed final response"
        assert responses[-1]["tool_calls"][0]["tool"] == "executor_probe"
    finally:
        manager.close()


def test_simple_agent_uses_global_mcp_tools_without_native_tool_config(tmp_path):
    """Fallback-compatible simple agents preserve SSE/global-MCP parity."""

    from openjarvis.agents.simple import SimpleAgent

    AgentRegistry.register_value("simple", SimpleAgent)
    _ExecutorProbeTool.calls = 0
    provider = MagicMock(return_value=([_ExecutorProbeTool()], []))
    engine = FakeEngine(
        [
            {
                "tool_calls": [
                    {
                        "id": "call-global-mcp-probe",
                        "name": _ExecutorProbeTool.tool_id,
                        "arguments": "{}",
                    }
                ]
            },
            {"content": "global MCP response"},
        ]
    )
    system = SimpleNamespace(
        engine=engine,
        model="test-model",
        config=None,
        memory_backend=None,
        channel_backend=None,
        session_store=None,
        knowledge_db_path=None,
        get_managed_agent_mcp_tools=provider,
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "simple global MCP",
        agent_type="simple",
        config={"model": "test-model", "instruction": "Use MCP."},
    )

    try:
        AgentExecutor(manager, EventBus(), system=system).execute_tick(agent["id"])

        provider.assert_called_once_with()
        assert _ExecutorProbeTool.calls == 1
        assert engine.call_count == 2
        responses = [
            message
            for message in manager.list_messages(agent["id"])
            if message["direction"] == "agent_to_user"
        ]
        assert responses[-1]["content"] == "global MCP response"
    finally:
        manager.close()


def test_simple_agent_without_tools_keeps_its_custom_system_prompt(tmp_path):
    """Signature filtering must not discard prompt-builder state on retry."""

    from openjarvis.agents.simple import SimpleAgent

    AgentRegistry.register_value("simple", SimpleAgent)
    engine = FakeEngine([{"content": "custom prompt response"}])
    system = FakeSystem(engine=engine)
    system.config = SimpleNamespace(
        agent=SimpleNamespace(default_system_prompt="GLOBAL_DEFAULT"),
        memory_files=MemoryFilesConfig(persona_name="none"),
        system_prompt=SystemPromptConfig(),
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "simple custom prompt",
        agent_type="simple",
        config={
            "model": "test-model",
            "instruction": "Answer directly.",
            "system_prompt": "SIMPLE_CUSTOM_SYSTEM_SENTINEL",
            "mcp_tools": False,
        },
    )

    try:
        AgentExecutor(manager, EventBus(), system=system).execute_tick(agent["id"])

        assert engine.call_count == 1
        assert any(
            message.role is Role.SYSTEM
            and message.content == "SIMPLE_CUSTOM_SYSTEM_SENTINEL"
            for message in engine.last_messages or []
        )
    finally:
        manager.close()


def test_specialized_non_tool_agent_is_not_replaced_by_generic_tool_loop(tmp_path):
    """Configured/global tools never replace a non-opted-in agent class."""

    AgentRegistry.register_value("specialized_non_tool", _SpecializedNonToolAgent)
    ToolRegistry.register_value(_ExecutorProbeTool.tool_id, _ExecutorProbeTool)
    _SpecializedNonToolAgent.runs = 0
    _ExecutorProbeTool.calls = 0
    provider = MagicMock(return_value=([_ExecutorProbeTool()], []))
    system = SimpleNamespace(
        engine=FakeEngine([{"content": "unused"}]),
        model="test-model",
        config=None,
        memory_backend=None,
        channel_backend=None,
        session_store=None,
        knowledge_db_path=None,
        get_managed_agent_mcp_tools=provider,
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "specialized with configured tool",
        agent_type="specialized_non_tool",
        config={
            "model": "test-model",
            "instruction": "Keep the specialized path.",
            "tools": [_ExecutorProbeTool.tool_id],
        },
    )

    try:
        AgentExecutor(manager, EventBus(), system=system).execute_tick(agent["id"])

        provider.assert_not_called()
        assert _SpecializedNonToolAgent.runs == 1
        assert _ExecutorProbeTool.calls == 0
        responses = [
            message
            for message in manager.list_messages(agent["id"])
            if message["direction"] == "agent_to_user"
        ]
        assert responses[-1]["content"] == "specialized response"
    finally:
        manager.close()


def test_executor_grants_deep_research_live_knowledge_tools(tmp_path):
    """Immediate ticks receive the same live Deep Research grant as SSE."""

    AgentRegistry.register_value("deep_research", _CapturingToolAgent)
    _CapturingToolAgent.captured_tools = []
    _CapturingToolAgent.captured_search_result = None

    knowledge_db_path = tmp_path / "knowledge.db"
    with KnowledgeStore(db_path=knowledge_db_path) as store:
        store.store(
            "The EXECUTOR_RESOLVER_SENTINEL decision was approved.",
            source="test",
            doc_type="note",
        )

    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "researcher",
        agent_type="deep_research",
        config={
            "model": "agent-selected-model",
            # These duplicate two agent-type grants and must not replace them.
            "tools": ["knowledge_search", "think"],
            "instruction": "Find the sentinel.",
        },
    )
    manager.send_message(agent["id"], "Search the knowledge base.", mode="immediate")

    system = SimpleNamespace(
        engine=FakeEngine([{"content": "unused"}]),
        model="system-model",
        memory_backend=None,
        channel_backend=None,
        tool_executor=None,
        _mcp_clients=[],
        knowledge_db_path=knowledge_db_path,
        config=None,
        session_store=None,
    )
    executor = AgentExecutor(manager=manager, event_bus=EventBus(), system=system)

    try:
        executor.execute_tick(agent["id"])

        tools_by_name = {
            tool.spec.name: tool for tool in _CapturingToolAgent.captured_tools
        }
        assert set(tools_by_name) == {
            "knowledge_search",
            "knowledge_sql",
            "scan_chunks",
            "think",
        }
        result = _CapturingToolAgent.captured_search_result
        assert result is not None
        assert result.success is True
        assert "EXECUTOR_RESOLVER_SENTINEL" in result.content
        assert tools_by_name["scan_chunks"]._model == "agent-selected-model"
        assert manager.get_agent(agent["id"])["status"] == "idle"
        with pytest.raises(sqlite3.ProgrammingError):
            tools_by_name["knowledge_sql"]._store._conn.execute("SELECT 1")
    finally:
        manager.close()


def test_executor_mcp_opt_out_does_not_call_lazy_provider(tmp_path):
    """An opted-out tick must not trigger request-local MCP discovery."""

    AgentRegistry.register_value("capturing", _CapturingToolAgent)
    provider = MagicMock(side_effect=AssertionError("MCP discovery must stay lazy"))
    system = SimpleNamespace(
        engine=FakeEngine([{"content": "unused"}]),
        model="system-model",
        memory_backend=None,
        channel_backend=None,
        tool_executor=None,
        _mcp_clients=[],
        config=None,
        session_store=None,
        get_managed_agent_mcp_tools=provider,
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "no-mcp",
        agent_type="capturing",
        config={"model": "test-model", "mcp_tools": False},
    )

    try:
        AgentExecutor(manager, EventBus(), system=system).execute_tick(agent["id"])
        provider.assert_not_called()
        assert manager.get_agent(agent["id"])["status"] == "idle"
    finally:
        manager.close()


def test_executor_preserves_custom_dict_tool_schema(tmp_path):
    """Executor-based agents see the same custom schema advertised by SSE."""

    from openjarvis.tools.think import ThinkTool

    AgentRegistry.register_value("capturing", _CapturingToolAgent)
    ToolRegistry.register_value("think", ThinkTool)
    _CapturingToolAgent.captured_tools = []
    custom_spec = {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Agent-specific thinking schema",
            "parameters": {
                "type": "object",
                "properties": {"thought": {"type": "string"}},
                "required": ["thought"],
            },
        },
    }
    system = SimpleNamespace(
        engine=FakeEngine([{"content": "unused"}]),
        model="test-model",
        memory_backend=None,
        channel_backend=None,
        tool_executor=None,
        mcp_tools=[],
        _mcp_clients=[],
        config=None,
        session_store=None,
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "custom-schema",
        agent_type="capturing",
        config={"model": "test-model", "tools": [custom_spec]},
    )

    try:
        AgentExecutor(manager, EventBus(), system=system).execute_tick(agent["id"])
        assert len(_CapturingToolAgent.captured_tools) == 1
        configured_tool = _CapturingToolAgent.captured_tools[0]
        assert configured_tool.to_openai_function() == custom_spec
        assert configured_tool.spec.description == "Agent-specific thinking schema"
        assert configured_tool.execute(thought="same instance").success is True
    finally:
        manager.close()


def test_executor_closes_resolver_resources_when_pre_run_setup_fails(
    tmp_path,
    monkeypatch,
):
    """The resolver finalizer covers failures before agent.run is reached."""

    AgentRegistry.register_value("capturing", _CapturingToolAgent)
    resource = MagicMock()

    def _resolve(*args, **kwargs):
        return ResolvedAgentTools(owned_resources=[resource])

    monkeypatch.setattr("openjarvis.agents.executor.resolve_agent_tools", _resolve)
    system = SimpleNamespace(
        engine=FakeEngine([{"content": "unused"}]),
        model="test-model",
        memory_backend=None,
        channel_backend=None,
        tool_executor=None,
        mcp_tools=[],
        _mcp_clients=[],
        config=None,
        session_store=None,
    )
    manager = AgentManager(db_path=str(tmp_path / "agents.db"))
    agent = manager.create_agent(
        "cleanup",
        agent_type="capturing",
        config={"model": "test-model"},
    )
    monkeypatch.setattr(
        manager,
        "get_pending_messages",
        MagicMock(side_effect=RuntimeError("pre-run setup failed")),
    )

    try:
        with pytest.raises(RuntimeError, match="pre-run setup failed"):
            AgentExecutor(manager, EventBus(), system=system)._invoke_agent(agent)
        gc.collect()
        resource.close.assert_called_once_with()
    finally:
        manager.close()
