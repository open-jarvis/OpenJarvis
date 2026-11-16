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


def test_allows_select_with_keyword_substring(store: KnowledgeStore) -> None:
    """A read-only SELECT must not be rejected because a column/alias merely
    contains a write keyword as a substring (e.g. 'created' -> CREATE)."""
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT author AS created_author FROM knowledge_chunks")
    assert result.success, result.content
    assert "Alice" in result.content


def test_allows_keyword_inside_string_literal(store: KnowledgeStore) -> None:
    """A write keyword appearing only inside a string literal must not be
    treated as a forbidden statement."""
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(
        query="SELECT content FROM knowledge_chunks WHERE content LIKE '%delete%'"
    )
    assert result.success, result.content


def test_rejects_multi_statement(store: KnowledgeStore) -> None:
    """Multi-statement strings fail with a ToolResult, not an exception."""
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    tool = KnowledgeSQLTool(store=store)
    result = tool.execute(query="SELECT 1; VACUUM")
    assert not result.success
    assert "error" in result.content.lower()


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


def test_no_store_falls_back_to_default_store(tmp_path: Path, monkeypatch) -> None:
    """Built with no arguments, the tool queries the default store."""
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", tmp_path)
    with KnowledgeStore() as default:
        default.store("Note one", source="upload", doc_type="document")
        default.store("Note two", source="upload", doc_type="document")

    tool = KnowledgeSQLTool()
    result = tool.execute(query="SELECT COUNT(*) as total FROM knowledge_chunks")
    assert result.success
    assert "2" in result.content


def test_default_store_unavailable(monkeypatch) -> None:
    """If the default store cannot be opened, the tool says so."""
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("openjarvis.tools.knowledge_sql.KnowledgeStore", boom)
    tool = KnowledgeSQLTool()
    result = tool.execute(query="SELECT COUNT(*) FROM knowledge_chunks")
    assert not result.success
    assert "No knowledge store configured" in result.content
