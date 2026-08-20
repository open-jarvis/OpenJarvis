"""Regression test for #753: a failed MCP handshake in
``SystemBuilder._discover_external_mcp`` must not leak the spawned
subprocess / HTTP client.

``client.initialize()`` used to be called before the client was appended
to ``self._mcp_clients``. When ``initialize()`` raised (malformed JSON
output, auth errors, protocol issues), the client was never appended --
and since nothing else holds a reference to it, ``close()`` never ran,
leaving the underlying ``StdioTransport`` subprocess or
``StreamableHTTPTransport`` connection pool running indefinitely.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.system.builder import SystemBuilder


@pytest.fixture
def _mock_mcp_stack():
    """Patch MCPClient / transports / MCPToolProvider so no real I/O happens."""
    with (
        patch("openjarvis.mcp.client.MCPClient") as MockClient,
        patch("openjarvis.mcp.transport.StreamableHTTPTransport") as MockHttp,
        patch("openjarvis.mcp.transport.StdioTransport") as MockStdio,
        patch("openjarvis.tools.mcp_adapter.MCPToolProvider") as MockProvider,
    ):
        MockProvider.return_value.discover.return_value = []
        MockClient.return_value.initialize.return_value = None
        yield {
            "client": MockClient,
            "http": MockHttp,
            "stdio": MockStdio,
            "provider": MockProvider,
        }


def test_failed_initialize_closes_the_client(_mock_mcp_stack, caplog):
    builder = SystemBuilder(config=JarvisConfig())

    bad_client = MagicMock()
    bad_client.initialize.side_effect = RuntimeError("handshake failed")
    bad_client.close.side_effect = RuntimeError("cleanup failed")
    _mock_mcp_stack["client"].return_value = bad_client

    with (
        caplog.at_level("WARNING"),
        pytest.raises(RuntimeError, match="handshake failed"),
    ):
        builder._discover_external_mcp({"name": "broken", "url": "http://broken"})

    assert bad_client not in builder._mcp_clients
    bad_client.close.assert_called_once()
    assert any("cleanup failed" in record.getMessage() for record in caplog.records)
