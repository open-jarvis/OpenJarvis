# Deep Research Agent v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `knowledge_sql` and `scan_chunks` tools to the DeepResearchAgent, rewrite the system prompt with query strategies, wire in the `think` tool, and validate with 4 test queries.

**Architecture:** Two new tool files following the existing `BaseTool`/`ToolSpec`/`ToolResult` pattern. The `knowledge_sql` tool runs read-only SQL against `KnowledgeStore._conn`. The `scan_chunks` tool pulls chunks from the store, batches them, and calls the LM to extract findings. The system prompt teaches the model when to use each tool. Everything wired together in `_launch_chat`.

**Tech Stack:** Python 3.10+, sqlite3, pytest

---

### Task 1: Create `knowledge_sql` tool

**Files:**
- Create: `src/openjarvis/tools/knowledge_sql.py`
- Create: `tests/tools/test_knowledge_sql.py`

- [ ] **Step 1: Write the test file**

Create `tests/tools/__init__.py` if it doesn't exist, then create `tests/tools/test_knowledge_sql.py`:

```python
"""Tests for KnowledgeSQLTool."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    ks = KnowledgeStore(str(tmp_path / "test.db"))
    ks.store("Hello from Alice", source="imessage", author="Alice", doc_type="message")
    ks.store("Hello from Alice again", source="imessage", author="Alice", doc_type="message")
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
        query="SELECT author, COUNT(*) as n FROM knowledge_chunks GROUP BY author ORDER BY n DESC"
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/tools/test_knowledge_sql.py -v --tb=short
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the tool**

Create `src/openjarvis/tools/knowledge_sql.py`:

```python
"""KnowledgeSQLTool — read-only SQL queries against the KnowledgeStore.

Allows agents to run SELECT queries for aggregation, counting, ranking,
and filtering operations that BM25 search cannot handle.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_ROWS = 50

_SCHEMA_DESCRIPTION = (
    "Table: knowledge_chunks\n"
    "Columns: id, content, source, doc_type, doc_id, title, author, "
    "participants, timestamp, thread_id, url, metadata, chunk_index"
)


@ToolRegistry.register("knowledge_sql")
class KnowledgeSQLTool(BaseTool):
    """Run read-only SQL against the knowledge store for aggregation queries."""

    tool_id = "knowledge_sql"

    def __init__(self, store: Optional[KnowledgeStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_sql",
            description=(
                "Run a read-only SQL SELECT query against the knowledge_chunks table. "
                "Use for counting, ranking, aggregation, and filtering. "
                f"{_SCHEMA_DESCRIPTION}"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "SQL SELECT query. Only SELECT statements allowed. "
                            "Example: SELECT author, COUNT(*) as n FROM knowledge_chunks "
                            "WHERE source='imessage' GROUP BY author ORDER BY n DESC LIMIT 10"
                        ),
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._store is None:
            return ToolResult(
                tool_name="knowledge_sql",
                content="No knowledge store configured.",
                success=False,
            )

        query: str = params.get("query", "").strip()
        if not query:
            return ToolResult(
                tool_name="knowledge_sql",
                content="No query provided.",
                success=False,
            )

        # Read-only enforcement
        normalized = query.lstrip().upper()
        if not normalized.startswith("SELECT"):
            return ToolResult(
                tool_name="knowledge_sql",
                content="Only SELECT queries are allowed (read-only).",
                success=False,
            )

        # Block dangerous keywords even in SELECT subqueries
        for forbidden in ("DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH"):
            if forbidden in normalized:
                return ToolResult(
                    tool_name="knowledge_sql",
                    content=f"Query contains forbidden keyword: {forbidden}. Only SELECT queries allowed.",
                    success=False,
                )

        try:
            rows = self._store._conn.execute(query).fetchmany(_MAX_ROWS)
        except sqlite3.OperationalError as exc:
            return ToolResult(
                tool_name="knowledge_sql",
                content=f"SQL error: {exc}",
                success=False,
            )

        if not rows:
            return ToolResult(
                tool_name="knowledge_sql",
                content="Query returned no results.",
                success=True,
                metadata={"num_rows": 0},
            )

        # Format as table
        columns = rows[0].keys()
        lines = [" | ".join(columns)]
        lines.append(" | ".join("---" for _ in columns))
        for row in rows:
            lines.append(" | ".join(str(row[c]) for c in columns))

        return ToolResult(
            tool_name="knowledge_sql",
            content="\n".join(lines),
            success=True,
            metadata={"num_rows": len(rows)},
        )


__all__ = ["KnowledgeSQLTool"]
```

- [ ] **Step 4: Ensure tests/tools/__init__.py exists**

```bash
touch tests/tools/__init__.py
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/tools/test_knowledge_sql.py -v --tb=short
```

Expected: 7/7 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/tools/knowledge_sql.py tests/tools/__init__.py tests/tools/test_knowledge_sql.py
git commit -m "feat: add knowledge_sql tool for read-only SQL aggregation queries"
```

---

### Task 2: Create `scan_chunks` tool

**Files:**
- Create: `src/openjarvis/tools/scan_chunks.py`
- Create: `tests/tools/test_scan_chunks.py`

- [ ] **Step 1: Write the test file**

Create `tests/tools/test_scan_chunks.py`:

```python
"""Tests for ScanChunksTool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    ks = KnowledgeStore(str(tmp_path / "test.db"))
    ks.store("Met with Sequoia about Series A", source="granola", doc_type="document")
    ks.store("Fundraising discussion with a]16z", source="granola", doc_type="document")
    ks.store("Weekly standup notes", source="granola", doc_type="document")
    ks.store("Trip to Spain with family", source="imessage", doc_type="message")
    return ks


