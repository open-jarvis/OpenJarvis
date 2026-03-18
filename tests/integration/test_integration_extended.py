"""Extended integration tests for new components (Phase 6+)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry, ToolRegistry
from openjarvis.core.types import (
    Conversation,
    Message,
    Role,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_all():
    """Ensure agents and tools are registered."""
    from openjarvis.agents.native_openhands import NativeOpenHandsAgent
    from openjarvis.agents.native_react import NativeReActAgent
    from openjarvis.tools.calculator import CalculatorTool
    from openjarvis.tools.think import ThinkTool

    for key, cls in [
        ("native_react", NativeReActAgent),
        ("native_openhands", NativeOpenHandsAgent),
    ]:
        if not AgentRegistry.contains(key):
            AgentRegistry.register_value(key, cls)

    for key, cls in [
        ("calculator", CalculatorTool),
        ("think", ThinkTool),
    ]:
        if not ToolRegistry.contains(key):
            ToolRegistry.register_value(key, cls)


def _make_engine(responses):
    """Create a mock engine returning a sequence of responses."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    if isinstance(responses, list):
        engine.generate.side_effect = responses
    else:
        engine.generate.return_value = responses
    return engine


def _simple_response(content, model="test-model"):
    return {
        "content": content,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        "model": model,
        "finish_reason": "stop",
    }


# ---------------------------------------------------------------------------
# ReAct pipeline integration
# ---------------------------------------------------------------------------


class TestReActPipeline:
    """End-to-end: ReAct agent with calculator tool."""

    def test_react_with_calculator_e2e(self):
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent
        from openjarvis.tools.calculator import CalculatorTool

        responses = [
            _simple_response(
                "Thought: I need to calculate 2+2.\n"
                "Action: calculator\n"
                'Action Input: {"expression":"2+2"}'
            ),
            _simple_response("Thought: The result is 4.\nFinal Answer: 2+2 equals 4."),
        ]
        engine = _make_engine(responses)
        bus = EventBus(record_history=True)
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[CalculatorTool()],
            bus=bus,
        )
        result = agent.run("What is 2+2?")

        assert isinstance(result, AgentResult)
        assert "4" in result.content
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].content == "4.0"

    def test_react_with_think_tool(self):
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent
        from openjarvis.tools.think import ThinkTool

        responses = [
            _simple_response(
                "Thought: Let me reason about this.\n"
                "Action: think\n"
                'Action Input: {"thought":"Step 1: analyze"}'
            ),
            _simple_response(
                "Thought: I have my analysis.\nFinal Answer: The answer is clear."
            ),
        ]
        engine = _make_engine(responses)
        agent = NativeReActAgent(
            engine,
            "test-model",
            tools=[ThinkTool()],
        )
        result = agent.run("Analyze this.")
        assert result.turns == 2
        assert result.tool_results[0].success is True

    def test_react_direct_answer(self):
        """ReAct returns immediately when no tool use is needed."""
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent

        engine = _make_engine(
            _simple_response("Thought: This is simple.\nFinal Answer: Hello!")
        )
        agent = NativeReActAgent(engine, "test-model")
        result = agent.run("Say hello")
        assert result.content == "Hello!"
        assert result.turns == 1

    def test_react_event_chain(self):
        """Verify agent-level event chain through ReAct run.

        INFERENCE_START/END are now published by InstrumentedEngine,
        not by agents directly.
        """
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent

        engine = _make_engine(_simple_response("Thought: done.\nFinal Answer: ok"))
        bus = EventBus(record_history=True)
        agent = NativeReActAgent(
            engine,
            "test-model",
            bus=bus,
        )
        agent.run("Test")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in types
        assert EventType.AGENT_TURN_END in types


# ---------------------------------------------------------------------------
# OpenHands pipeline integration
# ---------------------------------------------------------------------------


class TestOpenHandsPipeline:
    """End-to-end: OpenHands agent with code execution."""

    def test_openhands_code_execution_e2e(self):
        _register_all()
        from openjarvis.agents.native_openhands import NativeOpenHandsAgent
        from openjarvis.tools.code_interpreter import (
            CodeInterpreterTool,
        )

        if not ToolRegistry.contains("code_interpreter"):
            ToolRegistry.register_value(
                "code_interpreter",
                CodeInterpreterTool,
            )

        responses = [
            _simple_response("I'll calculate this:\n```python\nprint(2 + 2)\n```"),
            _simple_response("The result is 4."),
        ]
        engine = _make_engine(responses)
        agent = NativeOpenHandsAgent(
            engine,
            "test-model",
            tools=[CodeInterpreterTool()],
        )
        result = agent.run("What is 2+2?")

        assert isinstance(result, AgentResult)
        assert result.turns == 2
        assert len(result.tool_results) == 1
        # The code_interpreter actually runs print(2+2)
        assert "4" in result.tool_results[0].content

    def test_openhands_direct_answer(self):
        """OpenHands returns directly when no code is needed."""
        _register_all()
        from openjarvis.agents.native_openhands import NativeOpenHandsAgent

        engine = _make_engine(_simple_response("Hello! How can I help?"))
        agent = NativeOpenHandsAgent(engine, "test-model")
        result = agent.run("Say hello")
        assert result.content == "Hello! How can I help?"
        assert result.turns == 1

    def test_openhands_event_chain(self):
        """Verify event chain through OpenHands run."""
        _register_all()
        from openjarvis.agents.native_openhands import NativeOpenHandsAgent

        engine = _make_engine(_simple_response("Direct answer."))
        bus = EventBus(record_history=True)
        agent = NativeOpenHandsAgent(
            engine,
            "test-model",
            bus=bus,
        )
        agent.run("Test")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in types
        assert EventType.AGENT_TURN_END in types


