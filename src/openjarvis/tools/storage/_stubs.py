"""ABC for memory / retrieval backends.

Phase 2 will provide concrete implementations (SQLite/FTS5, FAISS,
ColBERTv2, BM25, Hybrid).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Actionable message surfaced whenever a Rust-backed memory backend cannot be
#: constructed because the mandatory ``openjarvis_rust`` extension is missing
#: from the *current* venv. Kept as a single constant so the server routes, the
#: SDK and the regression tests all surface exactly the same wording.
RUST_MISSING_HINT = (
    "Memory backend unavailable: the native `openjarvis_rust` extension is not "
    "installed in this environment. Build it into the venv that runs the server "
    "with `uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml` "
    "(needs rustc >= 1.88), then restart. Verify with "
    '`python -c "from openjarvis._rust_bridge import RUST_AVAILABLE; '
    'print(RUST_AVAILABLE)"`.'
)


class MemoryBackendUnavailable(RuntimeError):
    """Raised when a memory backend cannot be built because the mandatory
    ``openjarvis_rust`` extension is missing from the current environment.

    This is deliberately distinct from "memory is intentionally disabled": a
    missing native extension is an environment/install error that must be
    surfaced loudly and actionably, never swallowed into a silent no-op.
    """

    def __init__(self, message: str = RUST_MISSING_HINT) -> None:
        super().__init__(message)


@dataclass(slots=True)
class RetrievalResult:
    """A single result returned by a memory backend query."""

    content: str
    score: float = 0.0
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryBackend(ABC):
    """Base class for all memory / retrieval backends.

    Subclasses must be registered via
    ``@MemoryRegistry.register("name")`` to become discoverable.
    """

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
        """Delete a document by id. Return ``True`` if it existed."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all stored documents."""


__all__ = [
    "RUST_MISSING_HINT",
    "MemoryBackend",
    "MemoryBackendUnavailable",
    "RetrievalResult",
]
