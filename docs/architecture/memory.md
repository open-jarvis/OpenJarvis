# Memory Primitive

The Memory primitive provides **persistent, searchable storage** for documents and knowledge. It enables context injection -- retrieving relevant information from indexed documents and prepending it to prompts so the LLM can answer questions grounded in specific content.

---

## MemoryBackend ABC

All memory backends implement the `MemoryBackend` abstract base class:

```python
class MemoryBackend(ABC):
    backend_id: str

    @abstractmethod
    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""

    @abstractmethod
    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search for *query* and return the top-k results."""

    @abstractmethod
    def delete(self, doc_id: str) -> bool:
        """Delete a document by id. Return True if it existed."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all stored documents."""
```

### RetrievalResult

Search results are returned as `RetrievalResult` objects:

```python
@dataclass(slots=True)
class RetrievalResult:
    content: str                  # The document text
    score: float = 0.0            # Relevance score (higher is better)
    source: str = ""              # Originating file path or identifier
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## Backend Comparison

| Backend | Registry Key | Index Type | Extra Dependencies | GPU Required | Quality | Speed | Persistence |
|---------|-------------|-----------|-------------------|-------------|---------|-------|-------------|
| **SQLite/FTS5** | `sqlite` | Full-text (BM25) | None | No | Good | Fast | Disk (SQLite) |
| **FAISS** | `faiss` | Dense vector | `faiss-cpu`, `sentence-transformers` | Optional | Very Good | Fast | In-memory |
| **ColBERTv2** | `colbert` | Late interaction | `colbert-ai`, `torch` | Optional | Excellent | Slower | In-memory |
| **BM25** | `bm25` | Term-frequency | `rank-bm25` | No | Good | Fast | In-memory |
| **Hybrid** | `hybrid` | RRF fusion | Depends on sub-backends | Depends | Best | Moderate | Depends |

### SQLite/FTS5 (Default)

The zero-dependency default backend. Uses SQLite's built-in FTS5 extension for full-text search with BM25 ranking.

- **Storage:** Documents stored in a `documents` table with automatic FTS5 indexing via triggers
- **Search:** FTS5 `MATCH` queries with BM25 ranking (more negative rank = better match, converted to positive scores)
- **Query escaping:** Each word is quoted to avoid FTS5 syntax errors
- **Persistence:** Data persists across restarts in `~/.friday_ai/memory.db`

### FAISS

Dense retrieval using Facebook AI Similarity Search. Documents are embedded into vector space and searched via cosine similarity.

- **Index type:** `IndexFlatIP` (inner-product, equivalent to cosine similarity when vectors are L2-normalized)
- **Embedding model:** `all-MiniLM-L6-v2` by default (384-dim, ~22 MB)
- **Deletion:** Soft-delete (documents are marked as deleted but remain in the index)
- **Persistence:** In-memory only -- data is lost on restart

### ColBERTv2

Late interaction retrieval using token-level embeddings with MaxSim scoring. Provides the highest retrieval quality at the cost of higher latency.

- **Scoring:** For each query token, finds the maximum cosine similarity across all document tokens, then sums across query tokens
- **Checkpoint:** `colbert-ir/colbertv2.0` (lazily loaded on first use)
- **Persistence:** In-memory only

!!! warning "Heavy dependencies"
    ColBERTv2 requires `colbert-ai` and `torch`, which are large packages. Install with:
    `uv sync --extra memory-colbert`

### BM25

Classic Okapi BM25 probabilistic ranking function using the `rank_bm25` library.

- **Tokenization:** Lowercase whitespace split
- **Index:** Rebuilt on every `store()` and `delete()` operation
- **Filtering:** Results are filtered to require at least one shared token with the query (handles edge cases where BM25 assigns IDF=0)
- **Persistence:** In-memory only

### Hybrid (RRF Fusion)

Combines a sparse retriever and a dense retriever using Reciprocal Rank Fusion:

$$\text{RRF}(d) = \sum_{i} \frac{w_i}{k + \text{rank}_i(d)}$$

- **Sub-backends:** Any two `MemoryBackend` implementations (e.g., SQLite + FAISS)
- **Over-fetch:** Retrieves `top_k * 3` results from each sub-backend for better fusion
- **Configurable:** RRF constant `k` (default 60) and per-backend weights

```python
from friday_ai.tools.storage.sqlite import SQLiteMemory
from friday_ai.tools.storage.faiss_backend import FAISSMemory
from friday_ai.tools.storage.hybrid import HybridMemory

hybrid = HybridMemory(
    sparse=SQLiteMemory(db_path="memory.db"),
    dense=FAISSMemory(),
    sparse_weight=1.0,
    dense_weight=1.5,  # Weight dense retrieval more heavily
)
```

!!! note "Backward compatibility"
    The old imports (e.g., `from friday_ai.memory.sqlite import SQLiteMemory`) still work via backward-compatibility shims in the `memory/` package, but the canonical location is now `friday_ai.tools.storage.*`.

---

## Chunking Pipeline

Large documents are split into manageable chunks before storage. The chunking pipeline is defined in `tools/storage/chunking.py` (previously `memory/chunking.py`).

### ChunkConfig

```python
@dataclass(slots=True)
class ChunkConfig:
    chunk_size: int = 512      # Maximum tokens per chunk (whitespace-split)
    chunk_overlap: int = 64    # Tokens to overlap between consecutive chunks
    min_chunk_size: int = 50   # Minimum tokens for a chunk to be kept
```

### Chunk

```python
@dataclass(slots=True)
class Chunk:
    content: str               # The chunk text
    source: str = ""           # Originating file path
    offset: int = 0            # Token offset within the original document
    index: int = 0             # Chunk index (0, 1, 2, ...)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Chunking Algorithm

