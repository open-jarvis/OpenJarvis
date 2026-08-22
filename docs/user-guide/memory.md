# Memory

The memory system provides persistent, searchable document storage for retrieval-augmented generation (RAG). It supports multiple retrieval backends, a configurable chunking pipeline, document ingestion from files and directories, and automatic context injection into prompts.

## Architecture

```
Documents  -->  Chunking Pipeline  -->  Memory Backend  -->  Context Injection  -->  Prompt
  (files)       (split + overlap)      (store + index)      (retrieve + format)    (to LLM)
```

---

## MemoryBackend ABC

All memory backends implement the `MemoryBackend` abstract base class.

```python
class MemoryBackend(ABC):
    backend_id: str

    def store(self, content: str, *, source: str = "", metadata: dict | None = None) -> str:
        """Persist content and return a unique document ID."""

    def retrieve(self, query: str, *, top_k: int = 5, **kwargs) -> list[RetrievalResult]:
        """Search for query and return the top-k results."""

    def delete(self, doc_id: str) -> bool:
        """Delete a document by ID. Return True if it existed."""

    def clear(self) -> None:
        """Remove all stored documents."""
```

### RetrievalResult

Each retrieval returns a list of `RetrievalResult` objects:

| Field      | Type             | Description                                |
|------------|------------------|--------------------------------------------|
| `content`  | `str`            | The retrieved text chunk                   |
| `score`    | `float`          | Relevance score (higher is better)         |
| `source`   | `str`            | Originating file path or identifier        |
| `metadata` | `dict[str, Any]` | Additional metadata (chunk index, etc.)    |

---

## Backends

### SQLite / FTS5 (Default)

**Registry key:** `sqlite`

The default backend using SQLite's built-in FTS5 full-text search extension. Zero external dependencies -- uses Python's standard `sqlite3` module.

- **Scoring:** BM25 ranking via FTS5 MATCH queries
- **Persistence:** SQLite database file (default: `~/.openjarvis/memory.db`)
- **Dependencies:** None (built into Python)

```python
from openjarvis.core.registry import MemoryRegistry

backend = MemoryRegistry.create("sqlite", db_path="./memory.db")
doc_id = backend.store("Hello world", source="test.txt")
results = backend.retrieve("hello")
backend.close()
```

!!! tip "When to use SQLite/FTS5"
    Use this backend when you want zero-configuration setup, keyword-based search is sufficient, and you need persistent storage across restarts. It works well for small to medium document collections.

### FAISS

**Registry key:** `faiss`

Dense neural retrieval using Facebook AI Similarity Search. Embeds documents and queries into dense vectors and retrieves by cosine similarity.

- **Scoring:** Cosine similarity via inner-product search on L2-normalized vectors
- **Persistence:** In-memory only (data is lost on restart)
- **Dependencies:** `faiss-cpu` (or `faiss-gpu`), `sentence-transformers`

```bash
uv sync --extra memory-faiss
```

```python
backend = MemoryRegistry.create("faiss")
doc_id = backend.store("Neural networks are computational models")
results = backend.retrieve("deep learning architectures")
```

!!! tip "When to use FAISS"
    Use this backend when you need semantic search (finding conceptually similar content even without exact keyword matches). Best for use cases where you can re-index on each run since data is not persisted.

### ColBERTv2

**Registry key:** `colbert`

Late-interaction retrieval using ColBERT's token-level embeddings with MaxSim scoring. Provides the highest retrieval quality among the available backends.

- **Scoring:** MaxSim -- for each query token, take the maximum cosine similarity across all document tokens, then sum
- **Persistence:** In-memory only
- **Dependencies:** `colbert-ai`, `torch`

```bash
uv sync --extra memory-colbert
```

```python
backend = MemoryRegistry.create(
    "colbert",
    checkpoint="colbert-ir/colbertv2.0",
    device="cpu",
)
```

| Parameter    | Default                    | Description                         |
|--------------|----------------------------|-------------------------------------|
| `checkpoint` | `"colbert-ir/colbertv2.0"` | ColBERT model checkpoint            |
| `device`     | `"cpu"`                    | Computation device (`cpu` or `cuda`) |

!!! tip "When to use ColBERTv2"
    Use this backend when retrieval quality is the top priority and you have the compute resources for it. The checkpoint is lazily loaded on first use to avoid slow imports. Best for research and evaluation workloads.

### BM25

**Registry key:** `bm25`

Classic probabilistic ranking using the BM25 Okapi algorithm. In-memory implementation using the `rank_bm25` library.

- **Scoring:** BM25 Okapi term-frequency scoring
- **Persistence:** In-memory only
- **Dependencies:** `rank-bm25`

```bash
uv sync --extra memory-bm25
```

```python
backend = MemoryRegistry.create("bm25")
backend.store("Python is a programming language", source="intro.txt")
results = backend.retrieve("programming language")
```

