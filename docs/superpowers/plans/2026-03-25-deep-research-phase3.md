# Deep Research Phase 3: Two-Stage Retrieval + Deep Research Agent

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ColBERTv2 reranking on top of BM25 retrieval and build the DeepResearchAgent — a multi-hop tool-using agent that searches your personal knowledge base across sources, synthesizes findings, and produces cited research reports.

**Architecture:** A new `TwoStageRetriever` composes BM25 recall (KnowledgeStore FTS5) with ColBERTv2 semantic reranking. The `knowledge_search` tool is upgraded to use it. A `DeepResearchAgent` extends `ToolUsingAgent` with a research-oriented system prompt, multi-hop loop, and structured report output with cross-platform citations. ColBERT persistence to disk is added via memory-mapped tensors for large knowledge bases.

**Tech Stack:** Python 3.10+, sqlite3 (BM25/FTS5), torch + colbert-ai (reranking, optional), pytest

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Sections 7, 8, Phase 3

**Depends on:** Phase 1 complete (KnowledgeStore, knowledge_search tool, IngestionPipeline, SemanticChunker)

---

## File Structure

```
src/openjarvis/connectors/
├── retriever.py             # TwoStageRetriever: BM25 recall → ColBERT rerank
├── store.py                 # (modify) Add store_embedding/load_embedding methods
├── pipeline.py              # (modify) Dual-write to ColBERT index during ingest

src/openjarvis/agents/
├── deep_research.py         # DeepResearchAgent with multi-hop loop + citations

src/openjarvis/tools/
├── knowledge_search.py      # (modify) Upgrade to use TwoStageRetriever

tests/connectors/
├── test_retriever.py        # TwoStageRetriever tests

tests/agents/
├── test_deep_research.py    # DeepResearchAgent tests
```

---

### Task 1: TwoStageRetriever (BM25 Recall → ColBERT Rerank)

**Files:**
- Create: `src/openjarvis/connectors/retriever.py`
- Create: `tests/connectors/test_retriever.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_retriever.py`:

