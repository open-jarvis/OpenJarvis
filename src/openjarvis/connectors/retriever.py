"""TwoStageRetriever — BM25 recall from KnowledgeStore + optional reranking.

Composes a fast BM25 first-stage recall (via ``KnowledgeStore``) with an
optional second-stage ``Reranker`` for semantic reordering.  The default
``ColBERTReranker`` lazy-loads a ColBERT checkpoint and scores candidates via
MaxSim; it degrades gracefully when ``colbert-ai`` is not installed.

Typical usage::

    store = KnowledgeStore()
    retriever = TwoStageRetriever(store, reranker=ColBERTReranker())
    results = retriever.retrieve("neural networks", top_k=10)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.tools.storage._stubs import RetrievalResult

if TYPE_CHECKING:
    from openjarvis.connectors.embedding_store import EmbeddingStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Abstract Reranker
# ---------------------------------------------------------------------------


class Reranker(ABC):
    """Abstract base class for second-stage semantic rerankers."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        *,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """Rerank *candidates* for *query* and return the top *top_k* results.

        Parameters
        ----------
        query:
            The original search query.
        candidates:
            List of ``RetrievalResult`` objects from the BM25 recall stage.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        List[RetrievalResult]
            Reranked results, truncated to *top_k*.
        """


# ---------------------------------------------------------------------------
# ColBERT reranker
# ---------------------------------------------------------------------------


class ColBERTReranker(Reranker):
    """Semantic reranker backed by ColBERT MaxSim scoring.

    Lazy-loads a ColBERT checkpoint on first use.  If the ``colbert-ai``
    package is not installed the reranker falls back to returning the
    BM25-ordered candidates unchanged (with a warning logged once).

    Parameters
    ----------
    checkpoint:
        Path or HuggingFace model ID for the ColBERT checkpoint.
        Defaults to ``"colbert-ir/colbertv2.0"``.
    embedding_store:
        Optional :class:`EmbeddingStore` for caching per-chunk ColBERT
        token embeddings on disk.  When provided, the reranker looks up
        pre-computed embeddings before falling back to ``docFromText()``,
        and stores newly computed embeddings for future reuse.
    """

    def __init__(
        self,
        checkpoint: str = "colbert-ir/colbertv2.0",
        embedding_store: Optional["EmbeddingStore"] = None,
    ) -> None:
        self._checkpoint = checkpoint
        self._model = None
        self._warned = False
        self._embedding_store = embedding_store

    def _load_model(self) -> bool:
        """Attempt to load the ColBERT model.  Returns True on success."""
        if self._model is not None:
            return True
        try:
            import os

            from colbert.infra.config import ColBERTConfig  # type: ignore[import]
            from colbert.modeling.checkpoint import Checkpoint  # type: ignore[import]

            # Force CPU if CUDA unavailable
            gpus = 0
            try:
                import torch  # type: ignore[import]

                if torch.cuda.is_available():
                    gpus = 1
            except Exception:
                pass

            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
            config = ColBERTConfig(gpus=gpus)
            self._model = Checkpoint(self._checkpoint, colbert_config=config)
            return True
        except Exception as exc:
            if not self._warned:
                logger.warning(
                    "ColBERTReranker: failed to load colbert-ai (%s). "
                    "Falling back to BM25 order.",
                    exc,
                )
                self._warned = True
            return False

    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        *,
        top_k: int = 10,
    ) -> List[RetrievalResult]:
        """Rerank *candidates* using ColBERT MaxSim scores.

        Falls back to BM25 order if ``colbert-ai`` is unavailable.
        """
        if not candidates:
            return []

        if not self._load_model():
            # Graceful degradation: return BM25 order
            return candidates[:top_k]

        try:
            import torch  # type: ignore[import]

            # Encode query: (Q, dim) where Q=query_maxlen (32)
            q_emb = self._model.queryFromText([query])[0]

            # Score each candidate via MaxSim, using cached embeddings
            # from the EmbeddingStore when available.
            scores = []
            for r in candidates:
                chunk_id = r.metadata.get("chunk_id", "")

                # Try cached embedding first
                d_emb = None
                if self._embedding_store and chunk_id:
                    d_emb = self._embedding_store.get(chunk_id)

                if d_emb is None:
                    # Encode on the fly
                    d_emb = self._model.docFromText([r.content], bsize=1)[0]
                    # d_emb shape: (1, T, dim) or (T, dim)
                    if d_emb.dim() == 3:
                        d_emb = d_emb.squeeze(0)
                    # Cache for future queries
                    if self._embedding_store and chunk_id:
                        self._embedding_store.store(chunk_id, d_emb)

                sim = torch.nn.functional.cosine_similarity(
                    q_emb.unsqueeze(1), d_emb.unsqueeze(0), dim=2
                )
                maxsim = sim.max(dim=1).values.sum().item()
                scores.append(maxsim)

            ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
            reranked = []
            for score, result in ranked[:top_k]:
                reranked.append(
                    RetrievalResult(
                        content=result.content,
                        score=float(score),
                        source=result.source,
                        metadata=result.metadata,
                    )
                )
            return reranked

        except Exception as exc:
            logger.warning("ColBERTReranker.rerank failed (%s); using BM25 order.", exc)
            return candidates[:top_k]


# ---------------------------------------------------------------------------
# TwoStageRetriever
# ---------------------------------------------------------------------------


class TwoStageRetriever:
    """BM25 recall + optional semantic reranking for Deep Research.

    Stage 1 retrieves ``max(recall_k, top_k * 3)`` candidates from the
    ``KnowledgeStore`` using FTS5/BM25.  Stage 2 optionally passes those
    candidates through a ``Reranker`` to produce a semantically ordered
    final list of ``top_k`` results.

    Parameters
    ----------
    store:
        The ``KnowledgeStore`` to query in Stage 1.
    reranker:
        An optional ``Reranker`` for Stage 2.  When *None* the retriever
        returns BM25-ordered results directly.
    recall_k:
        Number of candidates to fetch in Stage 1.  The actual recall
        size is ``max(recall_k, top_k * 3)`` so that the reranker always
        has a meaningful pool to work with.
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
        """Run the two-stage retrieval pipeline.

        Parameters
        ----------
        query:
            Full-text search query.
        top_k:
            Maximum number of results to return.
        source:
            Restrict to chunks from this source (e.g. ``"gmail"``).
        doc_type:
            Restrict to chunks of this doc type (e.g. ``"email"``).
        author:
            Restrict to chunks authored by this person.
        since:
            Exclude chunks whose timestamp is earlier than this ISO string.
        until:
            Exclude chunks whose timestamp is later than this ISO string.

        Returns
        -------
        List[RetrievalResult]
            Up to *top_k* results, reranked when a reranker is configured.
        """
        # Determine Stage-1 recall size
        stage1_k = max(self._recall_k, top_k * 3)

        # Build optional filter kwargs (only pass non-empty values)
        filter_kwargs = {}
        if source:
            filter_kwargs["source"] = source
        if doc_type:
            filter_kwargs["doc_type"] = doc_type
        if author:
            filter_kwargs["author"] = author
        if since:
            filter_kwargs["since"] = since
        if until:
            filter_kwargs["until"] = until

        # Stage 1: BM25 recall
        candidates = self._store.retrieve(query, top_k=stage1_k, **filter_kwargs)

        if not candidates:
            return []

        # Stage 2: optional reranking
        if self._reranker is not None and len(candidates) > top_k:
            return self._reranker.rerank(query, candidates, top_k=top_k)

        return candidates[:top_k]


__all__ = ["ColBERTReranker", "Reranker", "TwoStageRetriever"]