!!! tip "When to use BM25"
    Use this backend when you want classic keyword-based retrieval without database dependencies. Useful as the sparse component in a hybrid retrieval setup.

### Hybrid (RRF Fusion)

**Registry key:** `hybrid`

Combines a sparse retriever and a dense retriever using Reciprocal Rank Fusion (RRF). Documents are stored in both sub-backends, and retrieval results are merged.

- **Scoring:** `RRF_score(d) = sum(weight_i / (k + rank_i(d)))` across both ranked lists
- **Persistence:** Depends on sub-backends
- **Dependencies:** Depends on sub-backends

```python
from openjarvis.tools.storage.bm25 import BM25Memory
from openjarvis.tools.storage.faiss_backend import FAISSMemory

sparse = BM25Memory()
dense = FAISSMemory()

backend = MemoryRegistry.create(
    "hybrid",
    sparse=sparse,
    dense=dense,
    k=60,
    sparse_weight=1.0,
    dense_weight=1.0,
)
```

!!! note "Backward compatibility"
    The old `from openjarvis.memory.bm25 import BM25Memory` still works via backward-compatibility shims, but new code should use the canonical `openjarvis.tools.storage.*` imports.

| Parameter       | Default | Description                              |
|-----------------|---------|------------------------------------------|
| `sparse`        | --      | Sparse retrieval backend (e.g., BM25)    |
| `dense`         | --      | Dense retrieval backend (e.g., FAISS)    |
| `k`             | `60`    | RRF constant                             |
| `sparse_weight` | `1.0`   | Weight for sparse retriever results      |
| `dense_weight`  | `1.0`   | Weight for dense retriever results       |

The hybrid backend over-fetches (3x `top_k`) from each sub-backend before applying fusion to improve result quality.

!!! tip "When to use Hybrid"
    Use this backend when you want the best of both keyword matching and semantic similarity. The RRF fusion approach is robust and does not require tuning score distributions across different retrieval methods.

### Mixedbread (toast-1)

**Registry key:** `mixedbread`

