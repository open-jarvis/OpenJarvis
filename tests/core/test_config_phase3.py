"""Tests for Phase 3 config additions (AgentConfig expansion, ServerConfig)."""

from __future__ import annotations

from openjarvis.core.config import (
    AgentConfig,
    HardwareInfo,
    JarvisConfig,
    ServerConfig,
    generate_default_toml,
)


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig()
        assert cfg.default_agent == "simple"
        assert cfg.max_turns == 10
        assert cfg.tools == ""
        assert cfg.default_tools == ""  # backward-compat property
        assert cfg.objective == ""
        assert cfg.system_prompt == ""
        assert cfg.system_prompt_path == ""
        assert cfg.context_from_memory is True

    def test_custom_values(self):
        cfg = AgentConfig(
            default_agent="orchestrator",
            max_turns=5,
            tools="calculator,think",
        )
        assert cfg.default_agent == "orchestrator"
        assert cfg.tools == "calculator,think"
        assert cfg.default_tools == "calculator,think"  # backward-compat


class TestServerConfig:
    def test_defaults(self):
        cfg = ServerConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.agent == "orchestrator"
        assert cfg.model == ""
        assert cfg.workers == 1

    def test_custom_values(self):
        cfg = ServerConfig(host="127.0.0.1", port=9000, agent="simple")
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9000


class TestJarvisConfig:
    def test_has_server(self):
        cfg = JarvisConfig()
        assert hasattr(cfg, "server")
        assert isinstance(cfg.server, ServerConfig)

    def test_agent_config_expanded(self):
        cfg = JarvisConfig()
        assert hasattr(cfg.agent, "default_tools")  # backward-compat property
        assert hasattr(cfg.agent, "tools")
        assert hasattr(cfg.agent, "objective")
        assert hasattr(cfg.agent, "system_prompt")
        assert hasattr(cfg.agent, "context_from_memory")


class TestGenerateDefaultToml:
    def test_includes_server_section(self):
        hw = HardwareInfo(cpu_brand="Test CPU", cpu_count=4, ram_gb=16.0)
        toml_str = generate_default_toml(hw)
        assert "[server]" in toml_str
        assert "port = 8000" in toml_str

    def test_includes_agent_section(self):
        hw = HardwareInfo()
        toml_str = generate_default_toml(hw)
        assert "[agent]" in toml_str
        assert "default_agent" in toml_str