# ---------------------------------------------------------------------------
# MCP integration
# ---------------------------------------------------------------------------


class TestMCPIntegration:
    """MCP server + client with real tools."""

    def test_mcp_server_with_all_tools(self):
        from openjarvis.mcp.client import MCPClient
        from openjarvis.mcp.server import MCPServer
        from openjarvis.mcp.transport import InProcessTransport
        from openjarvis.tools.calculator import CalculatorTool
        from openjarvis.tools.think import ThinkTool

        tools = [CalculatorTool(), ThinkTool()]
        server = MCPServer(tools)
        transport = InProcessTransport(server)
        client = MCPClient(transport)

        # Initialize
        caps = client.initialize()
        assert "serverInfo" in caps

        # List tools
        specs = client.list_tools()
        names = [s.name for s in specs]
        assert "calculator" in names
        assert "think" in names

        # Call calculator
        result = client.call_tool(
            "calculator",
            {"expression": "10*5"},
        )
        assert result["content"][0]["text"] == "50.0"
        assert result["isError"] is False

        # Call think
        result = client.call_tool(
            "think",
            {"thought": "reasoning step"},
        )
        assert result["content"][0]["text"] == "reasoning step"

        client.close()

    def test_mcp_unknown_tool_error(self):
        from openjarvis.mcp.client import MCPClient
        from openjarvis.mcp.protocol import MCPError
        from openjarvis.mcp.server import MCPServer
        from openjarvis.mcp.transport import InProcessTransport
        from openjarvis.tools.calculator import CalculatorTool

        server = MCPServer([CalculatorTool()])
        client = MCPClient(InProcessTransport(server))
        client.initialize()

        with pytest.raises(MCPError):
            client.call_tool("nonexistent", {})

        client.close()

    def test_mcp_roundtrip_lifecycle(self):
        """Full lifecycle: init -> list -> call -> result."""
        from openjarvis.mcp.client import MCPClient
        from openjarvis.mcp.server import MCPServer
        from openjarvis.mcp.transport import InProcessTransport
        from openjarvis.tools.calculator import CalculatorTool

        server = MCPServer([CalculatorTool()])
        client = MCPClient(InProcessTransport(server))

        # 1. Initialize
        caps = client.initialize()
        assert caps["protocolVersion"] == "2025-11-25"

        # 2. Discover tools
        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "calculator"

        # 3. Call tool
        result = client.call_tool(
            "calculator",
            {"expression": "7+3"},
        )
        assert result["content"][0]["text"] == "10.0"

        # 4. Close
        client.close()


# ---------------------------------------------------------------------------
# Cross-engine consistency
# ---------------------------------------------------------------------------


class TestCrossEngineConsistency:
    """Same query through different mock engine configs."""

    def test_same_query_same_format(self):
        """All engines return the same result dict shape."""
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent

        for engine_name in ["vllm", "ollama", "mock"]:
            engine = _make_engine(
                _simple_response(
                    "Thought: ok.\nFinal Answer: Result",
                    model="test-model",
                )
            )
            engine.engine_id = engine_name
            agent = NativeReActAgent(engine, "test-model")
            result = agent.run("Test query")
            assert isinstance(result, AgentResult)
            assert result.content == "Result"

    def test_tool_calls_across_engines(self):
        """Tool calling works regardless of engine mock."""
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent
        from openjarvis.tools.calculator import CalculatorTool

        for engine_name in ["vllm", "ollama"]:
            responses = [
                _simple_response(
                    "Thought: calc.\n"
                    "Action: calculator\n"
                    'Action Input: {"expression":"3*3"}'
                ),
                _simple_response("Thought: got 9.\nFinal Answer: 9"),
            ]
            engine = _make_engine(responses)
            engine.engine_id = engine_name
            agent = NativeReActAgent(
                engine,
                "test-model",
                tools=[CalculatorTool()],
            )
            result = agent.run("What is 3*3?")
            assert result.content == "9"
            tr = result.tool_results[0]
            assert tr.content == "9.0"
            assert tr.success is True


