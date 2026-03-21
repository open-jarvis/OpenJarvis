"""Tests for ``jarvis ask --agent`` CLI integration."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.cli import cli
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_ask_mod = importlib.import_module("openjarvis.cli.ask")


def _mock_engine(content="Hello from engine"):
    """Create a mock engine that returns content."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _register_agents():
    """Re-register agents after registry clear."""
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.agents.simple import SimpleAgent
    from openjarvis.core.registry import AgentRegistry

    for name, cls in [
        ("simple", SimpleAgent),
        ("orchestrator", OrchestratorAgent),
    ]:
        if not AgentRegistry.contains(name):
            AgentRegistry.register_value(name, cls)


def _register_tools():
    """Re-register tools after registry clear."""
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.tools.calculator import CalculatorTool
    from openjarvis.tools.file_read import FileReadTool
    from openjarvis.tools.llm_tool import LLMTool
    from openjarvis.tools.retrieval import RetrievalTool
    from openjarvis.tools.think import ThinkTool

    for name, cls in [
        ("calculator", CalculatorTool),
        ("think", ThinkTool),
        ("retrieval", RetrievalTool),
        ("llm", LLMTool),
        ("file_read", FileReadTool),
    ]:
        if not ToolRegistry.contains(name):
            ToolRegistry.register_value(name, cls)


class _DangerousTool(BaseTool):
    tool_id = "dangerous"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dangerous",
            description="Confirmation-gated test tool.",
            requires_confirmation=True,
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="dangerous",
            content="executed!",
            success=True,
        )


class _ConfirmingAgent(ToolUsingAgent):
    agent_id = "confirming_agent"

    def run(self, input, context: AgentContext | None = None, **kwargs):
        result = self._executor.execute(
            ToolCall(id="confirm", name="dangerous", arguments="{}")
        )
        return AgentResult(
            content=result.content,
            tool_results=[result],
            turns=1,
        )


@dataclass
class _EngineSetup:
    engine: MagicMock
    config: object


@pytest.fixture
def agent_setup():
    from openjarvis.core.config import JarvisConfig
    from openjarvis.core.registry import AgentRegistry, ToolRegistry

    engine = _mock_engine("unused")
    config = JarvisConfig()
    config.intelligence.default_model = "test-model"
    config.agent.max_turns = 3

    AgentRegistry.register_value("confirming_agent", _ConfirmingAgent)
    ToolRegistry.register_value("dangerous", _DangerousTool)

    with (
        patch.object(_ask_mod, "load_config", return_value=config),
        patch.object(_ask_mod, "get_engine", return_value=("mock", engine)),
        patch.object(_ask_mod, "discover_engines", return_value=[("mock", engine)]),
        patch.object(
            _ask_mod,
            "discover_models",
            return_value={"mock": ["test-model"]},
        ),
        patch.object(_ask_mod, "register_builtin_models"),
        patch.object(_ask_mod, "merge_discovered_models"),
    ):
        yield _EngineSetup(engine=engine, config=config)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_setup():
    """Patch engine discovery to avoid needing a running engine."""
    engine = _mock_engine()
    _register_agents()
    _register_tools()
    with (
        patch.object(_ask_mod, "load_config") as mock_cfg,
        patch.object(_ask_mod, "get_engine") as mock_ge,
        patch.object(_ask_mod, "discover_engines") as mock_de,
        patch.object(_ask_mod, "discover_models") as mock_dm,
        patch.object(_ask_mod, "register_builtin_models"),
        patch.object(_ask_mod, "merge_discovered_models"),
    ):
        from openjarvis.core.config import JarvisConfig

        mock_cfg.return_value = JarvisConfig()
        mock_ge.return_value = ("mock", engine)
        mock_de.return_value = [("mock", engine)]
        mock_dm.return_value = {"mock": ["test-model"]}
        yield engine


