# Deep Research Vertical Slice — End-to-End on Laptop

## Goal

Get the full Deep Research experience working end-to-end on a MacBook with real personal data: connect local sources → ingest → retrieve → research agent → cited report. Then wire the API router so the desktop wizard UI works too.

## Scope

**In scope:**
- Fix Apple Notes protobuf text extraction + broken test
- `jarvis deep-research-setup` CLI command that auto-detects and ingests local sources
- Ingest 3 local sources into shared KnowledgeStore (~/.openjarvis/knowledge.db):
  - Apple Notes (42 notes, ~100 chunks)
  - iMessage (52K messages, ~52K chunks)
  - Obsidian vault (size varies)
- Run TwoStageRetriever queries (BM25 + optional ColBERT rerank) against combined corpus
- Run DeepResearchAgent with Qwen3.5 4B via Ollama — multi-hop research producing cited reports
- Wire connectors_router into FastAPI app (one-line fix)
- Smoke test wizard UI via browser

**Out of scope:**
- OAuth connectors (Gmail, Drive, Calendar, Contacts, Slack, Notion, Dropbox)
- Channel plugins (iMessage/WhatsApp/Slack bot)
- Sync scheduling, performance optimization
- ColBERT disk persistence tuning

## Architecture

### Data Flow

```
Local Sources (no OAuth)
  Apple Notes → NoteStore.sqlite → protobuf → plain text
  iMessage → chat.db → messages with contact/conversation metadata
  Obsidian → filesystem → .md files
      ↓
Connectors (AppleNotesConnector, IMessageConnector, ObsidianConnector)
  yield Document(doc_id, source, doc_type, content, title, author, timestamp, ...)
      ↓
IngestionPipeline
  Dedup by doc_id → SemanticChunker (512 token chunks) → KnowledgeStore
      ↓
KnowledgeStore (~/.openjarvis/knowledge.db)
  SQLite + FTS5 (BM25), ~50K-55K chunks
      ↓
TwoStageRetriever
  Stage 1: BM25 recall (top 100) with source/type/date filters
  Stage 2: ColBERT rerank (top 10) — optional, falls back to BM25-only
      ↓
DeepResearchAgent (Qwen3.5 4B via Ollama)
  Multi-hop loop (up to 5 turns):
    think → knowledge_search → refine → knowledge_search → ... → synthesize
  Output: cited research report with source attribution
```

### CLI Command: `jarvis deep-research-setup`

Interactive CLI command that:
1. Auto-detects available local sources (checks if NoteStore.sqlite, chat.db exist; prompts for Obsidian vault path or skips if none)
2. Confirms with user which sources to connect
3. Syncs each source via SyncEngine + IngestionPipeline into ~/.openjarvis/knowledge.db
4. Prints summary (sources, document count, chunk count)
5. Drops user into `jarvis chat` with DeepResearchAgent configured

### LLM Configuration

- Engine: Ollama
- Model: qwen3.5:4b (pulled via `ollama pull qwen3.5:4b`)
- Agent: DeepResearchAgent with knowledge_search + think tools
- Expected latency: fast token generation on Apple Silicon, main cost is ColBERT model loading on first query

### API Router Fix

The `connectors_router.py` file exists with all endpoints but was never registered in the FastAPI app. Fix: add `app.include_router(create_connectors_router())` in `app.py` or `api_routes.py`.

## Test Plan

### Retrieval Quality Checks
1. Name search spanning Apple Notes + iMessage (person who appears in both)
2. Topical search across Obsidian vault
3. Time-bounded query ("what was I working on last week")

### Agent Quality Checks
1. Cross-source research query requiring multi-hop
2. Check that citations point back to real source documents
3. Check that agent uses multiple search refinements (not just one query)

### Wizard Smoke Test
1. `jarvis serve` → open localhost in browser
2. Walk through wizard: pick sources → connect → ingest → ready screen
3. Verify sync status polling shows progress
4. Verify "Ready" screen appears with suggestion queries

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| 4B model too small for multi-hop reasoning | Agent produces shallow one-hop reports | Swap to larger Ollama model or cloud engine |
| 52K iMessage chunks slow to ingest | Long initial setup time | Show progress, allow incremental use |
| ColBERT model loading slow on first query | Bad first-query UX | Fall back to BM25-only, lazy load ColBERT |
| Apple Notes protobuf extraction still garbled for some notes | Missing or corrupted content | Graceful degradation, skip notes with no extractable text |
