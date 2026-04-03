"""Test that _build_deep_research_tools works correctly."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

try:
    import fastapi  # noqa: F401

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from openjarvis.connectors.store import KnowledgeStore


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