```python
"""Tests for TwoStageRetriever — BM25 recall + ColBERT rerank."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.connectors.retriever import TwoStageRetriever
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.tools.storage._stubs import RetrievalResult


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    s = KnowledgeStore(db_path=str(tmp_path / "retriever_test.db"))
    s.store(
        content="Kubernetes migration proposal with cost analysis",
        source="gdrive",
        doc_type="document",
        author="sarah",
        title="K8s Proposal",
    )
    s.store(
        content="Discussion about Kubernetes deployment timeline",
        source="slack",
        doc_type="message",
        author="mike",
        title="#infrastructure",
    )
    s.store(
        content="Quarterly budget review for cloud services",
        source="gmail",
        doc_type="email",
        author="alice",
        title="Re: Budget Q3",
    )
    s.store(
        content="Meeting notes about project planning",
        source="granola",
        doc_type="document",
        author="bob",
        title="Sprint Planning",
    )
    return s


@pytest.fixture
def retriever(store: KnowledgeStore) -> TwoStageRetriever:
    return TwoStageRetriever(store=store)


def test_retrieve_returns_results(retriever: TwoStageRetriever) -> None:
    results = retriever.retrieve("Kubernetes migration")
    assert len(results) > 0
    assert all(isinstance(r, RetrievalResult) for r in results)


def test_retrieve_respects_top_k(retriever: TwoStageRetriever) -> None:
    results = retriever.retrieve("cloud", top_k=2)
    assert len(results) <= 2


def test_retrieve_with_source_filter(
    retriever: TwoStageRetriever,
) -> None:
    results = retriever.retrieve("Kubernetes", source="gdrive")
    assert len(results) >= 1
    assert all(
        r.metadata.get("source") == "gdrive" for r in results
    )


def test_retrieve_with_author_filter(
    retriever: TwoStageRetriever,
) -> None:
    results = retriever.retrieve("budget", author="alice")
    assert len(results) >= 1
    assert all(
        r.metadata.get("author") == "alice" for r in results
    )


def test_retrieve_bm25_only_when_no_colbert(
    retriever: TwoStageRetriever,
) -> None:
    """Without ColBERT, falls back to BM25-only results."""
    results = retriever.retrieve("planning")
    assert len(results) > 0
    # Results should still have scores
    assert all(r.score >= 0 for r in results)


def test_retrieve_with_colbert_reranking(
    store: KnowledgeStore,
) -> None:
    """With a mock ColBERT reranker, results are reranked."""
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = [
        RetrievalResult(
            content="Kubernetes migration proposal with cost analysis",
            score=0.95,
            source="gdrive",
            metadata={"source": "gdrive", "author": "sarah"},
        ),
    ]

    retriever = TwoStageRetriever(
        store=store, reranker=mock_reranker
    )
    results = retriever.retrieve("Kubernetes", top_k=5)
    assert len(results) >= 1
    mock_reranker.rerank.assert_called_once()


def test_retrieve_no_results(retriever: TwoStageRetriever) -> None:
    results = retriever.retrieve("xyznonexistent999")
    assert len(results) == 0


def test_retrieve_recall_k_larger_than_top_k(
    retriever: TwoStageRetriever,
) -> None:
    """BM25 recall fetches more candidates than final top_k."""
    results = retriever.retrieve("Kubernetes", top_k=1)
    assert len(results) <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_retriever.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement TwoStageRetriever**

Create `src/openjarvis/connectors/retriever.py`:

```python
"""Two-stage retriever: BM25 recall from KnowledgeStore → optional ColBERT rerank.

Stage 1 (BM25): Fast keyword recall via SQLite FTS5. Returns top-N candidates.
Stage 2 (ColBERT): Semantic reranking of candidates via token-level MaxSim scoring.
         Falls back to BM25-only if ColBERT is not available.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.tools.storage._stubs import RetrievalResult

logger = logging.getLogger(__name__)


class Reranker(ABC):
    """Abstract base for reranking BM25 candidates."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        *,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """Rerank candidates and return top-k by semantic relevance."""


class ColBERTReranker(Reranker):
    """Reranker using ColBERTv2 late-interaction MaxSim scoring.

    Lazily loads the ColBERT checkpoint on first use.
    """

    def __init__(
        self,
        *,
        checkpoint: str = "colbert-ir/colbertv2.0",
        device: str = "cpu",
    ) -> None:
        self._checkpoint_name = checkpoint
        self._device = device
        self._loaded = False
        self._checkpoint = None

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            from colbert.modeling.checkpoint import Checkpoint

            self._checkpoint = Checkpoint(
                self._checkpoint_name, colbert_config=None
            )
            self._loaded = True
            logger.info("ColBERT checkpoint loaded: %s", self._checkpoint_name)
        except ImportError:
            logger.warning("colbert-ai not installed, reranking disabled")
            self._loaded = True  # Don't retry
        except Exception as exc:
            logger.warning("ColBERT load failed: %s", exc)
            self._loaded = True

    def _encode(self, text: str) -> Any:
        if self._checkpoint is None:
            return None
        return self._checkpoint.queryFromText([text])[0]

    @staticmethod
    def _maxsim(query_embs: Any, doc_embs: Any) -> float:
        import torch

        # query_embs: (Q, D), doc_embs: (T, D)
        sim = torch.nn.functional.cosine_similarity(
            query_embs.unsqueeze(1), doc_embs.unsqueeze(0), dim=2
        )
        return sim.max(dim=1).values.sum().item()

    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        *,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        self._load()
        if self._checkpoint is None:
            return candidates[:top_k]

        query_embs = self._encode(query)
        if query_embs is None:
            return candidates[:top_k]

        scored = []
        for r in candidates:
            doc_embs = self._encode(r.content)
            if doc_embs is None:
                scored.append((r, r.score))
            else:
                score = self._maxsim(query_embs, doc_embs)
                scored.append((r, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for r, score in scored[:top_k]:
            results.append(
                RetrievalResult(
                    content=r.content,
                    score=score,
                    source=r.source,
                    metadata=r.metadata,
                )
            )
        return results


class TwoStageRetriever:
    """Composes BM25 recall with optional semantic reranking.

    Parameters
    ----------
    store:
        KnowledgeStore for BM25 recall via FTS5.
    reranker:
        Optional Reranker (e.g., ColBERTReranker). If None, BM25-only.
    recall_k:
        Number of BM25 candidates to fetch for reranking (default: 100).
    """

    def __init__(
        self,
        store: KnowledgeStore,
        reranker: Optional[Reranker] = None,
        *,
        recall_k: int = 100,
    ) -> None:
        self._store = store
        self._reranker = reranker
        self._recall_k = recall_k

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        source: str = "",
        doc_type: str = "",
        author: str = "",
        since: str = "",
        until: str = "",
    ) -> List[RetrievalResult]:
        """Two-stage retrieval: BM25 recall → optional rerank.

        Falls back to BM25-only if no reranker is configured.
        """
        # Stage 1: BM25 recall
        recall_n = max(self._recall_k, top_k * 3)
        candidates = self._store.retrieve(
            query,
            top_k=recall_n,
            source=source,
            doc_type=doc_type,
            author=author,
            since=since,
            until=until,
        )

        if not candidates:
            return []

        # Stage 2: Rerank (or just truncate)
        if self._reranker is not None and len(candidates) > top_k:
            return self._reranker.rerank(
                query, candidates, top_k=top_k
            )

        return candidates[:top_k]
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_retriever.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/retriever.py tests/connectors/test_retriever.py
git commit -m "feat: add TwoStageRetriever with BM25 recall and pluggable ColBERT reranking"
```

---

### Task 2: Upgrade knowledge_search to Use TwoStageRetriever

**Files:**
- Modify: `src/openjarvis/tools/knowledge_search.py`
- Modify: `tests/tools/test_knowledge_search.py`

- [ ] **Step 1: Write new test for two-stage retrieval**

Add to `tests/tools/test_knowledge_search.py`:

```python
def test_tool_uses_two_stage_retriever(tmp_path: Path) -> None:
    """When initialized with a TwoStageRetriever, uses it."""
    from openjarvis.connectors.retriever import TwoStageRetriever

    store = KnowledgeStore(db_path=str(tmp_path / "ts_test.db"))
    store.store(
        content="Deep learning research paper",
        source="gdrive",
        doc_type="document",
    )
    retriever = TwoStageRetriever(store=store)
    tool = KnowledgeSearchTool(store=store, retriever=retriever)
    result = tool.execute(query="deep learning")
    assert result.success
    assert result.metadata["num_results"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/tools/test_knowledge_search.py::test_tool_uses_two_stage_retriever -v`

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'retriever'`

- [ ] **Step 3: Update KnowledgeSearchTool**

Modify `src/openjarvis/tools/knowledge_search.py` — add optional `retriever` parameter:

In `__init__`, add `retriever` parameter:

```python
def __init__(
    self,
    store: Optional[KnowledgeStore] = None,
    retriever: Optional[Any] = None,
) -> None:
    self._store = store
    self._retriever = retriever
```

In `execute`, use retriever if available, else fall back to store:

```python
# In execute(), replace the store.retrieve() call with:
if self._retriever is not None:
    results = self._retriever.retrieve(
        query,
        top_k=top_k,
        source=params.get("source", ""),
        doc_type=params.get("doc_type", ""),
        author=params.get("author", ""),
        since=params.get("since", ""),
        until=params.get("until", ""),
    )
elif self._store is not None:
    results = self._store.retrieve(
        query,
        top_k=top_k,
        source=params.get("source", ""),
        doc_type=params.get("doc_type", ""),
        author=params.get("author", ""),
        since=params.get("since", ""),
        until=params.get("until", ""),
    )
else:
    return ToolResult(
        tool_name="knowledge_search",
        content="No knowledge store configured.",
        success=False,
    )
```

Also update the no-store check at the top of `execute()` to allow retriever-only mode:

```python
if self._store is None and self._retriever is None:
    return ToolResult(
        tool_name="knowledge_search",
        content="No knowledge store configured. Run 'jarvis connect' to set up data sources.",
        success=False,
    )
```

- [ ] **Step 4: Run all knowledge_search tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/tools/test_knowledge_search.py -v`

Expected: All tests PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/tools/knowledge_search.py tests/tools/test_knowledge_search.py
git commit -m "feat: upgrade knowledge_search to support TwoStageRetriever"
```

---

### Task 3: DeepResearchAgent

**Files:**
- Create: `src/openjarvis/agents/deep_research.py`
- Create: `tests/agents/test_deep_research.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_deep_research.py`:

```python
"""Tests for DeepResearchAgent — multi-hop research with citations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.deep_research import DeepResearchAgent
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    s = KnowledgeStore(db_path=str(tmp_path / "dr_test.db"))
    s.store(
        content="Kubernetes migration was proposed by Sarah in March",
        source="slack",
        doc_type="message",
        author="sarah",
        title="#infrastructure",
        url="https://slack.com/archives/C001/p123",
    )
    s.store(
        content="Cost analysis shows 40% increase during transition",
        source="gdrive",
        doc_type="document",
        author="sarah",
        title="K8s Cost Analysis",
        url="https://drive.google.com/d/doc1",
    )
    s.store(
        content="Migration approved by engineering leads on March 8",
        source="gmail",
        doc_type="email",
        author="mike",
        title="Re: K8s migration approved",
        url="https://mail.google.com/mail/u/0/#inbox/msg1",
    )
    return s


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    return engine


