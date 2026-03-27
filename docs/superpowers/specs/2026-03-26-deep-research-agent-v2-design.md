# Deep Research Agent v2 — Better Tools + Prompts

## Goal

Improve the DeepResearchAgent so it can answer aggregation queries ("who do I talk to most"), semantic/fuzzy queries ("which VCs have I spoken with"), and factual queries ("when was my trip to Spain") by adding SQL and LM-scan tools alongside better prompts.

## Evaluation Criteria

Re-run these 4 queries and compare to v1 (which returned empty or "no data found" for all 4):

1. "When was my most recent trip to Spain?"
2. "Which VCs have I spoken with since 2023?"
3. "Who are the 10 people I have spoken with the most over text?"
4. "What meetings take up most of my time based on my calendar and meeting logs?"

Success = the agent produces substantive, cited answers for at least 3 of 4.

## Changes

### 1. New tool: `knowledge_sql`

Read-only SQL queries against the `knowledge_chunks` table. The agent writes SELECT statements to aggregate, count, filter, and rank data.

```python
class KnowledgeSQLTool(BaseTool):
    tool_id = "knowledge_sql"

    def execute(self, query: str) -> ToolResult:
        # Reject non-SELECT queries
        # Execute against KnowledgeStore's SQLite connection
        # Return formatted rows (max 50 rows)
```

Exposed schema (included in the tool description so the model knows the columns):
```
knowledge_chunks(id, content, source, doc_type, doc_id, title, author,
                 participants, timestamp, thread_id, url, metadata, chunk_index)
```

### 2. New tool: `scan_chunks`

Semantic grep — pulls chunks by filter, batches through the LM with a question.

```python
class ScanChunksTool(BaseTool):
    tool_id = "scan_chunks"

    def execute(self, question: str, source: str = "", doc_type: str = "",
                since: str = "", until: str = "", max_chunks: int = 200,
                batch_size: int = 20) -> ToolResult:
        # 1. Pull chunks matching filters from KnowledgeStore
        # 2. Batch into groups of batch_size
        # 3. For each batch, call engine.generate():
        #    "Extract info relevant to: {question}\n\nChunks:\n{batch_text}"
        # 4. Return aggregated findings
```

This is the "LM combs through tokens" capability — catches semantic matches that BM25 keyword search misses.

### 3. Wire `think` tool

The `think` tool already exists at `src/openjarvis/tools/think.py`. Wire it into the DeepResearchAgent's tool list in `deep_research_setup_cmd.py`.

### 4. System prompt rewrite

Replace the current generic prompt with one that teaches query strategies:

```
/no_think
You are a deep research agent with access to a personal knowledge base
containing emails, messages, meeting notes, documents, and notes.

## Your Tools

- **knowledge_search**: BM25 keyword search. Best for finding specific topics,
  names, or phrases. Use filters (source, author, since, until) to narrow results.

- **knowledge_sql**: Run SQL queries against the knowledge_chunks table.
  Schema: knowledge_chunks(id, content, source, doc_type, doc_id, title,
  author, participants, timestamp, thread_id, url, metadata, chunk_index)
  Best for: counting, ranking, aggregation, time-range queries.
  Example: SELECT author, COUNT(*) as n FROM knowledge_chunks WHERE source='imessage' GROUP BY author ORDER BY n DESC LIMIT 10

- **scan_chunks**: Semantic search — feeds chunks to an LM that reads the actual
  text looking for relevant information. Use when keyword search misses semantic
  matches (e.g. searching for "VCs" when text says "fundraising round").
  Slower but catches what BM25 misses.

- **think**: Reasoning scratchpad. Use between searches to plan your next query,
  evaluate findings, and identify gaps.

## Strategy

1. Start with **think** to plan your approach — which tools suit this query?
2. For "who/what/how many" queries → start with **knowledge_sql**
3. For specific topics → start with **knowledge_search**
4. If keyword search returns nothing useful → try **scan_chunks** with broader filters
5. Cross-reference across sources — search emails, then messages, then notes
6. After gathering evidence → write a cited narrative report

## Citation Format

Cite sources as: [source] title -- author
Include a Sources section at the end.
```

### 5. Loop guard tuning

Increase the `max_turns` default from 5 to 8, and configure the loop guard (if present) with a higher poll budget to accommodate the larger tool set.

## What Does NOT Change

- Agent class structure (DeepResearchAgent)
- Retriever pipeline (BM25 + optional ColBERT)
- Ingestion pipeline
- Connectors
- CLI command
