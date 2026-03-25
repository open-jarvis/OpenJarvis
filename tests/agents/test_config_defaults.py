"""Tests for agent constructor config-based default resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.agents._stubs import AgentResult, BaseAgent, ToolUsingAgent


class _TestAgent(BaseAgent):
    agent_id = "test_cfg"

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="ok", turns=1)


class _TestToolAgent(ToolUsingAgent):
    agent_id = "test_cfg_tool"

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="ok", turns=1)


class _TestToolAgentWithDefaults(ToolUsingAgent):
    """Agent with class-level defaults (like MonitorOperativeAgent)."""

    agent_id = "test_cfg_tool_defaults"
    _default_temperature = 0.3
    _default_max_tokens = 4096
    _default_max_turns = 25

    def run(self, input, context=None, **kwargs):
        return AgentResult(content="ok", turns=1)


class TestBaseAgentConfigResolution:
    """BaseAgent resolves None params from config.intelligence."""

    def test_none_temperature_reads_config(self):
        """When temperature is not passed, it should come from config."""
        engine = MagicMock()
        with patch("openjarvis.agents._stubs.load_config") as mock_cfg:
            mock_cfg.return_value.intelligence.temperature = 0.2
            mock_cfg.return_value.intelligence.max_tokens = 512
            agent = _TestAgent(engine, "m")
        assert agent._temperature == 0.2

    def test_none_max_tokens_reads_config(self):
        """When max_tokens is not passed, it should come from config."""
        engine = MagicMock()
        with patch("openjarvis.agents._stubs.load_config") as mock_cfg:
            mock_cfg.return_value.intelligence.temperature = 0.7
            mock_cfg.return_value.intelligence.max_tokens = 512
            agent = _TestAgent(engine, "m")
        assert agent._max_tokens == 512

    def test_explicit_temperature_overrides_config(self):
        """Caller-provided temperature takes precedence over config."""
        engine = MagicMock()
        agent = _TestAgent(engine, "m", temperature=0.9)
        assert agent._temperature == 0.9

    def test_explicit_max_tokens_overrides_config(self):
        """Caller-provided max_tokens takes precedence over config."""
        engine = MagicMock()
        agent = _TestAgent(engine, "m", max_tokens=2048)
        assert agent._max_tokens == 2048

    def test_partial_override_temperature_only(self):
        """Providing only temperature still reads max_tokens from config."""
        engine = MagicMock()
        with patch("openjarvis.agents._stubs.load_config") as mock_cfg:
            mock_cfg.return_value.intelligence.temperature = 0.2
            mock_cfg.return_value.intelligence.max_tokens = 512
            agent = _TestAgent(engine, "m", temperature=0.9)
        assert agent._temperature == 0.9
        assert agent._max_tokens == 512

    def test_config_load_failure_uses_hardcoded_fallback(self):
        """When config loading fails, fall back to class defaults then 0.7/1024."""
        engine = MagicMock()
        with patch(
            "openjarvis.agents._stubs.load_config",
            side_effect=Exception("boom"),
        ):
            agent = _TestAgent(engine, "m")
        assert agent._temperature == 0.7
        assert agent._max_tokens == 1024


class TestToolUsingAgentConfigResolution:
    """ToolUsingAgent resolves None max_turns from config.agent."""

    def test_none_max_turns_reads_config(self):
        """When max_turns is not passed, it should come from config."""
        engine = MagicMock()
        with patch("openjarvis.agents._stubs.load_config") as mock_cfg:
            mock_cfg.return_value.intelligence.temperature = 0.7
            mock_cfg.return_value.intelligence.max_tokens = 1024
            mock_cfg.return_value.agent.max_turns = 15
            agent = _TestToolAgent(engine, "m")
        assert agent._max_turns == 15

    def test_explicit_max_turns_overrides_config(self):
        """Caller-provided max_turns takes precedence over config."""
        engine = MagicMock()
        agent = _TestToolAgent(engine, "m", max_turns=5)
        assert agent._max_turns == 5

    def test_temperature_and_max_tokens_forwarded_to_base(self):
        """ToolUsingAgent also resolves temperature/max_tokens from config."""
        engine = MagicMock()
        with patch("openjarvis.agents._stubs.load_config") as mock_cfg:
            mock_cfg.return_value.intelligence.temperature = 0.1
            mock_cfg.return_value.intelligence.max_tokens = 256
            mock_cfg.return_value.agent.max_turns = 10
            agent = _TestToolAgent(engine, "m")
        assert agent._temperature == 0.1
        assert agent._max_tokens == 256

    def test_config_load_failure_max_turns_fallback(self):
        """When config loading fails, max_turns falls back to class default then 10."""
        engine = MagicMock()
        with patch(
            "openjarvis.agents._stubs.load_config",
            side_effect=Exception("boom"),
        ):
            agent = _TestToolAgent(engine, "m")
        assert agent._max_turns == 10


class TestClassLevelDefaults:
    """Agents with class-level _default_* attributes use them as fallback."""

    def test_class_default_used_when_config_fails(self):
        """Agent class defaults are used when config is unavailable."""
        engine = MagicMock()
        with patch(
            "openjarvis.agents._stubs.load_config",
            side_effect=Exception("boom"),
        ):
            agent = _TestToolAgentWithDefaults(engine, "m")
        assert agent._temperature == 0.3
        assert agent._max_tokens == 4096
        assert agent._max_turns == 25

    def test_config_overrides_class_default(self):
        """User config takes precedence over class-level defaults."""
        engine = MagicMock()
        with patch("openjarvis.agents._stubs.load_config") as mock_cfg:
            mock_cfg.return_value.intelligence.temperature = 0.5
            mock_cfg.return_value.intelligence.max_tokens = 2048
            mock_cfg.return_value.agent.max_turns = 12
            agent = _TestToolAgentWithDefaults(engine, "m")
        assert agent._temperature == 0.5
        assert agent._max_tokens == 2048
        assert agent._max_turns == 12

    def test_explicit_overrides_everything(self):
        """Caller-provided values override both config and class defaults."""
        engine = MagicMock()
        agent = _TestToolAgentWithDefaults(
            engine,
            "m",
            temperature=0.9,
            max_tokens=100,
            max_turns=2,
        )
        assert agent._temperature == 0.9
        assert agent._max_tokens == 100
        assert agent._max_turns == 2