def _make_engine_response(
    content: str, tool_calls: list | None = None
) -> dict:
    result: Dict[str, Any] = {
        "content": content,
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 50,
            "total_tokens": 100,
        },
        "model": "test-model",
        "finish_reason": "stop",
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
        result["finish_reason"] = "tool_calls"
    return result


def test_agent_registration() -> None:
    import openjarvis.agents.deep_research  # noqa: F401

    AgentRegistry.register_value(
        "deep_research", DeepResearchAgent
    )
    assert AgentRegistry.contains("deep_research")


def test_agent_produces_result(
    mock_engine: MagicMock, store: KnowledgeStore
) -> None:
    """Agent returns an AgentResult with content."""
    mock_engine.generate.return_value = _make_engine_response(
        "Based on my research, the Kubernetes migration was "
        "proposed by Sarah.\n\n**Sources:**\n"
        "1. [slack] #infrastructure"
    )

    ks_tool = KnowledgeSearchTool(store=store)
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test-model",
        tools=[ks_tool],
        max_turns=5,
    )

    result = agent.run("What was the K8s migration context?")
    assert result.content
    assert result.turns >= 1


def test_agent_uses_knowledge_search(
    mock_engine: MagicMock, store: KnowledgeStore
) -> None:
    """Agent calls knowledge_search tool during research."""
    # First call: agent wants to search
    call1 = _make_engine_response(
        "",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": json.dumps(
                        {"query": "Kubernetes migration"}
                    ),
                },
            }
        ],
    )
    # Second call: agent synthesizes
    call2 = _make_engine_response(
        "The Kubernetes migration was proposed by Sarah in March.\n\n"
        "**Sources:**\n"
        "1. [slack] #infrastructure — sarah\n"
        "2. [gdrive] K8s Cost Analysis — sarah"
    )
    mock_engine.generate.side_effect = [call1, call2]

    ks_tool = KnowledgeSearchTool(store=store)
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test-model",
        tools=[ks_tool],
        max_turns=5,
    )

    result = agent.run("What was the K8s migration context?")
    assert result.content
    assert result.turns >= 1
    assert len(result.tool_results) >= 1
    assert result.tool_results[0].tool_name == "knowledge_search"
    assert result.tool_results[0].success