class TestAskAgentOption:
    def test_help_shows_agent_option(self, runner):
        result = runner.invoke(cli, ["ask", "--help"])
        assert "--agent" in result.output or "-a" in result.output

    def test_help_shows_tools_option(self, runner):
        result = runner.invoke(cli, ["ask", "--help"])
        assert "--tools" in result.output

    def test_agent_simple(self, runner, mock_setup):
        result = runner.invoke(cli, ["ask", "--agent", "simple", "Hello"])
        assert result.exit_code == 0
        assert "Hello from engine" in result.output

    def test_agent_orchestrator_no_tools(self, runner, mock_setup):
        result = runner.invoke(
            cli,
            ["ask", "--agent", "orchestrator", "Hello"],
        )
        assert result.exit_code == 0

    def test_agent_orchestrator_with_tools(self, runner, mock_setup):
        result = runner.invoke(
            cli,
            [
                "ask",
                "--agent",
                "orchestrator",
                "--tools",
                "calculator,think",
                "What is 2+2?",
            ],
        )
        assert result.exit_code == 0

    def test_agent_json_output(self, runner, mock_setup):
        result = runner.invoke(
            cli,
            ["ask", "--agent", "simple", "--json", "Hello"],
        )
        assert result.exit_code == 0
        assert '"content"' in result.output
        assert '"turns"' in result.output

    def test_unknown_agent(self, runner, mock_setup):
        result = runner.invoke(
            cli,
            ["ask", "--agent", "nonexistent", "Hello"],
        )
        assert result.exit_code != 0

    def test_no_agent_uses_direct_mode(self, runner, mock_setup):
        result = runner.invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
        assert "Hello from engine" in result.output

    def test_agent_simple_with_model(self, runner, mock_setup):
        result = runner.invoke(
            cli,
            ["ask", "--agent", "simple", "-m", "test-model", "Hello"],
        )
        assert result.exit_code == 0

    def test_agent_simple_with_temperature(self, runner, mock_setup):
        result = runner.invoke(
            cli,
            ["ask", "--agent", "simple", "-t", "0.1", "Hello"],
        )
        assert result.exit_code == 0

    @pytest.mark.parametrize(
        ("tools_enabled", "agent_tools"),
        [
            (["dangerous"], ""),
            ("dangerous", ""),
            ("", "dangerous"),
        ],
    )
    def test_agent_uses_configured_tools_by_default(
        self,
        runner,
        agent_setup,
        tools_enabled,
        agent_tools,
    ):
        agent_setup.config.tools.enabled = tools_enabled
        agent_setup.config.agent.tools = agent_tools

        result = runner.invoke(
            cli,
            ["ask", "--agent", "confirming_agent", "Hello"],
        )

        assert result.exit_code == 0
        assert "executed!" in result.output
        agent_setup.engine.generate.assert_not_called()


class TestBuildTools:
    def test_build_calculator(self, mock_setup):
        from openjarvis.cli.ask import _build_tools
        from openjarvis.core.config import JarvisConfig

        _register_tools()
        config = JarvisConfig()
        tools = _build_tools(["calculator"], config, mock_setup, "test-model")
        assert len(tools) == 1
        assert tools[0].tool_id == "calculator"

    def test_build_think(self, mock_setup):
        from openjarvis.cli.ask import _build_tools
        from openjarvis.core.config import JarvisConfig

        _register_tools()
        config = JarvisConfig()
        tools = _build_tools(["think"], config, mock_setup, "test-model")
        assert len(tools) == 1
        assert tools[0].tool_id == "think"

    def test_build_unknown_tool_skipped(self, mock_setup):
        from openjarvis.cli.ask import _build_tools
        from openjarvis.core.config import JarvisConfig

        config = JarvisConfig()
        tools = _build_tools(["nonexistent"], config, mock_setup, "test-model")
        assert len(tools) == 0

    def test_build_empty_names(self, mock_setup):
        from openjarvis.cli.ask import _build_tools
        from openjarvis.core.config import JarvisConfig

        config = JarvisConfig()
        tools = _build_tools(["", " "], config, mock_setup, "test-model")
        assert len(tools) == 0

    def test_build_multiple_tools(self, mock_setup):
        from openjarvis.cli.ask import _build_tools
        from openjarvis.core.config import JarvisConfig

        _register_tools()
        config = JarvisConfig()
        tools = _build_tools(["calculator", "think"], config, mock_setup, "test-model")
        assert len(tools) == 2
