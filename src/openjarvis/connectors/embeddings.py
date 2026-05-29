"""Dense embedding clients for the IngestionPipeline.

A thin HTTP wrapper around a local `Ollama <https://ollama.com>`_ daemon
running an embedding model (default ``nomic-embed-text``, 768-dim). Embeddings
are serialised as float32 ``bytes`` for storage in the ``embedding`` BLOB
column of ``knowledge_chunks``.

The client degrades gracefully when the daemon is unreachable: ``embed``
returns ``None`` and ``is_available()`` reports ``False`` instead of raising,
so ingestion never fails because a sidecar service is down.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

import requests

# numpy is imported lazily inside the functions that use it (not at module
# load). The CLI imports this module eagerly via the deep-research command
# chain, so a module-level `import numpy` makes a broken/slow numpy on Windows
# crash every `jarvis` command — including `jarvis serve` (#404, #309).
if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"


class OllamaEmbedder:
    """Embed text via a local Ollama daemon.

    Parameters
    ----------
    model:
        Ollama model tag (e.g. ``nomic-embed-text``, ``mxbai-embed-large``).
    host:
        Base URL for the Ollama HTTP API. Defaults to ``http://localhost:11434``.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_EMBED_MODEL,
        host: str = DEFAULT_OLLAMA_HOST,
        timeout: float = 30.0,
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._dim: Optional[int] = None

    # ------------------------------------------------------------------
    # Identity / capability checks
    # ------------------------------------------------------------------

    @property
    def model_version(self) -> str:
        """Stable identifier persisted alongside each embedding row."""
        return f"ollama:{self._model}"

    @property
    def dim(self) -> Optional[int]:
        """Embedding dimensionality, learned after the first successful call."""
        return self._dim

    def is_available(self) -> bool:
        """Return True iff the daemon answers and the model is installed."""
        try:
            resp = requests.get(f"{self._host}/api/tags", timeout=2.0)
            resp.raise_for_status()
        except requests.RequestException:
            return False

        try:
            names = {m.get("name", "") for m in resp.json().get("models", [])}
        except ValueError:
            return False

        # Ollama tags include the ":latest" suffix; match either form.
        return self._model in names or f"{self._model}:latest" in names

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed(self, text: str) -> Optional[bytes]:
        """Embed a single string. Returns float32 bytes or ``None`` on failure."""
        if not text or not text.strip():
            return None
        try:
            resp = requests.post(
                f"{self._host}/api/embeddings",
                json={"model": self._model, "prompt": text},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            logger.warning("OllamaEmbedder.embed: request failed (%s)", exc)
            return None
        except ValueError as exc:
            logger.warning("OllamaEmbedder.embed: bad JSON (%s)", exc)
            return None

        vec = payload.get("embedding")
        if not vec:
            logger.warning(
                "OllamaEmbedder.embed: empty embedding for %d chars", len(text)
            )
            return None

        import numpy as np

        arr = np.asarray(vec, dtype=np.float32)
        if self._dim is None:
            self._dim = int(arr.shape[0])
        elif arr.shape[0] != self._dim:
            logger.warning(
                "OllamaEmbedder.embed: dim drift (expected %d, got %d)",
                self._dim, arr.shape[0],
            )
            return None
        return arr.tobytes()

    def embed_batch(self, texts: List[str]) -> List[Optional[bytes]]:
        """Embed a list of strings sequentially.

        Ollama's HTTP API serves one prompt per call; on the same host the
        round-trip overhead is negligible relative to model inference.
        """
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Deserialisation helper (used by verification + future retrieval code)
# ---------------------------------------------------------------------------


def decode_embedding(
    blob: Optional[bytes], *, dtype=None
) -> Optional[np.ndarray]:
    """Reconstruct a 1-D vector from a BLOB written by ``OllamaEmbedder.embed``.

    Returns ``None`` when the input is missing or zero-length so callers can
    treat absent embeddings uniformly. ``dtype`` defaults to ``np.float32``
    (resolved lazily; passing ``np.float32`` as a default arg would import
    numpy at module load).
    """
    if not blob:
        return None
    import numpy as np

    return np.frombuffer(blob, dtype=dtype if dtype is not None else np.float32)


__all__ = [
    "OllamaEmbedder",
    "decode_embedding",
    "DEFAULT_EMBED_MODEL",
    "DEFAULT_OLLAMA_HOST",
]