def test_agent_respects_max_turns(
    mock_engine: MagicMock, store: KnowledgeStore
) -> None:
    """Agent stops after max_turns even if not done."""
    # Always return a tool call (infinite loop without max_turns)
    mock_engine.generate.return_value = _make_engine_response(
        "",
        tool_calls=[
            {
                "id": "call_n",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": json.dumps(
                        {"query": "anything"}
                    ),
                },
            }
        ],
    )

    ks_tool = KnowledgeSearchTool(store=store)
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test-model",
        tools=[ks_tool],
        max_turns=3,
    )

    result = agent.run("Research something")
    assert result.turns <= 3


def test_agent_system_prompt_mentions_research(
    mock_engine: MagicMock, store: KnowledgeStore
) -> None:
    """System prompt should mention research and citations."""
    mock_engine.generate.return_value = _make_engine_response(
        "Final answer here."
    )

    ks_tool = KnowledgeSearchTool(store=store)
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test-model",
        tools=[ks_tool],
    )

    agent.run("test")

    # Check the system message passed to generate
    call_args = mock_engine.generate.call_args
    messages = call_args[0][0]  # first positional arg
    system_msg = messages[0]
    assert "research" in system_msg.content.lower()
    assert "source" in system_msg.content.lower()


def test_agent_defaults(
    mock_engine: MagicMock, store: KnowledgeStore
) -> None:
    """Check default max_turns and agent_id."""
    ks_tool = KnowledgeSearchTool(store=store)
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test-model",
        tools=[ks_tool],
    )
    assert agent.agent_id == "deep_research"
    assert agent._max_turns == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_deep_research.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement DeepResearchAgent**