def _fake_engine() -> MagicMock:
    """Mock engine that echoes back a summary."""
    engine = MagicMock()
    engine.generate.return_value = {
        "content": "Found: Sequoia Series A discussion, a16z fundraising",
        "usage": {},
    }
    return engine


def test_scan_finds_semantic_matches(store: KnowledgeStore) -> None:
    from openjarvis.tools.scan_chunks import ScanChunksTool
    engine = _fake_engine()
    tool = ScanChunksTool(store=store, engine=engine, model="test")
    result = tool.execute(question="Which VCs have I spoken with?")
    assert result.success
    assert "Sequoia" in result.content or "Found" in result.content
    # Engine should have been called with chunks
    assert engine.generate.called


def test_scan_respects_source_filter(store: KnowledgeStore) -> None:
    from openjarvis.tools.scan_chunks import ScanChunksTool
    engine = _fake_engine()
    tool = ScanChunksTool(store=store, engine=engine, model="test")
    result = tool.execute(question="What trips?", source="imessage")
    assert result.success
    # Should only have passed imessage chunks to the engine
    call_args = engine.generate.call_args
    messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
    # At least one call should contain "Spain"
    all_content = str(messages)
    assert "Spain" in all_content


def test_scan_empty_store(tmp_path: Path) -> None:
    from openjarvis.tools.scan_chunks import ScanChunksTool
    ks = KnowledgeStore(str(tmp_path / "empty.db"))
    engine = _fake_engine()
    tool = ScanChunksTool(store=ks, engine=engine, model="test")
    result = tool.execute(question="Anything?")
    assert result.success
    assert "no chunks" in result.content.lower() or result.content == ""


def test_registered() -> None:
    from openjarvis.tools.scan_chunks import ScanChunksTool
    ToolRegistry.register_value("scan_chunks", ScanChunksTool)
    assert ToolRegistry.contains("scan_chunks")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/tools/test_scan_chunks.py -v --tb=short
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the tool**

Create `src/openjarvis/tools/scan_chunks.py`:

```python
"""ScanChunksTool — semantic grep via LM-powered chunk scanning.

Pulls chunks from the KnowledgeStore by filter, batches them, and asks the
LM to extract information relevant to a question.  Catches semantic matches
that keyword-based BM25 search misses.
"""

from __future__ import annotations

from typing import Any, List, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import Message, Role, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolSpec

_DEFAULT_MAX_CHUNKS = 200
_DEFAULT_BATCH_SIZE = 20


@ToolRegistry.register("scan_chunks")
class ScanChunksTool(BaseTool):
    """Semantic grep — feeds chunks to the LM to find information BM25 misses."""

    tool_id = "scan_chunks"

    def __init__(
        self,
        store: Optional[KnowledgeStore] = None,
        engine: Optional[InferenceEngine] = None,
        model: str = "",
    ) -> None:
        self._store = store
        self._engine = engine
        self._model = model

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="scan_chunks",
            description=(
                "Semantic search — feeds chunks from the knowledge store to an LM "
                "that reads the actual text looking for relevant information. "
                "Use when keyword search (knowledge_search) misses semantic matches "
                "(e.g. searching for 'VCs' when text says 'fundraising round'). "
                "Slower but catches what BM25 misses. "
                "Filters: source, doc_type, since, until."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "What to look for in the chunks.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Filter by source (e.g. 'granola', 'gmail').",
                    },
                    "doc_type": {
                        "type": "string",
                        "description": "Filter by doc type (e.g. 'document', 'email').",
                    },
                    "since": {
                        "type": "string",
                        "description": "Only chunks after this ISO timestamp.",
                    },
                    "until": {
                        "type": "string",
                        "description": "Only chunks before this ISO timestamp.",
                    },
                    "max_chunks": {
                        "type": "integer",
                        "description": f"Max chunks to scan (default {_DEFAULT_MAX_CHUNKS}).",
                    },
                },
                "required": ["question"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._store is None or self._engine is None:
            return ToolResult(
                tool_name="scan_chunks",
                content="Scan tool not configured (missing store or engine).",
                success=False,
            )

        question: str = params.get("question", "")
        if not question:
            return ToolResult(
                tool_name="scan_chunks",
                content="No question provided.",
                success=False,
            )

        source: str = params.get("source", "")
        doc_type: str = params.get("doc_type", "")
        since: str = params.get("since", "")
        until: str = params.get("until", "")
        max_chunks: int = int(params.get("max_chunks", _DEFAULT_MAX_CHUNKS))
        batch_size: int = _DEFAULT_BATCH_SIZE

        # Pull chunks matching filters
        where_clauses: List[str] = []
        sql_params: List[Any] = []

        if source:
            where_clauses.append("source = ?")
            sql_params.append(source)
        if doc_type:
            where_clauses.append("doc_type = ?")
            sql_params.append(doc_type)
        if since:
            where_clauses.append("timestamp >= ?")
            sql_params.append(since)
        if until:
            where_clauses.append("timestamp <= ?")
            sql_params.append(until)

        where = ""
        if where_clauses:
            where = "WHERE " + " AND ".join(where_clauses)

        sql = f"SELECT content, source, title, author FROM knowledge_chunks {where} LIMIT ?"
        sql_params.append(max_chunks)

        rows = self._store._conn.execute(sql, sql_params).fetchall()

        if not rows:
            return ToolResult(
                tool_name="scan_chunks",
                content="No chunks found matching filters.",
                success=True,
                metadata={"chunks_scanned": 0},
            )

        # Batch and scan
        findings: List[str] = []
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            batch_text = "\n\n---\n\n".join(
                f"[{row['source']}] {row['title']} by {row['author']}:\n{row['content']}"
                for row in batch
            )

            messages = [
                Message(
                    role=Role.USER,
                    content=(
                        f"/no_think\n"
                        f"Extract any information relevant to this question: {question}\n\n"
                        f"If nothing is relevant, reply with exactly: NOTHING_RELEVANT\n\n"
                        f"Chunks:\n{batch_text}"
                    ),
                ),
            ]

            result = self._engine.generate(
                messages, model=self._model, max_tokens=1024
            )
            content = result.get("content", "").strip()
            if content and "NOTHING_RELEVANT" not in content:
                findings.append(content)

        if not findings:
            return ToolResult(
                tool_name="scan_chunks",
                content=f"Scanned {len(rows)} chunks — no relevant information found.",
                success=True,
                metadata={"chunks_scanned": len(rows)},
            )

        return ToolResult(
            tool_name="scan_chunks",
            content="\n\n".join(findings),
            success=True,
            metadata={"chunks_scanned": len(rows), "batches_with_findings": len(findings)},
        )


__all__ = ["ScanChunksTool"]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/tools/test_scan_chunks.py -v --tb=short
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/tools/scan_chunks.py tests/tools/test_scan_chunks.py
git commit -m "feat: add scan_chunks tool for LM-powered semantic grep"
```

