"""Evidence-bound FTS5/BM25 retrieval for Markdown vault memory."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import (
    SOURCE_PRIORITY,
    ConflictState,
    EvidenceStatus,
    MemoryRetrievalResult,
    MemorySource,
    RetrievalCandidate,
)

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_MAX_CANDIDATES = 100
_MAX_SPAN_CHARS = 600


def normalize_query(query: str) -> str:
    """Normalize Unicode and whitespace without losing non-Latin scripts."""

    # SQLite unicode61 lowercases tokens but does not expand German ``ß`` to
    # ``ss``. ``lower`` mirrors that behavior; Python ``casefold`` would make
    # an otherwise identical "Grüße" query miss its FTS token.
    normalized = unicodedata.normalize("NFKC", query or "").lower()
    return " ".join(normalized.split())


def _tokens(normalized_query: str) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(normalized_query):
        if token not in seen:
            seen.add(token)
            output.append(token)
        # unicode61 does not equate German ß with the common uppercase/input
        # spelling SS. Search both forms while retaining the user's normalized
        # query verbatim in the result.
        if "ss" in token:
            sharp_s = token.replace("ss", "ß")
            if sharp_s not in seen:
                seen.add(sharp_s)
                output.append(sharp_s)
    return tuple(output)


def _fts_query(tokens: Iterable[str]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class _Ranked:
    row: sqlite3.Row
    score: float
    reason: str
    source_priority: int
    coverage: float


class VaultRetriever:
    """Retrieve bounded evidence without an LLM or embedding dependency."""

    def __init__(
        self,
        index: VaultIndex,
        *,
        max_candidates: int = 50,
    ) -> None:
        self.index = index
        self.max_candidates = min(
            _MAX_CANDIDATES,
            max(1, int(max_candidates)),
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Mapping[str, Any] | None = None,
        retrieval_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
    ) -> MemoryRetrievalResult:
        """Search FTS5 and persist only sources selected for the result."""

        normalized = normalize_query(query)
        terms = _tokens(normalized)
        actual_retrieval_id = retrieval_id or uuid.uuid4().hex
        clean_filters = self._normalize_filters(filters or {})
        if not terms:
            return MemoryRetrievalResult(
                retrieval_id=actual_retrieval_id,
                query=query,
                normalized_query=normalized,
                candidates=(),
                selected_sources=(),
                confidence=0.0,
                evidence_status=EvidenceStatus.INSUFFICIENT,
                retrieval_method="fts5_bm25",
                filters=clean_filters,
                warnings=("query contains no searchable terms",),
            )
        try:
            rows = self._search_rows(
                terms,
                filters=clean_filters,
                limit=min(self.max_candidates, max(top_k * 8, 20)),
            )
        except (sqlite3.Error, RuntimeError) as exc:
            return MemoryRetrievalResult(
                retrieval_id=actual_retrieval_id,
                query=query,
                normalized_query=normalized,
                candidates=(),
                selected_sources=(),
                confidence=0.0,
                evidence_status=EvidenceStatus.UNAVAILABLE,
                retrieval_method="fts5_bm25",
                filters=clean_filters,
                warnings=(f"vault index unavailable: {exc}",),
            )

        ranked = self._rank(rows, terms, normalized, clean_filters)
        deduped = self._dedupe(ranked)
        selected = self._diverse(deduped, top_k=max(1, min(top_k, 25)))
        candidates = tuple(
            RetrievalCandidate(
                note_id=item.row["note_id"],
                path=item.row["path"],
                title=item.row["title"],
                score=round(item.score, 6),
                reason=item.reason,
                content_hash=item.row["content_hash"],
                conflict_state=ConflictState(item.row["conflict_state"]),
                source_priority=item.source_priority,
            )
            for item in deduped[: self.max_candidates]
        )
        sources = tuple(
            self._source(actual_retrieval_id, item, terms) for item in selected
        )
        evidence_status, confidence, warnings = self._evidence(selected, terms)
        if self.index.embeddings_enabled:
            warnings.append(
                "embeddings are enabled but not required; this result used FTS5/BM25"
            )
        self._persist_sources(
            sources,
            task_id=task_id,
            session_id=session_id,
            correlation_id=correlation_id,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        return MemoryRetrievalResult(
            retrieval_id=actual_retrieval_id,
            query=query,
            normalized_query=normalized,
            candidates=candidates,
            selected_sources=sources,
            confidence=round(confidence, 6),
            evidence_status=evidence_status,
            retrieval_method="fts5_bm25",
            filters=clean_filters,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _normalize_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "note_type",
            "status",
            "scope",
            "project",
            "tags",
            "since",
            "until",
            "include_archived",
        }
        clean = {key: value for key, value in filters.items() if key in allowed}
        clean.setdefault("status", "active")
        clean.setdefault("include_archived", False)
        tags = clean.get("tags")
        if isinstance(tags, str):
            clean["tags"] = [tags]
        elif tags is not None:
            clean["tags"] = [str(tag) for tag in tags]
        return clean

    def _search_rows(
        self,
        terms: tuple[str, ...],
        *,
        filters: Mapping[str, Any],
        limit: int,
    ) -> list[sqlite3.Row]:
        clauses = ["memory_fts MATCH ?", "n.index_status='indexed'"]
        params: list[Any] = [_fts_query(terms)]
        for key, column in (
            ("note_type", "n.note_type"),
            ("status", "n.status"),
            ("scope", "n.scope"),
            ("project", "n.project"),
        ):
            value = filters.get(key)
            if value not in (None, ""):
                clauses.append(f"{column}=?")
                params.append(str(value))
        if not filters.get("include_archived", False):
            clauses.append("n.archived=0")
        if filters.get("since"):
            clauses.append("COALESCE(n.updated_at, n.created_at, '')>=?")
            params.append(str(filters["since"]))
        if filters.get("until"):
            clauses.append("COALESCE(n.updated_at, n.created_at, '')<=?")
            params.append(str(filters["until"]))
        tags = filters.get("tags") or []
        for tag in tags:
            clauses.append(
                "EXISTS (SELECT 1 FROM memory_tags t "
                "WHERE t.note_id=n.note_id AND t.tag=?)"
            )
            params.append(str(tag))
        params.append(limit)
        sql = f"""
            SELECT n.*,
                   bm25(memory_fts, 0.0, 10.0, 7.0, 1.0, 4.0, 5.0)
                       AS bm25_rank
            FROM memory_fts
            JOIN memory_notes n ON n.note_id=memory_fts.note_id
            WHERE {' AND '.join(clauses)}
            ORDER BY bm25_rank, n.updated_at DESC, n.path
            LIMIT ?
        """
        return self.index.connection.execute(sql, params).fetchall()

    def _rank(
        self,
        rows: list[sqlite3.Row],
        terms: tuple[str, ...],
        normalized_query: str,
        filters: Mapping[str, Any],
    ) -> list[_Ranked]:
        ranked: list[_Ranked] = []
        candidate_ids = {row["note_id"] for row in rows}
        link_counts: dict[str, int] = {}
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            link_rows = self.index.connection.execute(
                f"""
                SELECT source_note_id, COUNT(*) AS count
                FROM memory_links
                WHERE source_note_id IN ({placeholders})
                  AND target_note_id IN ({placeholders})
                GROUP BY source_note_id
                """,
                [*candidate_ids, *candidate_ids],
            ).fetchall()
            link_counts = {row["source_note_id"]: row["count"] for row in link_rows}

        for position, row in enumerate(rows):
            title = normalize_query(row["title"])
            aliases = [normalize_query(item) for item in json.loads(row["aliases"])]
            tags = [normalize_query(item) for item in json.loads(row["tags"])]
            project = normalize_query(row["project"] or "")
            body = normalize_query(row["body"])
            searchable = " ".join([title, *aliases, *tags, project, body])
            overlap = sum(1 for term in terms if term in searchable)
            coverage = overlap / len(terms)
            ordinal = 1.0 / (1.0 + position * 0.18)
            score = ordinal * (0.35 + 0.65 * coverage)
            reasons = ["FTS5/BM25"]
            if normalized_query == title:
                score += 0.55
                reasons.append("exact title")
            elif any(term in title for term in terms):
                score += 0.32
                reasons.append("title match")
            if normalized_query in aliases or any(
                term in alias for alias in aliases for term in terms
            ):
                score += 0.28
                reasons.append("alias match")
            if any(term in tags for term in terms):
                score += 0.14
                reasons.append("tag match")
            if project and any(term in project for term in terms):
                score += 0.12
                reasons.append("project match")
            folders = json.loads(row["folder_relations"])
            if any(
                term in normalize_query(folder)
                for term in terms
                for folder in folders
            ):
                score += 0.07
                reasons.append("folder relation")
            linked = int(link_counts.get(row["note_id"], 0))
            if linked:
                score += min(0.08, linked * 0.02)
                reasons.append("linked candidate")
            priority = SOURCE_PRIORITY.get(row["source"], 0)
            if priority:
                score += priority * 0.025
                reasons.append(f"source priority {priority}")
            if filters.get("project") and row["project"] == filters["project"]:
                score += 0.08
            ranked.append(
                _Ranked(
                    row=row,
                    score=min(1.0, score),
                    reason=", ".join(reasons),
                    source_priority=priority,
                    coverage=coverage,
                )
            )
        ranked.sort(
            key=lambda item: (
                item.score,
                item.source_priority,
                item.row["updated_at"] or "",
                item.row["title"].casefold(),
            ),
            reverse=True,
        )
        return ranked

    @staticmethod
    def _dedupe(ranked: list[_Ranked]) -> list[_Ranked]:
        by_hash: dict[str, _Ranked] = {}
        for item in ranked:
            body_hash = item.row["body_hash"]
            current = by_hash.get(body_hash)
            if current is None or (
                item.source_priority,
                item.score,
            ) > (
                current.source_priority,
                current.score,
            ):
                by_hash[body_hash] = item
        return sorted(
            by_hash.values(),
            key=lambda item: (
                item.score,
                item.source_priority,
                item.row["updated_at"] or "",
            ),
            reverse=True,
        )

    @staticmethod
    def _diverse(ranked: list[_Ranked], *, top_k: int) -> list[_Ranked]:
        selected: list[_Ranked] = []
        deferred: list[_Ranked] = []
        seen_folders: set[str] = set()
        for item in ranked:
            folder = Path(item.row["path"]).parent.as_posix().casefold()
            if folder in seen_folders:
                deferred.append(item)
                continue
            selected.append(item)
            seen_folders.add(folder)
            if len(selected) >= top_k:
                return selected
        for item in deferred:
            selected.append(item)
            if len(selected) >= top_k:
                break
        return selected

    def _source(
        self,
        retrieval_id: str,
        ranked: _Ranked,
        terms: tuple[str, ...],
    ) -> MemorySource:
        row = ranked.row
        relevant, line_start, line_end, section = _relevant_span(
            row["body"],
            terms,
            body_start_line=int(row["body_start_line"]),
        )
        source_id = hashlib.sha256(
            f"{retrieval_id}\0{row['note_id']}".encode("utf-8")
        ).hexdigest()
        return MemorySource(
            source_id=source_id,
            retrieval_id=retrieval_id,
            note_id=row["note_id"],
            path=row["path"],
            title=row["title"],
            relevant_text=relevant,
            line_start=line_start,
            line_end=line_end,
            section=section,
            score=round(ranked.score, 6),
            selection_reason=ranked.reason,
            content_hash=row["content_hash"],
            indexed_at=row["indexed_at"],
        )

    @staticmethod
    def _evidence(
        selected: list[_Ranked],
        terms: tuple[str, ...],
    ) -> tuple[EvidenceStatus, float, list[str]]:
        if not selected:
            return (
                EvidenceStatus.INSUFFICIENT,
                0.0,
                ["insufficient_evidence"],
            )
        conflicting = any(
            item.row["conflict_state"]
            in {
                ConflictState.POSSIBLE_CONFLICT.value,
                ConflictState.CONFIRMED_CONFLICT.value,
            }
            for item in selected
        )
        confidence = sum(item.score * item.coverage for item in selected) / len(
            selected
        )
        if conflicting:
            return (
                EvidenceStatus.CONFLICTING,
                min(1.0, confidence),
                ["selected sources contain an unresolved conflict"],
            )
        max_coverage = max(item.coverage for item in selected)
        if max_coverage < 0.5:
            return (
                EvidenceStatus.INSUFFICIENT,
                min(1.0, confidence),
                ["insufficient_evidence"],
            )
        if max_coverage < 1.0 and len(terms) > 1:
            return (
                EvidenceStatus.PARTIAL,
                min(1.0, confidence),
                ["only part of the normalized query is supported"],
            )
        return EvidenceStatus.SUFFICIENT, min(1.0, confidence), []

    def _persist_sources(
        self,
        sources: tuple[MemorySource, ...],
        *,
        task_id: str | None,
        session_id: str | None,
        correlation_id: str | None,
        thread_id: str | None,
        turn_id: str | None,
    ) -> None:
        if not sources:
            return
        timestamp = _now()
        with self.index.connection:
            self.index.connection.executemany(
                """
                INSERT OR IGNORE INTO memory_sources (
                    source_id, retrieval_id, task_id, session_id,
                    correlation_id, thread_id, turn_id, note_id, path, title,
                    relevant_text, line_start, line_end, section, score,
                    selection_reason, content_hash, indexed_at, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    (
                        source.source_id,
                        source.retrieval_id,
                        task_id,
                        session_id,
                        correlation_id,
                        thread_id,
                        turn_id,
                        source.note_id,
                        source.path,
                        source.title,
                        source.relevant_text,
                        source.line_start,
                        source.line_end,
                        source.section,
                        source.score,
                        source.selection_reason,
                        source.content_hash,
                        source.indexed_at,
                        timestamp,
                    )
                    for source in sources
                ],
            )