# ---------------------------------------------------------------------------
# Memory pipeline integration
# ---------------------------------------------------------------------------


class TestMemoryPipeline:
    """Index and retrieve across available backends."""

    def test_sqlite_index_and_retrieve(self, tmp_path):
        from openjarvis.tools.storage.sqlite import SQLiteMemory

        backend = SQLiteMemory(db_path=str(tmp_path / "mem.db"))
        backend.store(
            "Machine learning uses data to learn patterns",
            source="ml.md",
        )
        backend.store(
            "Python is a versatile programming language",
            source="py.md",
        )
        results = backend.retrieve("machine learning")
        assert len(results) >= 1
        assert "machine" in results[0].content.lower()

    def test_bm25_index_and_retrieve(self, tmp_path):
        try:
            from openjarvis.tools.storage.bm25 import BM25Memory
        except ImportError:
            pytest.skip("rank_bm25 not installed")

        backend = BM25Memory()
        backend.store("Neural networks for NLP", source="a.md")
        backend.store("Database indexing strategies", source="b.md")
        results = backend.retrieve("neural NLP")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Model catalog integration
# ---------------------------------------------------------------------------


class TestModelCatalogIntegration:
    """All registered models have valid metadata."""

    def test_all_models_routable(self):
        """Every model in catalog has required fields."""
        from openjarvis.intelligence.model_catalog import (
            BUILTIN_MODELS,
        )

        for spec in BUILTIN_MODELS:
            assert spec.model_id, "model_id required"
            assert spec.context_length > 0
            if spec.requires_api_key:
                assert spec.provider

    def test_local_models_have_engine_compat(self):
        """Every local model has at least one engine."""
        from openjarvis.intelligence.model_catalog import (
            BUILTIN_MODELS,
        )

        local = [s for s in BUILTIN_MODELS if not s.requires_api_key]
        for spec in local:
            assert len(spec.supported_engines) >= 1, f"{spec.model_id} has no engines"

    def test_cloud_models_require_api_key(self):
        """All cloud models require an API key."""
        from openjarvis.intelligence.model_catalog import (
            BUILTIN_MODELS,
        )

        cloud_ids = [
            "gpt-5-mini",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-pro",
            "gemini-3-flash",
        ]
        for mid in cloud_ids:
            matches = [s for s in BUILTIN_MODELS if s.model_id == mid]
            assert len(matches) == 1, f"Missing {mid}"
            assert matches[0].requires_api_key is True


# ---------------------------------------------------------------------------
# Agent routing matrix (lightweight integration)
# ---------------------------------------------------------------------------


class TestAgentRoutingMatrix:
    """Agents run consistently across different configurations."""

    @pytest.mark.parametrize(
        "agent_key",
        ["native_react", "native_openhands"],
    )
    def test_agent_returns_valid_result(self, agent_key):
        _register_all()

        engine = _make_engine(
            _simple_response(
                "Thought: done.\nFinal Answer: ok"
                if agent_key == "native_react"
                else "The answer is ok"
            )
        )
        agent_cls = AgentRegistry.get(agent_key)
        agent = agent_cls(engine, "test-model")
        result = agent.run("Test")

        assert isinstance(result, AgentResult)
        assert result.turns >= 1
        assert len(result.content) > 0

    @pytest.mark.parametrize(
        "agent_key",
        ["native_react", "native_openhands"],
    )
    def test_agent_emits_events(self, agent_key):
        _register_all()

        engine = _make_engine(
            _simple_response(
                "Thought: done.\nFinal Answer: ok"
                if agent_key == "native_react"
                else "Direct answer"
            )
        )
        bus = EventBus(record_history=True)
        agent_cls = AgentRegistry.get(agent_key)
        agent = agent_cls(engine, "test-model", bus=bus)
        agent.run("Test")

        types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in types
        assert EventType.AGENT_TURN_END in types

    def test_context_passing(self):
        """Agents accept and use AgentContext."""
        _register_all()
        from openjarvis.agents.native_react import NativeReActAgent

        engine = _make_engine(
            _simple_response(
                "Thought: I see the system message.\nFinal Answer: Got context."
            )
        )
        conv = Conversation()
        conv.add(
            Message(
                role=Role.SYSTEM,
                content="You are helpful.",
            )
        )
        ctx = AgentContext(conversation=conv)
        agent = NativeReActAgent(engine, "test-model")
        result = agent.run("Hello", context=ctx)
        assert result.content == "Got context."

        # Verify engine received system message
        call_args = engine.generate.call_args
        msgs = call_args[0][0]
        # First message is ReAct system prompt, then context
        assert any(m.content == "You are helpful." for m in msgs)
