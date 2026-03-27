"""End-to-end integration tests for the Deep Research pipeline.

Covers the full path:
  multi-source Documents
    -> IngestionPipeline
    -> KnowledgeStore
    -> TwoStageRetriever
    -> KnowledgeSearchTool
    -> DeepResearchAgent
    -> cited report
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from openjarvis.agents.deep_research import DeepResearchAgent
from openjarvis.connectors._stubs import Document
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.retriever import TwoStageRetriever
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.tools.knowledge_search import KnowledgeSearchTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_K8S_DOCS = [
    Document(
        doc_id="slack-001",
        source="slack",
        doc_type="message",
        content=(
            "Hey team, we should migrate to Kubernetes for better"
            " orchestration. The new cluster is ready."
        ),
        title="K8s migration proposal",
        author="sarah",
    ),
    Document(
        doc_id="gmail-001",
        source="gmail",
        doc_type="email",
        content=(
            "Cost analysis for the Kubernetes migration shows a 40% reduction"
            " in infrastructure spend over 12 months."
        ),
        title="Cost analysis for K8s migration",
        author="mike",
    ),
    Document(
        doc_id="gdrive-001",
        source="gdrive",
        doc_type="document",
        content=(
            "Kubernetes Migration Proposal v2: This document outlines the"
            " phased approach for moving all services to the new K8s cluster."
        ),
        title="K8s Migration Proposal v2",
        author="sarah",
    ),
    Document(
        doc_id="gcalendar-001",
        source="gcalendar",
        doc_type="event",
        content=(
            "Infrastructure Sync meeting to review the Kubernetes rollout"
            " timeline and assign owners for each microservice."
        ),
        title="Infrastructure Sync",
        author="",
    ),
    Document(
        doc_id="granola-001",
        source="granola",
        doc_type="meeting_notes",
        content=(
            "Meeting notes: Sarah presented the Kubernetes migration plan."
            " Action items: Mike to run cost analysis, team to review"
            " proposal doc by Friday."
        ),
        title="Infra meeting notes",
        author="sarah",
    ),
]


def _make_engine_response(content, tool_calls=None):
    result = {
        "content": content,
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 100,
            "total_tokens": 150,
        },
        "model": "test-model",
        "finish_reason": "stop",
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
        result["finish_reason"] = "tool_calls"
    return result


def _build_populated_store(tmp_path: Path) -> KnowledgeStore:
    """Return a KnowledgeStore populated with the 5 test documents."""
    store = KnowledgeStore(db_path=str(tmp_path / "integration_test.db"))
    pipeline = IngestionPipeline(store)
    chunks_stored = pipeline.ingest(_K8S_DOCS)
    assert chunks_stored >= 5, f"Expected >= 5 chunks, got {chunks_stored}"
    return store


# ---------------------------------------------------------------------------
# Test 1 — Full research pipeline
# ---------------------------------------------------------------------------


def test_full_research_pipeline(tmp_path):
    """Full path: IngestionPipeline -> KnowledgeStore -> TwoStageRetriever
    -> KnowledgeSearchTool -> DeepResearchAgent -> cited report.
    """
    # 1. Populate store via pipeline
    store = _build_populated_store(tmp_path)

    # 2. Two-stage retriever wrapping the store (no reranker = BM25 only)
    retriever = TwoStageRetriever(store)

    # 3. Knowledge search tool with both store and retriever
    ks_tool = KnowledgeSearchTool(store=store, retriever=retriever)

    # 4. Mock engine: first call returns tool_call, second returns final answer
    mock_engine = MagicMock()
    mock_engine.engine_id = "mock"
    mock_engine.health.return_value = True

    tool_call_response = _make_engine_response(
        "",
        tool_calls=[
            {
                "id": "call_k8s_1",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": json.dumps({"query": "Kubernetes migration"}),
                },
            }
        ],
    )
    final_response = _make_engine_response(
        "Based on my research across Slack, email, and documents, the"
        " Kubernetes migration was proposed by Sarah and supported by a cost"
        " analysis from Mike. [slack] K8s migration proposal -- sarah\n"
        "[gmail] Cost analysis for K8s migration -- mike\n"
        "[gdrive] K8s Migration Proposal v2 -- sarah\n"
        "\n## Sources\n"
        "- [slack] K8s migration proposal -- sarah\n"
        "- [gmail] Cost analysis for K8s migration -- mike\n"
        "- [gdrive] K8s Migration Proposal v2 -- sarah"
    )
    mock_engine.generate.side_effect = [tool_call_response, final_response]

    # 5. Create agent with tool
    agent = DeepResearchAgent(mock_engine, "test-model", tools=[ks_tool])

    # 6. Run the agent
    result = agent.run("What is the status of the Kubernetes migration?")

    # 7. Assertions
    assert result.content, "Result should have non-empty content"
    assert "Kubernetes" in result.content, "Result should mention Kubernetes"
    assert result.turns >= 1, f"Expected at least 1 turn, got {result.turns}"

    # At least one successful knowledge_search tool result
    ks_results = [
        tr
        for tr in result.tool_results
        if tr.tool_name == "knowledge_search" and tr.success
    ]
    assert len(ks_results) >= 1, (
        f"Expected at least 1 successful knowledge_search call, "
        f"got {len(ks_results)}: {result.tool_results}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Cross-platform search finds data from multiple sources
# ---------------------------------------------------------------------------


def test_search_finds_cross_platform_data(tmp_path):
    """KnowledgeSearchTool via TwoStageRetriever returns results from
    at least 2 different sources when searching for 'Kubernetes migration'.
    """
    # 1. Populate the same store
    store = _build_populated_store(tmp_path)

    # 2. Build search tool with retriever
    retriever = TwoStageRetriever(store)
    ks_tool = KnowledgeSearchTool(store=store, retriever=retriever)

    # 3. Execute the search directly (no agent)
    tool_result = ks_tool.execute(query="Kubernetes migration", top_k=10)

    assert tool_result.success, f"Search failed: {tool_result.content}"
    assert tool_result.content, "Search returned empty content"

    # 4. Identify which sources appear in the formatted output
    content = tool_result.content
    sources_found = {
        label
        for label in ("slack", "gmail", "gdrive", "granola", "gcalendar")
        if f"[{label}]" in content
    }

    assert len(sources_found) >= 2, (
        f"Expected results from at least 2 different sources, "
        f"but only found: {sources_found}\n\nFull output:\n{content}"
    )
