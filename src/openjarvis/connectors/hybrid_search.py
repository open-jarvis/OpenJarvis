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
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

# numpy imported lazily inside _vector_recall (see embeddings.py) so importing
# this module never forces numpy at load time (#404, #309).
from openjarvis.connectors.embeddings import OllamaEmbedder, decode_embedding
from openjarvis.connectors.store import KnowledgeStore

logger = logging.getLogger(__name__)


_UPCOMING_TERMS = {
    "next",
    "upcoming",
    "future",
    "forthcoming",
    "coming",
    "soon",
}
_CALENDAR_TERMS = {
    "calendar",
    "calendars",
    "event",
    "events",
}
_CALENDAR_REQUEST_TERMS = _CALENDAR_TERMS | {
    "appointment",
    "appointments",
    "meeting",
    "meetings",
    "schedule",
}
_GCALENDAR_GENERIC_TERMS = _UPCOMING_TERMS | _CALENDAR_TERMS | {
    "appointment",
    "appointments",
    "meeting",
    "meetings",
    "schedule",
}
_QUERY_STOPWORDS = {
    "a",
    "all",
    "am",
    "are",
    "do",
    "for",
    "have",
    "i",
    "in",
    "is",
    "list",
    "me",
    "my",
    "on",
    "s",
    "show",
    "tell",
    "the",
    "there",
    "to",
    "what",
    "whats",
    "when",
}


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


