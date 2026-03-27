"""Tests for KnowledgeSQLTool."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    ks = KnowledgeStore(str(tmp_path / "test.db"))
    ks.store("Hello from Alice", source="imessage", author="Alice", doc_type="message")
    ks.store(
        "Hello from Alice again", source="imessage", author="Alice", doc_type="message"
    )
    ks.store("Meeting notes Q1", source="granola", author="Bob", doc_type="document")
    ks.store("Email about Spain trip", source="gmail", author="Carol", doc_type="email")
    return ks


def test_select_count(store: KnowledgeStore) -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT COUNT(*) as total FROM knowledge_chunks")
    assert result.success
    assert "4" in result.content


def test_group_by_author(store: KnowledgeStore) -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(
        query=(
            "SELECT author, COUNT(*) as n "
            "FROM knowledge_chunks "
            "GROUP BY author ORDER BY n DESC"
        )
    )
    assert result.success
    assert "Alice" in result.content
    assert "2" in result.content


def test_rejects_non_select(store: KnowledgeStore) -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="DELETE FROM knowledge_chunks")
    assert not result.success
    assert "read-only" in result.content.lower() or "SELECT" in result.content


def test_rejects_drop(store: KnowledgeStore) -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="DROP TABLE knowledge_chunks")
    assert not result.success


def test_handles_bad_sql(store: KnowledgeStore) -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT * FROM nonexistent_table")
    assert not result.success


def test_filter_by_source(store: KnowledgeStore) -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(
        query="SELECT title, author FROM knowledge_chunks WHERE source = 'gmail'"
    )
    assert result.success
    assert "Carol" in result.content


def test_registered() -> None:
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    ToolRegistry.register_value("knowledge_sql", KnowledgeSQLTool)
    assert ToolRegistry.contains("knowledge_sql")