Create `src/openjarvis/agents/deep_research.py`:

```python
"""DeepResearchAgent — multi-hop research over personal knowledge base.

Extends ToolUsingAgent with:
- Research-oriented system prompt emphasizing citations and sources
- Multi-hop retrieval loop (up to max_turns subqueries)
- Structured report output with cross-platform source attribution
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    ToolUsingAgent,
)
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, build_tool_descriptions

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Deep Research agent with access to a personal knowledge base \
containing emails, messages, documents, calendar events, contacts, and \
notes from multiple sources (Gmail, Slack, Google Drive, Notion, \
Granola, Obsidian, and more).

Your job is to answer the user's question by searching across these \
sources, synthesizing information, and producing a comprehensive \
research report with citations.

## How to Research

1. Use the `knowledge_search` tool to find relevant information. \
You can filter by source, doc_type, author, and date range.
2. Use the `think` tool to reason about what you've found and plan \
your next search.
3. Make multiple searches to cross-reference across sources. \
A question about a decision might involve Slack threads, email chains, \
documents, and calendar events.
4. When you have enough information, synthesize a clear answer.

## Output Format

Structure your response as:

1. A narrative answer addressing the user's question
2. Inline citations in the format [source] title — author
3. A "Sources" section at the end listing all referenced items with \
their platform, title, author, and URL

## Important

- Always cite your sources — never present information without \
attribution
- Cross-reference across platforms when possible
- If you can't find enough information, say so clearly
- Prefer recent information over older content when relevant

{tool_descriptions}"""


@AgentRegistry.register("deep_research")
class DeepResearchAgent(ToolUsingAgent):
    """Multi-hop research agent for personal knowledge base queries.

    Searches across indexed personal data (emails, messages, documents,
    calendar events, contacts, notes) using the knowledge_search tool,
    performs multi-hop retrieval to cross-reference sources, and
    synthesizes findings into a cited research report.

    Parameters
    ----------
    engine:
        Inference engine for LLM calls.
    model:
        Model name/ID.
    tools:
        List of tools (should include KnowledgeSearchTool at minimum).
    max_turns:
        Maximum research hops (default: 5).
    """

    agent_id = "deep_research"
    _default_max_turns = 5
    _default_temperature = 0.3
    _default_max_tokens = 4096

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        interactive: bool = False,
        confirm_callback: Any = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns or self._default_max_turns,
            temperature=temperature or self._default_temperature,
            max_tokens=max_tokens or self._default_max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute a multi-hop research query.

        The agent loops through: search → think → search → ... → synthesize,
        up to max_turns iterations.
        """
        self._emit_turn_start(input)

        # Build system prompt with tool descriptions
        tool_desc = build_tool_descriptions(self._tools)
        system_prompt = _SYSTEM_PROMPT.format(
            tool_descriptions=tool_desc
        )

        # Assemble initial messages
        messages = self._build_messages(
            input, context, system_prompt=system_prompt
        )

        all_tool_results: List[ToolResult] = []
        turns = 0
        total_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for _turn in range(self._max_turns):
            turns += 1

            # Generate response
            result = self._generate(messages)
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)

            content = result.get("content", "")
            tool_calls_raw = result.get("tool_calls", [])

            # No tool calls → final answer
            if not tool_calls_raw:
                final_content = self._strip_think_tags(content)
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=final_content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        **total_usage,
                        "sources": self._extract_sources(
                            all_tool_results
                        ),
                    },
                )

            # Append assistant message
            messages.append(
                Message(role=Role.ASSISTANT, content=content)
            )

            # Execute tool calls
            for tc_raw in tool_calls_raw:
                fn = tc_raw.get("function", {})
                tool_call = ToolCall(
                    id=tc_raw.get("id", f"dr_{turns}"),
                    name=fn.get("name", ""),
                    arguments=fn.get("arguments", "{}"),
                )

                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                # Add tool result as message
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result.content,
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                    )
                )

        # Max turns exceeded — return what we have
        self._emit_turn_end(turns=turns)
        return self._max_turns_result(
            all_tool_results,
            turns,
            metadata={
                **total_usage,
                "sources": self._extract_sources(all_tool_results),
            },
        )

    @staticmethod
    def _extract_sources(
        tool_results: List[ToolResult],
    ) -> List[str]:
        """Extract source references from tool results for metadata."""
        sources: List[str] = []
        for tr in tool_results:
            if tr.tool_name == "knowledge_search" and tr.success:
                n = tr.metadata.get("num_results", 0)
                if n > 0:
                    sources.append(
                        f"knowledge_search: {n} results"
                    )
        return sources
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_deep_research.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/agents/deep_research.py tests/agents/test_deep_research.py
git commit -m "feat: add DeepResearchAgent with multi-hop retrieval and cited reports"
```

