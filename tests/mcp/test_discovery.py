"""Tests for _discover_external_mcp in SystemBuilder."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.tools._stubs import ToolSpec


def _make_mock_tool(name: str) -> MagicMock:
    """Create a mock BaseTool with the given name."""
    tool = MagicMock()
    tool.spec = ToolSpec(name=name, description=f"Mock {name}")
    return tool


@pytest.fixture
def builder():
    """Create a minimal SystemBuilder instance for testing _discover_external_mcp."""
    from openjarvis.system import SystemBuilder

    def _minimal_init(self):
        self._mcp_clients = []

    with patch.object(SystemBuilder, "__init__", _minimal_init):
        instance = SystemBuilder.__new__(SystemBuilder)
        instance.__init__()
        return instance


# Patch targets: the method uses local imports, so we patch the actual classes
# in their source modules (which is where the local from-imports resolve to).
_PATCH_HTTP = "openjarvis.mcp.transport.StreamableHTTPTransport"
_PATCH_STDIO = "openjarvis.mcp.transport.StdioTransport"
_PATCH_CLIENT = "openjarvis.mcp.client.MCPClient"
_PATCH_PROVIDER = "openjarvis.tools.mcp_adapter.MCPToolProvider"
_PATCH_LOGGER = "openjarvis.system.builder.logger"


class TestDiscoverHTTPServer:
    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_HTTP)
    def test_url_config_uses_http_transport(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """Config with 'url' should create StreamableHTTPTransport."""
        mock_tools = [_make_mock_tool("get_entities"), _make_mock_tool("call_service")]
        mock_provider_cls.return_value.discover.return_value = mock_tools

        cfg = {"name": "ha-mcp", "url": "http://172.16.3.1:9583/mcp"}
        result = builder._discover_external_mcp(cfg)

        # token=None is now forwarded explicitly (#461) so authenticated
        # MCP servers can use it; missing config field → None → no header.
        mock_transport_cls.assert_called_once_with(
            url="http://172.16.3.1:9583/mcp", token=None
        )
        mock_client_cls.return_value.initialize.assert_called_once()
        assert len(result) == 2
        assert result[0].spec.name == "get_entities"


class TestDiscoverStdioServer:
    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_STDIO)
    def test_command_config_uses_stdio_transport(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """Config with 'command' + 'args' should create StdioTransport."""
        mock_tools = [_make_mock_tool("read_file")]
        mock_provider_cls.return_value.discover.return_value = mock_tools

        cfg = {"name": "fs-server", "command": "node", "args": ["server.js", "--stdio"]}
        result = builder._discover_external_mcp(cfg)

        mock_transport_cls.assert_called_once_with(
            command=["node", "server.js", "--stdio"]
        )
        assert len(result) == 1
        assert result[0].spec.name == "read_file"


class TestDiscoverInvalidConfig:
    @patch(_PATCH_LOGGER)
    def test_no_url_no_command_returns_empty(self, mock_logger, builder):
        """Config with neither 'url' nor 'command' should return [] and log warning."""
        cfg = {"name": "broken-server"}
        result = builder._discover_external_mcp(cfg)

        assert result == []
        mock_logger.warning.assert_called_once()
        assert "neither" in mock_logger.warning.call_args[0][0].lower()


class TestToolFiltering:
    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_HTTP)
    def test_include_tools_filter(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """include_tools should keep only the listed tools."""
        mock_tools = [
            _make_mock_tool("tool1"),
            _make_mock_tool("tool2"),
            _make_mock_tool("tool3"),
        ]
        mock_provider_cls.return_value.discover.return_value = mock_tools

        cfg = {
            "name": "filtered",
            "url": "http://localhost:8080/mcp",
            "include_tools": ["tool1"],
        }
        result = builder._discover_external_mcp(cfg)

        assert len(result) == 1
        assert result[0].spec.name == "tool1"

    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_HTTP)
    def test_exclude_tools_filter(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """exclude_tools should remove the listed tools."""
        mock_tools = [
            _make_mock_tool("tool1"),
            _make_mock_tool("tool2"),
            _make_mock_tool("tool3"),
        ]
        mock_provider_cls.return_value.discover.return_value = mock_tools

        cfg = {
            "name": "filtered",
            "url": "http://localhost:8080/mcp",
            "exclude_tools": ["tool2"],
        }
        result = builder._discover_external_mcp(cfg)

        names = [t.spec.name for t in result]
        assert "tool2" not in names
        assert "tool1" in names
        assert "tool3" in names


class TestClientPersistence:
    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_HTTP)
    def test_client_stored_in_mcp_clients(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """After discovery, the MCPClient should be persisted on _mcp_clients."""
        mock_provider_cls.return_value.discover.return_value = []

        cfg = {"name": "test", "url": "http://localhost:8080/mcp"}
        builder._discover_external_mcp(cfg)

        assert hasattr(builder, "_mcp_clients")
        assert len(builder._mcp_clients) == 1
        assert builder._mcp_clients[0] is mock_client_cls.return_value

    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_HTTP)
    def test_multiple_servers_accumulate_clients(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """Multiple discover calls should accumulate clients."""
        mock_provider_cls.return_value.discover.return_value = []

        for i in range(3):
            cfg = {"name": f"server-{i}", "url": f"http://localhost:{8080 + i}/mcp"}
            builder._discover_external_mcp(cfg)

        assert len(builder._mcp_clients) == 3


def test_builder_retains_full_mcp_pool_for_managed_agents() -> None:
    """Global primary-agent filters must not trim managed-agent MCP tools."""

    from openjarvis.core.config import JarvisConfig
    from openjarvis.system import SystemBuilder

    config = JarvisConfig()
    config.tools.mcp.servers = json.dumps(
        [{"name": "test", "url": "http://localhost:8080/mcp"}]
    )
    external = _make_mock_tool("mcp_only")
    builder = SystemBuilder(config).tools(["native_only"])

    with (
        patch("openjarvis.mcp.server.MCPServer") as mcp_server_cls,
        patch.object(
            builder,
            "_discover_external_mcp",
            return_value=[external],
        ),
    ):
        mcp_server_cls.return_value.get_tools.return_value = []
        primary_tools = builder._resolve_tools(
            config,
            engine=MagicMock(),
            model="test-model",
            memory_backend=None,
        )

    assert primary_tools == []
    assert builder._mcp_tools == [external]


def test_builder_global_mcp_disable_prevents_discovery() -> None:
    """A global MCP disable is honored by every managed-agent entry path."""

    from openjarvis.core.config import JarvisConfig
    from openjarvis.system import SystemBuilder

    config = JarvisConfig()
    config.tools.mcp.enabled = False
    config.tools.mcp.servers = json.dumps(
        [{"name": "disabled", "url": "http://localhost:8080/mcp"}]
    )
    builder = SystemBuilder(config)

    with (
        patch("openjarvis.mcp.server.MCPServer") as mcp_server_cls,
        patch.object(builder, "_discover_external_mcp") as discover,
    ):
        mcp_server_cls.return_value.get_tools.return_value = []
        builder._resolve_tools(
            config,
            engine=MagicMock(),
            model="test-model",
            memory_backend=None,
        )

    discover.assert_not_called()
    assert builder._mcp_tools == []


def test_builder_resolves_external_file_from_config_directory(tmp_path) -> None:
    """SystemBuilder consumes file-backed MCP config on the primary path."""

    from openjarvis.core.config import JarvisConfig
    from openjarvis.system import SystemBuilder

    server_file = tmp_path / "mcp-servers.json"
    server_file.write_text(
        '[{"name": "file-server", "url": "http://localhost:8080/mcp"}]',
        encoding="utf-8",
    )
    config = JarvisConfig()
    config.tools.mcp.servers = server_file.name
    config._config_dir = tmp_path
    builder = SystemBuilder(config)

    with (
        patch("openjarvis.mcp.server.MCPServer") as mcp_server_cls,
        patch.object(builder, "_discover_external_mcp", return_value=[]) as discover,
    ):
        mcp_server_cls.return_value.get_tools.return_value = []
        builder._resolve_tools(
            config,
            engine=MagicMock(),
            model="test-model",
            memory_backend=None,
        )

    discover.assert_called_once_with(
        {"name": "file-server", "url": "http://localhost:8080/mcp"}
    )


def test_reused_builder_transfers_only_current_build_mcp_state() -> None:
    """Each built system exclusively owns its own MCP clients and tools."""

    from openjarvis.core.config import JarvisConfig
    from openjarvis.system import SystemBuilder

    config = JarvisConfig()
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.skills.enabled = False
    config.agent_manager.enabled = False
    config.tools.mcp.servers = json.dumps(
        [{"name": "test", "url": "http://localhost:8080/mcp"}]
    )

    engine = MagicMock(spec=["health", "can_serve", "generate", "list_models", "close"])
    engine.health.return_value = True
    first_tool = _make_mock_tool("first_mcp_tool")
    second_tool = _make_mock_tool("second_mcp_tool")
    first_client = MagicMock()
    second_client = MagicMock()
    discoveries = iter([(first_tool, first_client), (second_tool, second_client)])

    builder = (
        SystemBuilder(config)
        .engine_instance(engine)
        .model("test-model")
        .tools([])
        .telemetry(False)
        .traces(False)
        .speech(False)
    )

    def _discover(_server_cfg):
        tool, client = next(discoveries)
        builder._mcp_clients.append(client)
        return [tool]

    with (
        patch.object(builder, "_discover_external_mcp", side_effect=_discover),
        patch.object(builder, "_resolve_memory", return_value=None),
    ):
        first_system = builder.build()
        assert first_system.mcp_tools == [first_tool]
        assert first_system._mcp_clients == [first_client]
        assert builder._mcp_tools == []
        assert builder._mcp_clients == []
        first_system.close()

        second_system = builder.build()

    try:
        assert second_system.mcp_tools == [second_tool]
        assert second_system._mcp_clients == [second_client]
        assert first_client not in second_system._mcp_clients
        assert builder._mcp_tools == []
        assert builder._mcp_clients == []
    finally:
        second_system.close()

    first_client.close.assert_called_once()
    second_client.close.assert_called_once()


class TestStringConfig:
    @patch(_PATCH_PROVIDER)
    @patch(_PATCH_CLIENT)
    @patch(_PATCH_HTTP)
    def test_json_string_config_parsed(
        self, mock_transport_cls, mock_client_cls, mock_provider_cls, builder
    ):
        """Config passed as JSON string should be parsed correctly."""
        import json

        mock_provider_cls.return_value.discover.return_value = []

        cfg_str = json.dumps({"name": "test", "url": "http://localhost:8080/mcp"})
        builder._discover_external_mcp(cfg_str)

        # token=None is forwarded by the builder (#461) — see comment in
        # TestDiscoverHTTPServer.test_url_config_uses_http_transport.
        mock_transport_cls.assert_called_once_with(
            url="http://localhost:8080/mcp", token=None
        )