def _query_tokens(query: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", query.lower()))


def _sources_include_gcalendar(sources: Optional[Sequence[str]]) -> bool:
    return any(str(source).lower() == "gcalendar" for source in sources or [])


def _has_upcoming_calendar_intent(
    query: str,
    sources: Optional[Sequence[str]],
) -> bool:
    tokens = _query_tokens(query)
    if not tokens or not (tokens & _UPCOMING_TERMS):
        return False
    if _sources_include_gcalendar(sources):
        return True
    if sources:
        return False
    return bool(tokens & _CALENDAR_REQUEST_TERMS)


def _is_generic_calendar_timeline_query(query: str) -> bool:
    tokens = _query_tokens(query)
    if not tokens:
        return True
    topic_tokens = tokens - _GCALENDAR_GENERIC_TERMS - _QUERY_STOPWORDS
    return not topic_tokens


def _start_is_nowish_or_future(start: Optional[datetime]) -> bool:
    if start is None:
        return False
    now = datetime.now(tz=start.tzinfo) if start.tzinfo else datetime.now()
    return start >= now - timedelta(days=1)


def _start_of_day(ts: datetime) -> datetime:
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def _as_utc(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _parse_timestamp_for_timeline(
    raw: Any,
) -> Tuple[Optional[datetime], Optional[date]]:
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    is_naive_midnight = (
        parsed.tzinfo is None
        and parsed.hour == 0
        and parsed.minute == 0
        and parsed.second == 0
        and parsed.microsecond == 0
    )
    return _as_utc(parsed), parsed.date() if is_naive_midnight else None


def _timestamp_in_range(
    timestamp: Optional[datetime],
    time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]],
    *,
    all_day_date: Optional[date] = None,
) -> bool:
    if timestamp is None or time_range is None:
        return timestamp is not None
    start, end = time_range
    if all_day_date is not None:
        if start is not None and all_day_date < start.date():
            return False
        if end is not None and all_day_date > end.date():
            return False
        return True
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    if start_utc is not None and timestamp < start_utc:
        return False
    if end_utc is not None and timestamp > end_utc:
        return False
    return True


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
        import numpy as np

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

    def _normalise_calendar_timeline_scope(
        self,
        query: str,
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]],
        sources: Optional[Sequence[str]],
    ) -> Tuple[
        Optional[Tuple[Optional[datetime], Optional[datetime]]],
        Optional[Sequence[str]],
        bool,
        bool,
    ]:
        """Fill in structured filters for generic upcoming-calendar requests.

        Queries like "what are my next calendar events?" often have no useful
        lexical terms in the stored event text, so BM25/vector ranking can miss
        nearby events. Treat that shape as a source-filtered timeline request.
        """
        scoped_sources = list(sources) if sources else None
        has_upcoming_intent = _has_upcoming_calendar_intent(query, scoped_sources)

        if has_upcoming_intent and (
            scoped_sources is None or _sources_include_gcalendar(scoped_sources)
        ):
            scoped_sources = ["gcalendar"]

        if not _sources_include_gcalendar(scoped_sources):
            return time_range, scoped_sources, False, False

        if has_upcoming_intent:
            if time_range is None:
                time_range = (_start_of_day(datetime.now(timezone.utc)), None)
            else:
                start, end = time_range
                if start is None:
                    time_range = (_start_of_day(datetime.now(timezone.utc)), end)
                else:
                    time_range = (_start_of_day(start), end)

        chronological = has_upcoming_intent or (
            time_range is not None
            and time_range[1] is None
            and _start_is_nowish_or_future(time_range[0])
        )
        metadata_only = chronological and _is_generic_calendar_timeline_query(query)
        return time_range, scoped_sources, chronological, metadata_only

    def _calendar_timeline_ids(
        self,
        *,
        person: Optional[str],
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]],
        sources: Optional[Sequence[str]],
        limit: int,
    ) -> List[str]:
        """Return gcalendar rows sorted by normalized event start time."""
        filter_sql, filter_params = self._build_filters(
            person=person,
            time_range=None,
            sources=sources,
        )
        rows = self._store._conn.execute(
            f"""
            SELECT id, timestamp, created_at
            FROM knowledge_chunks
            WHERE {filter_sql}
            """,
            filter_params,
        ).fetchall()

        candidates: List[Tuple[str, datetime, float]] = []
        for row in rows:
            timestamp, all_day_date = _parse_timestamp_for_timeline(row["timestamp"])
            if not _timestamp_in_range(
                timestamp,
                time_range,
                all_day_date=all_day_date,
            ):
                continue
            candidates.append(
                (
                    row["id"],
                    timestamp or datetime.max.replace(tzinfo=timezone.utc),
                    float(row["created_at"] or 0.0),
                )
            )

        candidates.sort(key=lambda item: (item[1], item[2]))
        return [chunk_id for chunk_id, *_ in candidates[:limit]]

    def _filter_calendar_timeline_fused(
        self,
        fused: List[Tuple[str, float, float, float]],
        time_range: Optional[Tuple[Optional[datetime], Optional[datetime]]],
    ) -> List[Tuple[str, float, float, float]]:
        """Apply normalized timestamp filtering to ranked calendar candidates."""
        if not fused:
            return fused
        ids = [chunk_id for chunk_id, *_ in fused]
        placeholders = ",".join("?" for _ in ids)
        rows = self._store._conn.execute(
            f"""
            SELECT id, timestamp
            FROM knowledge_chunks
            WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        timestamps = {
            row["id"]: _parse_timestamp_for_timeline(row["timestamp"])
            for row in rows
        }

        def _keeps_item(item: Tuple[str, float, float, float]) -> bool:
            timestamp, all_day_date = timestamps.get(item[0], (None, None))
            return _timestamp_in_range(
                timestamp,
                time_range,
                all_day_date=all_day_date,
            )

        return [item for item in fused if _keeps_item(item)]

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
        structured filter is applied directly. Upcoming calendar timelines are
        returned nearest-first; other fallbacks return the most recent rows.
        """
        time_range, sources, chronological_order, metadata_only = (
            self._normalise_calendar_timeline_scope(query, time_range, sources)
        )
        rank_query = "" if metadata_only else query
        calendar_timeline = chronological_order and _sources_include_gcalendar(sources)
        recall_time_range = None if calendar_timeline else time_range

        bm25_filter_sql, bm25_filter_params = self._build_filters(
            person=person, time_range=recall_time_range, sources=sources, alias="kc"
        )
        unaliased_filter_sql, unaliased_filter_params = self._build_filters(
            person=person, time_range=recall_time_range, sources=sources
        )

        bm25 = (
            self._bm25_recall(rank_query, bm25_filter_sql, bm25_filter_params)
            if rank_query.strip()
            else []
        )
        vector = (
            self._vector_recall(
                rank_query,
                unaliased_filter_sql,
                unaliased_filter_params,
            )
            if rank_query.strip()
            else []
        )
        fused = self._fuse(bm25, vector)
        if calendar_timeline:
            fused = self._filter_calendar_timeline_fused(fused, time_range)

        # Metadata-only fallback: empty query, or both legs produced nothing
        # despite a non-empty query. Calendar timeline requests use start-time
        # ascending; other searches use recency so the agent still gets a
        # useful corpus snapshot.
        if not fused:
            if calendar_timeline:
                chunk_ids = self._calendar_timeline_ids(
                    person=person,
                    time_range=time_range,
                    sources=sources,
                    limit=limit,
                )
                fused = [(chunk_id, 0.0, 0.0, 0.0) for chunk_id in chunk_ids]
            else:
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
