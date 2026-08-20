"""Tests for the knowledge_search tool."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.knowledge_search import KnowledgeSearchTool

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    """Return a KnowledgeStore pre-loaded with 3 diverse items."""
    s = KnowledgeStore(db_path=tmp_path / "test_knowledge.db")

    # Item 1 — gmail email from alice
    s.store(
        "Meeting about Kubernetes migration scheduled for next Tuesday.",
        source="gmail",
        doc_type="email",
        title="Re: K8s migration",
        author="alice@example.com",
        url="https://mail.google.com/mail/u/0/#inbox/abc123",
        timestamp="2026-01-15T10:00:00Z",
    )

    # Item 2 — slack message from bob
    s.store(
        "Discussion about K8s costs — we should consider spot instances.",
        source="slack",
        doc_type="message",
        title="#infrastructure",
        author="bob@example.com",
        url="slack://thread/def456",
        timestamp="2026-01-20T14:30:00Z",
    )

    # Item 3 — obsidian document from sarah
    s.store(
        "Research notes on large language model fine-tuning strategies.",
        source="obsidian",
        doc_type="document",
        title="LLM Fine-tuning Notes",
        author="sarah@example.com",
        url="obsidian://vault/llm-notes",
        timestamp="2026-02-01T09:00:00Z",
    )

    yield s
    s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestKnowledgeSearchTool:
    def test_basic_search(self, store):
        """Search finds the matching document from the 3-item store."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="Kubernetes migration")
        assert result.success is True
        assert "Kubernetes" in result.content
        assert result.metadata["num_results"] >= 1

    def test_filter_by_source(self, store):
        """source filter restricts results to gmail only."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="Kubernetes", source="gmail")
        assert result.success is True
        assert "gmail" in result.content
        # Every returned result must come from gmail
        assert "slack" not in result.content

    def test_filter_by_author(self, store):
        """author filter restricts results to sarah only."""
        tool = KnowledgeSearchTool(store=store)
        # Use "language model" — FTS5 does not tokenise hyphenated terms like
        # "fine-tuning" as a single token, so we search for a phrase that works.
        result = tool.execute(query="language model", author="sarah@example.com")
        assert result.success is True
        assert "sarah@example.com" in result.content
        assert result.metadata["num_results"] >= 1

    def test_no_results(self, store):
        """Query matching nothing returns success=True with 'No relevant results'."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="zzz_nonexistent_xyzzy_12345")
        assert result.success is True
        assert "No relevant results" in result.content
        assert result.metadata["num_results"] == 0

    def test_empty_query(self, store):
        """Empty query string returns success=False."""
        tool = KnowledgeSearchTool(store=store)
        result = tool.execute(query="")
        assert result.success is False
        assert "No query provided" in result.content

    def test_no_store(self):
        """Missing store returns success=False."""
        tool = KnowledgeSearchTool()
        result = tool.execute(query="kubernetes")
        assert result.success is False
        assert "No knowledge store configured" in result.content

    def test_spec_has_filter_params(self):
        """ToolSpec.parameters includes all required and optional filter fields."""
        tool = KnowledgeSearchTool()
        props = tool.spec.parameters.get("properties", {})
        for field in ("query", "source", "doc_type", "author", "since", "top_k"):
            assert field in props, f"Missing parameter: {field}"
        assert "query" in tool.spec.parameters.get("required", [])
        assert tool.spec.category == "knowledge"

    def test_registry(self):
        """ToolRegistry contains 'knowledge_search' after module import.

        The autouse ``_clean_registries`` fixture clears all registries before
        each test.  Since the module is already cached in ``sys.modules`` a
        plain import won't re-execute the ``@ToolRegistry.register`` decorator,
        so we explicitly reload the module.
        """
        mod_name = "openjarvis.tools.knowledge_search"
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)

        assert ToolRegistry.contains("knowledge_search")


def test_tool_uses_two_stage_retriever(tmp_path: Path) -> None:
    """KnowledgeSearchTool delegates to TwoStageRetriever when supplied."""
    from openjarvis.connectors.retriever import TwoStageRetriever

    store = KnowledgeStore(db_path=str(tmp_path / "ts_test.db"))
    store.store(
        content="Deep learning research paper", source="gdrive", doc_type="document"
    )
    retriever = TwoStageRetriever(store=store)
    tool = KnowledgeSearchTool(store=store, retriever=retriever)
    result = tool.execute(query="deep learning")
    assert result.success
    assert result.metadata["num_results"] > 0