---

### Task 4: End-to-End Integration Test

**Files:**
- Create: `tests/agents/test_deep_research_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/agents/test_deep_research_integration.py`:

```python
"""Integration test — full pipeline from connector to Deep Research agent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.deep_research import DeepResearchAgent
from openjarvis.connectors._stubs import Document
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.retriever import TwoStageRetriever
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


@pytest.fixture
def populated_store(tmp_path: Path) -> KnowledgeStore:
    """KnowledgeStore with realistic multi-source data."""
    store = KnowledgeStore(
        db_path=str(tmp_path / "integration.db")
    )
    pipeline = IngestionPipeline(store=store, max_tokens=256)

    docs = [
        Document(
            doc_id="slack:c001:t1",
            source="slack",
            doc_type="message",
            content=(
                "Sarah: We should migrate to Kubernetes. "
                "The current Docker Swarm setup can't handle our scale."
            ),
            title="#infrastructure",
            author="sarah",
        ),
        Document(
            doc_id="gmail:msg1",
            source="gmail",
            doc_type="email",
            content=(
                "Hi team, I've completed the cost analysis for "
                "the K8s migration. Estimated 40% increase in "
                "cloud spend during the transition period, but "
                "20% reduction long-term."
            ),
            title="K8s Cost Analysis",
            author="mike",
        ),
        Document(
            doc_id="gdrive:doc1",
            source="gdrive",
            doc_type="document",
            content=(
                "# Kubernetes Migration Proposal\n\n"
                "## Timeline\n"
                "Six-week migration window starting April 1st.\n\n"
                "## Team\n"
                "Sarah (lead), Mike (infra), Bob (testing)\n\n"
                "## Risks\n"
                "Downtime during cutover, learning curve for team."
            ),
            title="K8s Migration Proposal v2",
            author="sarah",
        ),
        Document(
            doc_id="gcalendar:evt1",
            source="gcalendar",
            doc_type="event",
            content=(
                "Infrastructure Sync\n"
                "When: March 5, 2024 10:00 AM\n"
                "Attendees: Sarah, Mike, Bob\n"
                "Agenda: Review K8s migration proposal"
            ),
            title="Infrastructure Sync",
            author="sarah",
        ),
        Document(
            doc_id="granola:not1",
            source="granola",
            doc_type="document",
            content=(
                "## Summary\n"
                "Discussed K8s migration timeline. Sarah presented "
                "the proposal. Mike raised cost concerns. "
                "Decision: proceed with 6-week plan.\n\n"
                "## Transcript\n"
                "**sarah:** Let me walk through the timeline.\n"
                "**mike:** What about the cost increase?\n"
                "**sarah:** Short-term 40% increase, long-term savings."
            ),
            title="Infrastructure Sync Notes",
            author="sarah",
        ),
    ]

    pipeline.ingest(docs)
    return store


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    return engine


def test_full_research_pipeline(
    populated_store: KnowledgeStore,
    mock_engine: MagicMock,
) -> None:
    """Full pipeline: multi-source data → search → agent → cited report."""
    # Agent searches, then synthesizes
    search_call = {
        "content": "",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        "model": "test",
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": json.dumps(
                        {"query": "Kubernetes migration"}
                    ),
                },
            }
        ],
    }

    final_answer = {
        "content": (
            "## Kubernetes Migration — Decision Context\n\n"
            "The migration to Kubernetes was proposed by Sarah "
            "in the #infrastructure Slack channel "
            "[slack] #infrastructure — sarah.\n\n"
            "Mike completed a cost analysis showing a 40% "
            "short-term increase [gmail] K8s Cost Analysis — mike.\n\n"
            "The proposal document outlines a six-week timeline "
            "[gdrive] K8s Migration Proposal v2 — sarah.\n\n"
            "The team discussed and approved the plan during "
            "the March 5th Infrastructure Sync "
            "[granola] Infrastructure Sync Notes — sarah.\n\n"
            "**Sources:**\n"
            "1. [slack] #infrastructure — sarah\n"
            "2. [gmail] K8s Cost Analysis — mike\n"
            "3. [gdrive] K8s Migration Proposal v2 — sarah\n"
            "4. [gcalendar] Infrastructure Sync — sarah\n"
            "5. [granola] Infrastructure Sync Notes — sarah"
        ),
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
        },
        "model": "test",
        "finish_reason": "stop",
    }

    mock_engine.generate.side_effect = [search_call, final_answer]

    retriever = TwoStageRetriever(store=populated_store)
    ks_tool = KnowledgeSearchTool(
        store=populated_store, retriever=retriever
    )

    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test-model",
        tools=[ks_tool],
        max_turns=5,
    )

    result = agent.run(
        "What was the context around the Kubernetes migration decision?"
    )

    # Verify agent produced a result
    assert result.content
    assert "Kubernetes" in result.content
    assert result.turns >= 1

    # Verify tool was called
    assert len(result.tool_results) >= 1
    assert result.tool_results[0].tool_name == "knowledge_search"
    assert result.tool_results[0].success

    # Verify knowledge_search found cross-platform results
    search_result = result.tool_results[0]
    assert search_result.metadata.get("num_results", 0) > 0


def test_search_finds_cross_platform_data(
    populated_store: KnowledgeStore,
) -> None:
    """Verify the store has data from multiple sources."""
    retriever = TwoStageRetriever(store=populated_store)
    tool = KnowledgeSearchTool(
        store=populated_store, retriever=retriever
    )

    result = tool.execute(query="Kubernetes migration")
    assert result.success
    assert result.metadata["num_results"] > 0

    # Should find results from multiple sources
    content = result.content
    sources_found = set()
    for src in ["slack", "gmail", "gdrive", "granola"]:
        if f"[{src}]" in content:
            sources_found.add(src)
    assert len(sources_found) >= 2, (
        f"Expected cross-platform results, found: {sources_found}"
    )
```