---

### Task 3: Rewrite system prompt + wire all tools + tune loop guard

**Files:**
- Modify: `src/openjarvis/agents/deep_research.py` (system prompt + max_turns)
- Modify: `src/openjarvis/cli/deep_research_setup_cmd.py` (`_launch_chat` function)

- [ ] **Step 1: Replace `DEEP_RESEARCH_SYSTEM_PROMPT` in `deep_research.py`**

Replace the entire `DEEP_RESEARCH_SYSTEM_PROMPT` string (from line 33 to line 55) with:

```python
DEEP_RESEARCH_SYSTEM_PROMPT = """\
/no_think
You are a deep research agent with access to a personal knowledge base \
containing emails, messages, meeting notes, documents, and notes.

## Your Tools

- **knowledge_search**: BM25 keyword search. Best for finding specific topics, \
names, or phrases. Use filters (source, author, since, until) to narrow results.

- **knowledge_sql**: Run read-only SQL against the knowledge_chunks table. \
Schema: knowledge_chunks(id, content, source, doc_type, doc_id, title, \
author, participants, timestamp, thread_id, url, metadata, chunk_index). \
Best for counting, ranking, and aggregation. \
Example: SELECT author, COUNT(*) as n FROM knowledge_chunks \
WHERE source='imessage' GROUP BY author ORDER BY n DESC LIMIT 10

- **scan_chunks**: Semantic search — feeds chunks to an LM that reads the \
actual text looking for relevant information. Use when keyword search returns \
nothing useful or when you need semantic matching (e.g. searching for 'VCs' \
when text says 'fundraising round'). Slower but catches what BM25 misses.

- **think**: Reasoning scratchpad. Use between searches to plan your next \
query, evaluate findings so far, and identify gaps.

## Strategy

1. Start with **think** to plan your approach — which tools suit this query?
2. For "who/what/how many" queries → use **knowledge_sql** with GROUP BY
3. For specific topics or names → use **knowledge_search**
4. If keyword search returns nothing useful → try **scan_chunks** with filters
5. Cross-reference across sources (emails, messages, meeting notes)
6. After gathering evidence → write a cited narrative report

## Citation Format

Cite sources as: [source] title -- author
End with a Sources section listing all referenced items.

## Rules

- Always cite your sources. Never present information without attribution.
- Make at least two searches to cross-reference across different sources.
- If a search returns no results, try a different tool or rephrase the query.
- Prefer specificity: filter by source, author, or date when appropriate.
- Your final answer should be a coherent narrative, not a list of raw results."""
```

- [ ] **Step 2: Update `_default_max_turns` from 5 to 8**

In `deep_research.py`, change:

```python
_default_max_turns = 8
```

- [ ] **Step 3: Update `_launch_chat` in `deep_research_setup_cmd.py` to wire all 4 tools**

Replace the tool setup section in `_launch_chat` (around lines 293-303):