def _relevant_span(
    body: str,
    terms: tuple[str, ...],
    *,
    body_start_line: int,
) -> tuple[str, int | None, int | None, str | None]:
    lines = body.splitlines()
    if not lines:
        return "", None, None, None
    matched_index = 0
    for index, line in enumerate(lines):
        normalized = normalize_query(line)
        if any(term in normalized for term in terms):
            matched_index = index
            break
    start = max(0, matched_index - 1)
    end = min(len(lines), matched_index + 2)
    relevant = "\n".join(lines[start:end]).strip()
    while len(relevant) < _MAX_SPAN_CHARS and end < len(lines):
        candidate = f"{relevant}\n{lines[end]}".strip()
        if len(candidate) > _MAX_SPAN_CHARS:
            break
        relevant = candidate
        end += 1
    if len(relevant) > _MAX_SPAN_CHARS:
        relevant = relevant[:_MAX_SPAN_CHARS].rstrip() + "…"
    section: str | None = None
    for index in range(matched_index, -1, -1):
        if lines[index].lstrip().startswith("#"):
            section = lines[index].lstrip("#").strip() or None
            break
    return (
        relevant,
        body_start_line + start,
        body_start_line + max(start, end - 1),
        section,
    )


__all__ = ["VaultRetriever", "normalize_query"]