The `chunk_text()` function splits text using paragraph boundaries:

1. Split the document on double newlines (`\n\n`) into paragraphs
2. Accumulate paragraphs into the current chunk until `chunk_size` is exceeded
3. When a chunk is full, flush it and keep the last `chunk_overlap` tokens as overlap for the next chunk
4. If a single paragraph exceeds `chunk_size`, split it into fixed-size windows with overlap
5. Discard chunks smaller than `min_chunk_size`

```python
from friday_ai.tools.storage.chunking import chunk_text, ChunkConfig

config = ChunkConfig(chunk_size=256, chunk_overlap=32)
chunks = chunk_text(document_text, source="docs/guide.md", config=config)
```

---

## Document Ingestion

The `tools/storage/ingest.py` module (previously `memory/ingest.py`) handles reading files and directories into chunks.

### File Type Detection

| Extension | Detected Type |
|-----------|--------------|
| `.md`, `.markdown`, `.mdx` | `markdown` |
| `.pdf` | `pdf` |
| `.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.yaml`, `.json`, `.html`, `.css`, ... | `code` |
| Everything else | `text` |

### `ingest_path(path, config=None)`

Ingests a file or directory into chunks:

- **Single file:** Reads the file, detects its type, and chunks the content
- **Directory:** Recursively walks the tree, skipping:
    - Hidden directories (starting with `.`)
    - Common non-content directories (`__pycache__`, `node_modules`, `.git`, `.venv`, etc.)
    - Binary files (images, audio, video, archives, compiled files)
    - Hidden files (starting with `.`)

```python
from pathlib import Path
from friday_ai.tools.storage.ingest import ingest_path

# Ingest a single file
chunks = ingest_path(Path("docs/guide.md"))

# Ingest an entire directory
chunks = ingest_path(Path("./docs/"))
```

### PDF Support

PDF files are read using `pdfplumber`, extracting text from each page and joining with double newlines. This requires the optional `pdfplumber` dependency:

```bash
uv sync --extra memory-pdf
```

---

## Embeddings

Dense retrieval backends (FAISS, ColBERT) require text embeddings. The `tools/storage/embeddings.py` module (previously `memory/embeddings.py`) provides the `Embedder` ABC and a default implementation.

### Embedder ABC

```python
class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> Any:
        """Embed texts and return a numpy array of shape (n, dim)."""

    @abstractmethod
    def dim(self) -> int:
        """Return the dimensionality of the embedding vectors."""
```

### SentenceTransformerEmbedder

The default embedder wraps the `sentence-transformers` library:

- **Default model:** `all-MiniLM-L6-v2` (384 dimensions, ~22 MB)
- **Output:** NumPy arrays of shape `(n, dim)`

```python
from friday_ai.tools.storage.embeddings import SentenceTransformerEmbedder

embedder = SentenceTransformerEmbedder(model_name="all-MiniLM-L6-v2")
vectors = embedder.embed(["Hello world", "How are you?"])
# Shape: (2, 384)
```

---

## Context Injection

The context injection pipeline retrieves relevant documents and prepends them to the prompt with source attribution. This is defined in `tools/storage/context.py` (previously `memory/context.py`).

### ContextConfig

```python
@dataclass(slots=True)
class ContextConfig:
    enabled: bool = True           # Whether context injection is active
    top_k: int = 5                 # Maximum results to retrieve
    min_score: float = 0.1         # Minimum relevance score threshold
    max_context_tokens: int = 2048 # Maximum tokens of context to inject
```

### `inject_context()`

The main function for context injection:

```python
def inject_context(
    query: str,
    messages: List[Message],
    backend: MemoryBackend,
    *,
    config: Optional[ContextConfig] = None,
) -> List[Message]:
```

How it works:

1. Retrieves results from the memory backend using the query
2. Filters results below `min_score`
3. Truncates to `max_context_tokens` (approximate token count via whitespace split)
4. Formats results with source attribution tags: `[Source: docs/guide.md] The content...`
5. Creates a system message with the formatted context
6. Returns a **new** message list with the context message prepended

```python
from friday_ai.tools.storage.context import inject_context, ContextConfig

config = ContextConfig(top_k=3, min_score=0.2)
messages = inject_context("What is the API?", messages, backend, config=config)
```

### Source Attribution

Context is injected as a system message with clear source tags:

```
The following context was retrieved from the knowledge base. Use it to
inform your response, citing sources where applicable:

[Source: docs/api.md] The API exposes a /v1/chat/completions endpoint...

[Source: docs/setup.md] To configure the API server, edit config.toml...
```

---

## Backend Registration

Memory backends are registered via the `@MemoryRegistry.register("name")` decorator:

```python
from friday_ai.core.registry import MemoryRegistry
from friday_ai.tools.storage._stubs import MemoryBackend

@MemoryRegistry.register("my-backend")
class MyMemoryBackend(MemoryBackend):
    backend_id = "my-backend"

    def store(self, content, *, source="", metadata=None) -> str: ...
    def retrieve(self, query, *, top_k=5, **kwargs) -> list: ...
    def delete(self, doc_id) -> bool: ...
    def clear(self) -> None: ...
```

The default backend is configured in `~/.friday_ai/config.toml`. Storage settings live under `[tools.storage]`, and context injection is controlled by `agent.context_from_memory`:

```toml
[agent]
context_from_memory = true

[tools.storage]
default_backend = "sqlite"
db_path = "~/.friday_ai/memory.db"
context_top_k = 5
context_min_score = 0.1
context_max_tokens = 2048
chunk_size = 512
chunk_overlap = 64
```

!!! note "Backward compatibility"
    The `[memory]` TOML section is still accepted as a backward-compatible alias for `[tools.storage]`. The old `context_injection` field is automatically migrated to `agent.context_from_memory` at load time.
