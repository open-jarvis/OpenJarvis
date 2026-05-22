"""Tests for ``openjarvis.tools.factory.instantiate_tool``.

Pins the contract that memory/channel/llm tools get their dependencies
injected when built by name — the regression #395 reported was the
streaming managed-agent path getting ``backend=None`` and silently
failing on every call.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.channel_tools import ChannelSendTool
from openjarvis.tools.factory import (
    CHANNEL_TOOLS,
    MEMORY_TOOLS,
    instantiate_tool,
)
from openjarvis.tools.file_read import FileReadTool
from openjarvis.tools.llm_tool import LLMTool
from openjarvis.tools.storage_tools import MemoryStoreTool


@pytest.fixture
def _register_tools():
    """Re-register the tools each test needs after the autouse registry clear."""
    ToolRegistry.register_value("memory_store", MemoryStoreTool)
    ToolRegistry.register_value("channel_send", ChannelSendTool)
    ToolRegistry.register_value("llm", LLMTool)
    ToolRegistry.register_value("file_read", FileReadTool)


class _StubConfig:
    """Minimal stand-in for the app-config shape ``_get_memory_backend`` needs."""

    class _Mem:
        default_backend = "sqlite"
        db_path = "/tmp/test-factory.db"

    memory = _Mem()


def test_memory_tool_gets_backend_injected(_register_tools):
    sentinel = object()
    with patch(
        "openjarvis.cli.ask._get_memory_backend",
        return_value=sentinel,
    ):
        tool = instantiate_tool("memory_store", app_config=_StubConfig())
    assert tool is not None
    assert tool._backend is sentinel


def test_memory_tool_with_no_backend_warns_but_still_instantiates(
    _register_tools, caplog
):
    with (
        patch(
            "openjarvis.cli.ask._get_memory_backend",
            return_value=None,
        ),
        caplog.at_level(logging.WARNING, logger="openjarvis.tools.factory"),
    ):
        tool = instantiate_tool("memory_store", app_config=_StubConfig())
    assert tool is not None
    assert tool._backend is None
    assert any(
        "no memory backend is available" in rec.message for rec in caplog.records
    )


def test_channel_tool_gets_channel_injected(_register_tools):
    sentinel = MagicMock()
    tool = instantiate_tool(
        "channel_send",
        app_config=_StubConfig(),
        channel=sentinel,
    )
    assert tool is not None
    assert tool._channel is sentinel


def test_llm_tool_gets_engine_and_model(_register_tools):
    engine_sentinel = MagicMock()
    tool = instantiate_tool(
        "llm",
        app_config=_StubConfig(),
        engine=engine_sentinel,
        model_name="test-model",
    )
    assert tool is not None
    assert tool._engine is engine_sentinel
    assert tool._model == "test-model"


def test_unknown_tool_returns_none(_register_tools):
    assert instantiate_tool("nonexistent_tool_xyz", app_config=_StubConfig()) is None


def test_plain_tool_instantiates_without_dependencies(_register_tools):
    tool = instantiate_tool("file_read", app_config=_StubConfig())
    assert tool is not None


def test_memory_tools_set_membership():
    assert "memory_store" in MEMORY_TOOLS
    assert "memory_search" in MEMORY_TOOLS
    assert "memory_retrieve" in MEMORY_TOOLS
    assert "memory_index" in MEMORY_TOOLS


def test_channel_tools_set_membership():
    assert "channel_send" in CHANNEL_TOOLS
    assert "channel_list" in CHANNEL_TOOLS
    assert "channel_status" in CHANNEL_TOOLS