Cloud retrieval through [Mixedbread](https://www.mixedbread.com)'s [toast-1](https://www.mixedbread.com/blog/toast-1) search agent. Documents are uploaded to a managed Mixedbread store; retrieval runs an agentic search that performs query decomposition, evidence gathering, and ranking server-side before returning curated chunks.

- **Scoring:** Relevance scores returned by the toast-1 search agent
- **Persistence:** Remote (Mixedbread store, survives restarts)
- **Dependencies:** `mixedbread`, an API key in `MXBAI_API_KEY`

```bash
uv sync --extra memory-mixedbread
export MXBAI_API_KEY="..."
```

```python
backend = MemoryRegistry.create("mixedbread", store_name="openjarvis-memory")
doc_id = backend.store("Quarterly revenue grew 12% ...", source="report.md")
results = backend.retrieve("what changed in Q3 revenue?")
```

| Parameter           | Default               | Description                                                  |
|---------------------|-----------------------|--------------------------------------------------------------|
| `store_name`        | `"openjarvis-memory"` | Mixedbread store to use (created on first use)               |
| `api_key`           | `MXBAI_API_KEY` env   | Mixedbread API key                                           |
| `agentic`           | `True`                | Use toast-1 agentic search (plain chunk search when `False`) |
| `wait_for_indexing` | `False`               | Block `store()` until the document is searchable             |

!!! warning "Cloud backend"
    Unlike every other backend, this one sends stored documents and queries to the Mixedbread cloud API. Enable it only deliberately (`[tools.storage] default_backend = "mixedbread"`) and never index content that must stay on-device. Uploads are indexed asynchronously -- an immediate `retrieve()` after `store()` may not see the new document unless `wait_for_indexing=True`.

!!! tip "When to use Mixedbread"
    Use this backend when retrieval quality over a large corpus matters more than staying fully local: toast-1 handles multi-hop query decomposition and ranking server-side, so even a small local model receives curated context instead of driving the search loop itself.

---

## Backend Comparison

| Backend     | Search Type       | Persistence | Dependencies         | Quality  | Speed    |
|-------------|-------------------|-------------|----------------------|----------|----------|
| SQLite/FTS5 | Keyword (BM25)    | Yes         | None                 | Good     | Fast     |
| FAISS       | Dense (cosine)    | No          | faiss, transformers  | Better   | Fast     |
| ColBERTv2   | Late interaction  | No          | colbert-ai, torch    | Best     | Slower   |
| BM25        | Keyword (Okapi)   | No          | rank-bm25            | Good     | Fast     |
| Hybrid      | Fusion (RRF)      | Mixed       | Sub-backend deps     | Better   | Medium   |
| Mixedbread  | Agentic (toast-1) | Yes (cloud) | mixedbread, API key  | Best     | Medium   |

---

## Chunking Pipeline

Documents are split into chunks before storage using a configurable pipeline. The chunker respects paragraph boundaries when possible.

### ChunkConfig

| Field           | Type  | Default | Description                              |
|-----------------|-------|---------|------------------------------------------|
| `chunk_size`    | `int` | `512`   | Target chunk size in whitespace tokens   |
| `chunk_overlap` | `int` | `64`    | Overlap between consecutive chunks       |
| `min_chunk_size`| `int` | `50`    | Minimum chunk size (smaller chunks are discarded) |

### How Chunking Works

1. The document is split into paragraphs (separated by double newlines).
2. Paragraphs are accumulated until the token count exceeds `chunk_size`.
3. The accumulated content is emitted as a chunk.
4. The last `chunk_overlap` tokens are retained as context for the next chunk.
5. Paragraphs exceeding `chunk_size` are split into fixed-size windows with overlap.

### Chunk Output

Each chunk is a `Chunk` object with:

| Field      | Type             | Description                              |
|------------|------------------|------------------------------------------|
| `content`  | `str`            | The chunk text                           |
| `source`   | `str`            | Originating file path                    |
| `offset`   | `int`            | Token offset within the document         |
| `index`    | `int`            | Sequential chunk index                   |
| `metadata` | `dict[str, Any]` | Additional metadata                      |

---

## Document Ingestion

The `ingest_path()` function reads files or recursively walks directories, producing chunks ready for storage.

### Supported File Types

| Type     | Extensions                                                  |
|----------|-------------------------------------------------------------|
| Text     | `.txt` and other plain text files                           |
| Markdown | `.md`, `.markdown`, `.mdx`                                  |
| Code     | `.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.rb`, `.sh`, `.yaml`, `.json`, `.html`, `.css`, and more |
| PDF      | `.pdf` (requires `pdfplumber`: `uv sync --extra memory-pdf`) |

### Automatic Skipping

The ingestion pipeline automatically skips:

- Hidden files and directories (starting with `.`)
- Common non-content directories: `__pycache__`, `node_modules`, `.venv`, `.git`, etc.
- Binary files: images, audio, video, archives, compiled files
- Files that cannot be read (permission errors, encoding issues)

### Usage

```python
from pathlib import Path
from openjarvis.tools.storage.chunking import ChunkConfig
from openjarvis.tools.storage.ingest import ingest_path

# Default chunking
chunks = ingest_path(Path("./docs/"))

# Custom chunking
config = ChunkConfig(chunk_size=256, chunk_overlap=32)
chunks = ingest_path(Path("./notes.md"), config=config)

print(f"Produced {len(chunks)} chunks")
for chunk in chunks[:3]:
    print(f"  [{chunk.index}] {chunk.source}: {chunk.content[:60]}...")
```

---

## Context Injection

When memory context injection is enabled (the default), queries are automatically augmented with relevant retrieved documents before being sent to the model. Each retrieved passage includes source attribution.

### ContextConfig

| Field               | Type    | Default | Description                                      |
|---------------------|---------|---------|--------------------------------------------------|
| `enabled`           | `bool`  | `True`  | Whether context injection is active              |
| `top_k`             | `int`   | `5`     | Number of results to retrieve                    |
| `min_score`         | `float` | `0.1`   | Minimum relevance score threshold                |
| `max_context_tokens`| `int`   | `2048`  | Maximum total tokens in injected context         |

### How It Works

1. The user's query is searched against the memory backend.
2. Results below `min_score` are filtered out.
3. Results are truncated to fit within `max_context_tokens`.
4. A system message is prepended to the conversation with the formatted context:

```
The following context was retrieved from the knowledge base.
Use it to inform your response, citing sources where applicable:

[Source: docs/intro.md] OpenJarvis is a modular AI framework...

[Source: docs/config.md] Configuration is stored in TOML format...
```

### Disabling Context Injection

=== "CLI"

    ```bash
    jarvis ask --no-context "Tell me about Python"
    ```

=== "Python SDK"

    ```python
    response = j.ask("Tell me about Python", context=False)
    ```

---

## CLI Usage

```bash
# Index a directory
jarvis memory index ./docs/

# Index with custom chunking
jarvis memory index ./notes/ --chunk-size 256 --chunk-overlap 32

# Search the memory store
jarvis memory search "machine learning"

# Search with more results
jarvis memory search -k 10 "neural networks"

# Show memory statistics
jarvis memory stats
```

## SDK Usage

```python
from openjarvis import Jarvis

j = Jarvis()

# Index documents
result = j.memory.index("./docs/", chunk_size=512, chunk_overlap=64)
print(f"Indexed {result['chunks']} chunks")

# Search
results = j.memory.search("configuration", top_k=3)
for r in results:
    print(f"  [{r['score']:.4f}] {r['source']}: {r['content'][:80]}...")

# Statistics
stats = j.memory.stats()
print(f"Backend: {stats['backend']}, Documents: {stats.get('count', 'N/A')}")

# Clean up
j.close()
```
