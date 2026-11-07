# Deep Research

A multi-hop research agent that searches across your indexed documents, cross-references information, and returns answers with citations. It reasons through complex queries step by step, pulling context from multiple sources in your local knowledge base.

## Quickstart (5 minutes)

### 1. Install and initialize

```bash
git clone https://github.com/open-jarvis/FridayAI.git
cd FridayAI
uv sync --extra dev
friday init --preset deep-research --force
```

This writes a pre-configured `~/.friday_ai/config.toml` for the deep research agent.

### 2. Index your documents

```bash
# Install Ollama: https://ollama.com
ollama pull qwen3.5:9b

# Index a directory of files
friday memory index ./docs/
friday memory index ~/Documents/papers/
```

FridayAI chunks the content and stores it in a local SQLite/FTS5 database. Supported formats include `.txt`, `.md`, `.pdf`, `.py`, `.json`, `.csv`, and more.

### 3. Ask a research question

```bash
friday ask "Summarize all documents about transformer architectures"
```

The deep research agent will:

1. Search your indexed documents for relevant chunks
2. Reason across multiple sources (up to 8 hops)
3. Synthesize a coherent answer with references to source documents

## CLI Commands

```bash
# Ask a question (uses deep_research agent by default with this config)
friday ask "What meetings did I have with Alice last month?"

# Explicitly specify the agent
friday ask --agent deep_research "Compare the approaches described in paper-a.pdf and paper-b.pdf"

# Index more documents
friday memory index ~/Downloads/reports/
friday memory index ./notes.md

# Search memory directly
friday memory search "project timeline"
friday memory search -k 20 "budget estimates"

# Check what's indexed
friday memory stats
```

## Configuration Reference

The preset writes this to `~/.friday_ai/config.toml`:

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"
temperature = 0.3               # Low temperature for factual research

[agent]
default_agent = "deep_research"
max_turns = 8                   # Multi-hop reasoning steps

[tools]
enabled = ["knowledge_search", "knowledge_sql", "scan_chunks", "think", "web_search"]

[tools.storage]
default_backend = "sqlite"
```

### Key settings

| Setting | Default | Description |
|---------|---------|-------------|
| `intelligence.default_model` | `qwen3.5:9b` | The model used for reasoning. Larger models (e.g., `qwen3.5:35b`) give better results on complex queries. |
| `intelligence.temperature` | `0.3` | Low temperature keeps answers factual. Increase for more creative synthesis. |
| `agent.max_turns` | `8` | Maximum reasoning hops. Increase for deeply nested research tasks. |
| `tools.enabled` | 5 tools | `knowledge_search` (semantic), `knowledge_sql` (structured), `scan_chunks` (browse), `think` (reasoning scratchpad), `web_search` (online fallback). |
| `tools.storage.default_backend` | `sqlite` | FTS5-backed full-text search. Also supports `faiss`, `colbert`, `bm25`, and `hybrid`. |

## Example Queries

```bash
# Summarize across multiple documents
friday ask "Summarize all emails about the Q3 budget review"

# Cross-reference sources
friday ask "What do papers A and B agree on regarding attention mechanisms?"

# Find specific information
friday ask "What meetings did I have with Alice last month?"

# Extract structured data
friday ask "List all action items from the meeting notes in ~/Documents/meetings/"

# Research with web fallback
friday ask "Compare our internal benchmarks with the latest published results"
```

## Indexing Different Data Sources

### Local files and directories

```bash
# Recursively index a directory
friday memory index ~/Documents/

# Single file
friday memory index ./report.pdf

# Custom chunk size for long documents
friday memory index ./paper.pdf --chunk-size 1024 --chunk-overlap 128
```

### PDFs

PDFs are automatically extracted and chunked. For best results with scanned PDFs, ensure they have been OCR-processed.

```bash
friday memory index ~/Papers/*.pdf
```

### Web pages

Use the `web_search` tool (enabled by default in this config) to pull in online sources at query time. For persistent indexing of web content, download pages first:

```bash
curl -s https://example.com/article | friday memory index --stdin --source "example.com"
```

### Code repositories

```bash
friday memory index ./src/ --chunk-size 256
```

Smaller chunk sizes work better for code, where each function or class is a natural unit.

## Troubleshooting

**"No results found"** -- Make sure you have indexed documents first with `friday memory index`. Check indexed content with `friday memory stats`.

**Answers are too vague** -- Try increasing `max_turns` in the config (e.g., `12` or `15`) to give the agent more reasoning steps. You can also try a larger model like `qwen3.5:35b`.

**Slow responses** -- The agent makes multiple search passes. Each turn involves a model call. Reduce `max_turns` or use a smaller model (`qwen3.5:4b`) for faster but less thorough results.

**Web search not working** -- The `web_search` tool needs no API key by default; it uses the You.com keyless free tier, which is rate limited per IP. Set `YOUDOTCOM_API_KEY` (free key at [you.com/platform](https://you.com/platform?utm_source=friday-ai-friday_ai&utm_medium=oss_integration&utm_campaign=2026-09-oss-integrations&utm_content=docs)) for higher limits, or install Tavily with `uv sync --extra tools-search` and set `TAVILY_API_KEY`. Set `SERPLY_API_KEY` ([serply.io](https://serply.io)) to search through Google itself, which is the only engine here that honours Google operators such as `site:` and `after:` in a research query. Set `FIRECRAWL_API_KEY` ([firecrawl.dev](https://www.firecrawl.dev/app/api-keys?utm_source=friday_ai&utm_medium=integration)) to have URL lookups, including PDFs, return markdown. A `WARNING` naming the failed engine is logged whenever search drops to the DuckDuckGo fallback.

**Wrong chunks retrieved** -- Try re-indexing with different chunk sizes. For technical documents, smaller chunks (`256`) often retrieve more precisely. For narrative text, larger chunks (`1024`) preserve more context.