- [ ] **Step 2: Run integration test**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_deep_research_integration.py -v`

Expected: All 2 tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/ tests/agents/test_deep_research.py tests/agents/test_deep_research_integration.py tests/tools/test_knowledge_search.py -v`

Expected: All tests PASS.

- [ ] **Step 4: Run linter**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run ruff check src/openjarvis/connectors/retriever.py src/openjarvis/agents/deep_research.py src/openjarvis/tools/knowledge_search.py tests/connectors/test_retriever.py tests/agents/`

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add tests/agents/test_deep_research_integration.py
git commit -m "feat: add end-to-end integration test for Deep Research pipeline"
```

---

## Post-Plan Notes

**What this plan produces:**
- `TwoStageRetriever` — composable BM25 recall + pluggable ColBERT reranking
- `ColBERTReranker` — lazy-loading reranker with MaxSim scoring (optional dependency)
- `KnowledgeSearchTool` upgraded to use two-stage retrieval
- `DeepResearchAgent` — multi-hop research agent with cross-platform citations
- Full integration test proving the pipeline end-to-end

**ColBERT is optional:** The system works with BM25-only when ColBERT dependencies (torch, colbert-ai) aren't installed. ColBERT adds semantic reranking quality when available.

**What comes next:**
- **Phase 4:** ChannelAgent + iMessage/WhatsApp/Slack plugins for chatting with the agent
- **Phase 5:** Incremental sync, attachment store, polish
- **Phase 2B:** Desktop wizard UI
