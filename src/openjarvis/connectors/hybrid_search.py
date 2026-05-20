"""Hybrid retrieval over the KnowledgeStore: metadata filter + BM25 + vector cosine.

A single ``search`` entrypoint that the agentic research loop calls as a tool.
Structured WHERE-clause filters (person, time range, sources) narrow the
candidate set, then BM25 (FTS5) and dense cosine similarity score the
survivors. The two ranks are fused with Reciprocal Rank Fusion, which is
robust to the very different score scales the two signals produce
(BM25 ~ [0, 20], cosine ~ [0.4, 0.9] for nomic-embed-text).

Each result is enriched with its thread context: when a hit belongs to a
``thread_id``, the surrounding chunks are attached so the synthesis model
sees the conversation, not an isolated fragment.

Brute-force vector scan is fine at the current corpus size (~5k chunks ×
768 dims fits in ~15 MB and matmuls in <50 ms). Swap in an ANN index when
that stops being true.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from openjarvis.connectors.embeddings import OllamaEmbedder, decode_embedding
from openjarvis.connectors.store import KnowledgeStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SearchHit:
    """A single hybrid-search result with enough context for citation."""

    chunk_id: str
    document_id: str
    chunk_idx: int
    title: str
    content_snippet: str
    source: str
    timestamp: str
    participants: List[str]
    score: float
    bm25_score: float
    vector_score: float
    thread_id: str = ""
    thread_context: List[Dict[str, Any]] = field(default_factory=list)
    # ``url`` is the connector-provided deep-link, persisted on
    # ``knowledge_chunks.url``. Empty when the source didn't supply one — in
    # that case callers may fall back to a doc_id-based reconstruction (Slack,
    # Gmail), or render the citation as non-clickable.
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content_snippet": self.content_snippet,
            "source": self.source,
            "timestamp": self.timestamp,
            "participants": self.participants,
            "score": round(self.score, 4),
            "document_id": self.document_id,
            "chunk_idx": self.chunk_idx,
            "thread_id": self.thread_id,
            "thread_context": self.thread_context,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: Optional[datetime | str]) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def _quote_fts(query: str) -> str:
    """Make a plain user query safe for FTS5 MATCH.

    FTS5 treats characters like ``-``, ``:``, ``"`` as operators; the simplest
    way to avoid syntax errors on arbitrary user input is to quote each
    whitespace-delimited token and OR them together.
    """
    tokens = [t for t in query.split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


def _parse_participants(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _snippet(content: str, max_chars: int = 500) -> str:
    flat = content.strip()
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars].rstrip() + "…"


# ---------------------------------------------------------------------------
# HybridSearch
# ---------------------------------------------------------------------------


class HybridSearch:
    """Hybrid BM25 + dense-cosine retrieval over a ``KnowledgeStore``.

    Parameters
    ----------
    store:
        The store to query.
    embedder:
        Embedding client used to encode the query. When ``None``, search
        falls back to BM25 only and reports ``vector_score=0``.
    bm25_weight, vector_weight:
        Weights on the two RRF terms. Defaults to 0.5 / 0.5; raise either to
        bias retrieval toward lexical or semantic matches.
    rrf_k:
        RRF damping constant. Larger values flatten the contribution of
        deeper ranks; 60 is the canonical value from the original paper.
    recall_k:
        How deep each individual ranker recalls before fusion. Should be at
        least a few times ``limit`` so the fuser has overlap to work with.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        embedder: Optional[OllamaEmbedder] = None,
        *,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
        recall_k: int = 200,
        thread_context_cap: int = 20,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._bm25_weight = float(bm25_weight)
        self._vector_weight = float(vector_weight)
        self._rrf_k = int(rrf_k)
        self._recall_k = int(recall_k)
        self._thread_context_cap = int(thread_context_cap)

    # ------------------------------------------------------------------
    # Filter SQL construction
    # ------------------------------------------------------------------

    def _build_filters(
        self,
        *,
        person: Optional[str],
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]],
        sources: Optional[Sequence[str]],
        alias: str = "",
    ) -> Tuple[str, List[Any]]:
        """Return ``(where_fragment, params)`` for the structured filters.

        ``person`` is matched against the participants_raw JSON via LIKE so a
        substring of a name or email address is enough — handy when the user
        says "Kelly" rather than "kelly@example.com".

        ``alias`` qualifies every column reference (e.g. ``kc.`` when joining
        against the FTS virtual table which also has ``author`` and ``title``
        columns and would otherwise produce an "ambiguous column" error).
        """
        prefix = f"{alias}." if alias else ""
        clauses: List[str] = [f"{prefix}deleted_at IS NULL"]
        params: List[Any] = []

        if person:
            clauses.append(
                f"({prefix}participants_raw LIKE ? OR {prefix}participants LIKE ? "
                f"OR {prefix}author LIKE ?)"
            )
            needle = f"%{person}%"
            params.extend([needle, needle, needle])

        if time_range:
            start, end = time_range
            if start is not None:
                clauses.append(f"{prefix}timestamp >= ?")
                params.append(_iso(start))
            if end is not None:
                clauses.append(f"{prefix}timestamp <= ?")
                params.append(_iso(end))

        if sources:
            placeholders = ",".join("?" for _ in sources)
            clauses.append(f"{prefix}source IN ({placeholders})")
            params.extend(sources)

        return " AND ".join(clauses), params

    # ------------------------------------------------------------------
    # BM25 leg
    # ------------------------------------------------------------------

    def _bm25_recall(
        self, query: str, filter_sql: str, filter_params: List[Any]
    ) -> List[Tuple[str, float]]:
        """Return ``[(chunk_id, bm25_score), ...]`` from FTS5."""
        fts_query = _quote_fts(query)
        if not fts_query:
            return []
        sql = f"""
            SELECT kc.id, abs(bm25(knowledge_fts)) AS score
            FROM knowledge_fts
            JOIN knowledge_chunks kc ON knowledge_fts.rowid = kc.rowid
            WHERE knowledge_fts MATCH ?
              AND {filter_sql}
            ORDER BY score DESC
            LIMIT ?
        """
        try:
            rows = self._store._conn.execute(
                sql, [fts_query, *filter_params, self._recall_k]
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("hybrid_search: BM25 leg failed (%s)", exc)
            return []
        return [(row["id"], float(row["score"])) for row in rows]

    # ------------------------------------------------------------------
    # Vector leg
    # ------------------------------------------------------------------

    def _vector_recall(
        self, query: str, filter_sql: str, filter_params: List[Any]
    ) -> List[Tuple[str, float]]:
        """Return ``[(chunk_id, cosine_score), ...]`` from a brute-force scan."""
        if self._embedder is None:
            return []
        q_blob = self._embedder.embed(query)
        q_vec = decode_embedding(q_blob)
        if q_vec is None or q_vec.size == 0:
            return []
        q_norm = float(np.linalg.norm(q_vec))
        if q_norm == 0.0:
            return []
        q_unit = q_vec / q_norm

        sql = f"""
            SELECT id, embedding
            FROM knowledge_chunks
            WHERE embedding IS NOT NULL AND {filter_sql}
        """
        rows = self._store._conn.execute(sql, filter_params).fetchall()
        if not rows:
            return []

        ids: List[str] = []
        vecs: List[np.ndarray] = []
        for row in rows:
            vec = decode_embedding(row["embedding"])
            if vec is None or vec.size != q_unit.size:
                continue
            ids.append(row["id"])
            vecs.append(vec)
        if not ids:
            return []

        mat = np.vstack(vecs).astype(np.float32, copy=False)
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0.0] = 1.0
        mat = mat / norms[:, None]
        scores = mat @ q_unit
        # Top-recall_k
        if len(scores) > self._recall_k:
            top_idx = np.argpartition(-scores, self._recall_k)[: self._recall_k]
            top_idx = top_idx[np.argsort(-scores[top_idx])]
        else:
            top_idx = np.argsort(-scores)
        return [(ids[int(i)], float(scores[int(i)])) for i in top_idx]

    # ------------------------------------------------------------------
    # Fusion
    # ------------------------------------------------------------------

    def _fuse(
        self,
        bm25: List[Tuple[str, float]],
        vector: List[Tuple[str, float]],
    ) -> List[Tuple[str, float, float, float]]:
        """Reciprocal Rank Fusion across the two rankers.

        Returns ``[(chunk_id, fused, bm25_score, vector_score), ...]``
        sorted by ``fused`` descending.
        """
        bm25_rank = {cid: i + 1 for i, (cid, _) in enumerate(bm25)}
        vec_rank = {cid: i + 1 for i, (cid, _) in enumerate(vector)}
        bm25_scores = {cid: s for cid, s in bm25}
        vec_scores = {cid: s for cid, s in vector}

        candidates = set(bm25_rank) | set(vec_rank)
        out: List[Tuple[str, float, float, float]] = []
        for cid in candidates:
            fused = 0.0
            if cid in bm25_rank:
                fused += self._bm25_weight / (self._rrf_k + bm25_rank[cid])
            if cid in vec_rank:
                fused += self._vector_weight / (self._rrf_k + vec_rank[cid])
            out.append(
                (cid, fused, bm25_scores.get(cid, 0.0), vec_scores.get(cid, 0.0))
            )
        out.sort(key=lambda r: -r[1])
        return out

    # ------------------------------------------------------------------
    # Thread enrichment
    # ------------------------------------------------------------------

    def _thread_context(
        self, thread_id: str, anchor_chunk_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch sibling chunks for ``thread_id`` (capped at ``thread_context_cap``).

        When the thread is longer than the cap, return a centred window around
        the anchor so the most relevant chunk is always present.
        """
        if not thread_id:
            return []
        rows = self._store._conn.execute(
            """
            SELECT id, chunk_index, content, timestamp, author
            FROM knowledge_chunks
            WHERE thread_id = ? AND deleted_at IS NULL
            ORDER BY timestamp ASC, chunk_index ASC
            """,
            (thread_id,),
        ).fetchall()
        if not rows:
            return []
        cap = self._thread_context_cap
        if len(rows) > cap:
            anchor_idx = next(
                (i for i, r in enumerate(rows) if r["id"] == anchor_chunk_id),
                len(rows) // 2,
            )
            half = cap // 2
            lo = max(0, anchor_idx - half)
            hi = min(len(rows), lo + cap)
            lo = max(0, hi - cap)
            rows = rows[lo:hi]
        return [
            {
                "chunk_idx": int(r["chunk_index"]),
                "timestamp": r["timestamp"] or "",
                "author": r["author"] or "",
                "snippet": _snippet(r["content"], 240),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        person: Optional[str] = None,
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]] = None,
        sources: Optional[Sequence[str]] = None,
        limit: int = 20,
    ) -> List[SearchHit]:
        """Run the hybrid pipeline and return up to ``limit`` hits.

        See module docstring for ranking semantics. ``query`` may be empty
        when callers want a pure metadata filter (e.g. "all mail from X in
        May") — in that case only the vector leg runs (and only if an
        embedder is configured); if neither leg yields anything the
        structured filter is applied directly and the most recent rows are
        returned.
        """
        bm25_filter_sql, bm25_filter_params = self._build_filters(
            person=person, time_range=time_range, sources=sources, alias="kc"
        )
        unaliased_filter_sql, unaliased_filter_params = self._build_filters(
            person=person, time_range=time_range, sources=sources
        )

        bm25 = (
            self._bm25_recall(query, bm25_filter_sql, bm25_filter_params)
            if query.strip()
            else []
        )
        vector = (
            self._vector_recall(query, unaliased_filter_sql, unaliased_filter_params)
            if query.strip()
            else []
        )
        fused = self._fuse(bm25, vector)

        # Metadata-only fallback: empty query, or both legs produced nothing
        # despite a non-empty query. Return the most recent rows matching the
        # filter so the agent still gets a useful corpus snapshot.
        if not fused:
            sql = f"""
                SELECT id FROM knowledge_chunks
                WHERE {unaliased_filter_sql}
                ORDER BY timestamp DESC, created_at DESC
                LIMIT ?
            """
            rows = self._store._conn.execute(
                sql, [*unaliased_filter_params, limit]
            ).fetchall()
            fused = [(row["id"], 0.0, 0.0, 0.0) for row in rows]

        # Materialise the top-N rows in one IN-clause round trip.
        top = fused[:limit]
        if not top:
            return []
        ids = [cid for cid, *_ in top]
        placeholders = ",".join("?" for _ in ids)
        meta_rows = self._store._conn.execute(
            f"""
            SELECT id, doc_id, content, source, title, author, participants,
                   timestamp, thread_id, chunk_index, url
            FROM knowledge_chunks
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        by_id = {r["id"]: r for r in meta_rows}

        hits: List[SearchHit] = []
        for chunk_id, fused_score, bm25_score, vec_score in top:
            r = by_id.get(chunk_id)
            if r is None:
                continue
            hits.append(
                SearchHit(
                    chunk_id=chunk_id,
                    document_id=r["doc_id"],
                    chunk_idx=int(r["chunk_index"]),
                    title=r["title"] or "",
                    content_snippet=_snippet(r["content"]),
                    source=r["source"] or "",
                    timestamp=r["timestamp"] or "",
                    participants=_parse_participants(r["participants"]),
                    score=fused_score,
                    bm25_score=bm25_score,
                    vector_score=vec_score,
                    thread_id=r["thread_id"] or "",
                    thread_context=self._thread_context(r["thread_id"] or "", chunk_id),
                    url=r["url"] or "",
                )
            )
        return hits


__all__ = ["HybridSearch", "SearchHit"]