```python
def _launch_chat(store: KnowledgeStore, console: Console) -> None:
    """Start an interactive Deep Research chat session."""
    from openjarvis.agents.deep_research import DeepResearchAgent
    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    console.print("\n[bold]Setting up Deep Research agent...[/bold]")

    # Engine
    engine = OllamaEngine()
    if not engine.health():
        console.print(
            "[red]Ollama is not running.[/red] Start it with: "
            "[bold]ollama serve[/bold]"
        )
        return

    models = engine.list_models()
    if _OLLAMA_MODEL not in models and f"{_OLLAMA_MODEL}:latest" not in models:
        base_name = _OLLAMA_MODEL.split(":")[0]
        matching = [m for m in models if m.startswith(base_name)]
        if not matching:
            console.print(
                f"[yellow]Model {_OLLAMA_MODEL} not found.[/yellow] "
                f"Pull it with: [bold]ollama pull {_OLLAMA_MODEL}[/bold]"
            )
            return

    # Tools
    retriever = TwoStageRetriever(store)
    tools = [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=_OLLAMA_MODEL),
        ThinkTool(),
    ]

    # Agent
    agent = DeepResearchAgent(
        engine=engine,
        model=_OLLAMA_MODEL,
        tools=tools,
        interactive=True,
    )

    console.print(
        f"[green]Ready![/green] Using [bold]{_OLLAMA_MODEL}[/bold] via Ollama.\n"
        "Tools: knowledge_search, knowledge_sql, scan_chunks, think\n"
        "Type your research question. Type [bold]/quit[/bold] to exit.\n"
    )

    # REPL
    while True:
        try:
            query = console.input("[bold blue]research>[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not query:
            continue
        if query.lower() in ("/quit", "/exit", "quit", "exit"):
            break

        try:
            result = agent.run(query)
            console.print(f"\n{result.content}\n")
            if result.metadata and result.metadata.get("sources"):
                console.print("[dim]Sources:[/dim]")
                for s in result.metadata["sources"]:
                    console.print(f"  [dim]- {s}[/dim]")
                console.print()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error: {exc}[/red]\n")
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/agents/test_deep_research.py tests/agents/test_deep_research_integration.py tests/tools/test_knowledge_sql.py tests/tools/test_scan_chunks.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/openjarvis/agents/deep_research.py src/openjarvis/cli/deep_research_setup_cmd.py src/openjarvis/tools/knowledge_sql.py src/openjarvis/tools/scan_chunks.py
```

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/agents/deep_research.py src/openjarvis/cli/deep_research_setup_cmd.py
git commit -m "feat: rewrite DeepResearch system prompt, wire SQL + scan + think tools, increase max_turns to 8"
```

---

### Task 4: Evaluate with 4 test queries

**Files:** None (manual testing)

- [ ] **Step 1: Run the 4 test queries**

```python
import time
from openjarvis.agents.deep_research import DeepResearchAgent
from openjarvis.connectors.retriever import TwoStageRetriever
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.engine.ollama import OllamaEngine
from openjarvis.tools.knowledge_search import KnowledgeSearchTool
from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
from openjarvis.tools.scan_chunks import ScanChunksTool
from openjarvis.tools.think import ThinkTool

store = KnowledgeStore()
engine = OllamaEngine()
retriever = TwoStageRetriever(store)

tools = [
    KnowledgeSearchTool(retriever=retriever),
    KnowledgeSQLTool(store=store),
    ScanChunksTool(store=store, engine=engine, model="qwen3.5:9b"),
    ThinkTool(),
]

agent = DeepResearchAgent(engine=engine, model="qwen3.5:9b", tools=tools, max_turns=8)

queries = [
    "When was my most recent trip to Spain?",
    "Which VCs have I spoken with since 2023?",
    "Who are the 10 people I have spoken with the most over text?",
    "What meetings take up most of my time based on my calendar and meeting logs?",
]

for i, query in enumerate(queries, 1):
    print(f"QUERY {i}: {query}")
    t0 = time.time()
    result = agent.run(query)
    print(result.content[:3000])
    print(f"[Turns: {result.turns}, Tools: {len(result.tool_results)}, Time: {time.time()-t0:.0f}s]\n")
```

- [ ] **Step 2: Compare to v1 results**

v1 returned empty or "no data found" for all 4 queries. Success = at least 3 of 4 produce substantive answers.

- [ ] **Step 3: Push**

```bash
git push origin feat/deep-research-setup
```
