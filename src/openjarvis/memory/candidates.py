"""Non-blocking memory proposals and direct Flow-mode Markdown writes."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from openjarvis.memory.frontmatter import render_canonical_markdown
from openjarvis.memory.safe_write import (
    AtomicMarkdownWriter,
    AtomicWriteResult,
    ConcurrentMemoryWrite,
    safe_target,
    unified_diff,
)
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import (
    SOURCE_PRIORITY,
    CandidateStatus,
    ConflictState,
    MemoryCandidate,
    MemoryConflict,
)
from openjarvis.memory.vault_policy import WRITABLE_NOTE_TYPES
from openjarvis.memory.vault_retrieval import VaultRetriever, normalize_query
from openjarvis.tasks.policy import RiskLevel

_REMEMBER_PREFIX_RE = re.compile(
    r"^\s*(?:(?:okay|ok|also|und)\s+)*(?:"
    r"merk(?:e)?\s+dir|bitte\s+merken|remember(?:\s+that)?|"
    r"du\s+sollst\s+dir\s+merken|ich\s+m[öo]chte\s*,?\s*dass\s+du\s+dir\s+merkst|"
    r"behalt(?:e)?\s+(?:das\s+)?(?:im\s+ged[aä]chtnis)?|"
    r"speicher(?:e)?\s+(?:das\s+)?(?:als\s+erinnerung)?"
    r")\s*[:,-]?\s*(?P<body>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_REMEMBER_SUFFIX_RE = re.compile(
    r"^\s*(?P<body>.+?)\s*[,;.-]?\s*(?:"
    r"merk(?:e)?\s+dir\s+das|merk(?:e)?\s+es\s+dir|"
    r"das\s+sollst\s+du\s+dir\s+merken|"
    r"behalt(?:e)?\s+das\s+im\s+ged[aä]chtnis|"
    r"remember\s+(?:that|this)"
    r")\s*[.!]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_MEMORY_INTENT_RE = re.compile(
    r"\b(?:merk(?:e|st)?|merken|remember|behalt(?:e|en)?|ged[aä]chtnis|"
    r"als\s+erinnerung\s+speichern|dauerhaft\s+speichern)\b",
    re.IGNORECASE,
)
_COMPOSITE_ACTION_RE = re.compile(
    r"\b(?:lies|lese|auslesen|durchsuch(?:e|en)?|such(?:e|en)?|öffne|oeffne|"
    r"browse|research|navigate|fetch|download|webseite|website|ordner|dateien?)\b",
    re.IGNORECASE,
)


def has_memory_intent(text: str) -> bool:
    """Recognize an explicit semantic request to retain information."""

    value = (text or "").strip()
    if not value or not _MEMORY_INTENT_RE.search(value):
        return False
    # Questions about existing memory are retrieval requests, not writes.
    if re.match(
        r"^(?:was|weißt|weisst|kannst|hast|erinnerst|do\s+you|what\s+do\s+you)\b",
        value,
        re.IGNORECASE,
    ) and "sollst" not in value.casefold():
        return False
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def recognize_memory_request(text: str) -> str | None:
    """Return a directly storable fact from an explicit remember request.

    Composite requests such as "read this website and remember it" deliberately
    return ``None``: the requested action must finish first and its verified
    result is stored by the chat orchestrator.
    """

    value = text or ""
    match = _REMEMBER_PREFIX_RE.match(value) or _REMEMBER_SUFFIX_RE.match(value)
    if match is None:
        return None
    body = match.group("body").strip()
    if _COMPOSITE_ACTION_RE.search(body):
        return None
    return body or None


def _slug(text: str) -> str:
    normalized = normalize_query(text)
    slug = re.sub(r"[^\w-]+", "-", normalized, flags=re.UNICODE).strip("-_")
    return (slug[:48].rstrip("-_") or "memory").lower()


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class MemoryCandidateWorkflow:
    """Persist suggestions or atomically apply an explicit Flow memory write."""

    def __init__(
        self,
        index: VaultIndex,
        retriever: VaultRetriever,
        task_bridge: MemoryTaskBridge,
        writer: AtomicMarkdownWriter,
        *,
        flow_authority=None,
    ) -> None:
        self.index = index
        self.retriever = retriever
        self.task_bridge = task_bridge
        self.writer = writer
        self.flow_authority = flow_authority
        self._lock = threading.RLock()

    def create(
        self,
        context: MemoryTaskContext,
        *,
        body: str,
        note_type: str = "fact",
        scope: str = "personal",
        project: str | None = None,
        tags: Iterable[str] = (),
        aliases: Iterable[str] = (),
        proposed_path: str | None = None,
        correction: bool = False,
        conflict_key: str | None = None,
        idempotency_key: str,
    ) -> MemoryCandidate:
        """Create a reviewable candidate without writing Markdown."""

        self.task_bridge.validate(context)
        body = (body or "").strip()
        if not body:
            raise ValueError("candidate body must not be blank")
        if note_type not in WRITABLE_NOTE_TYPES:
            raise ValueError(f"unsupported note type: {note_type}")
        operation_key = self._operation_key(
            context.task_id, "candidate.create", idempotency_key
        )
        existing_id = self._operation_candidate(operation_key)
        if existing_id is not None:
            existing = self.get(existing_id)
            if existing is None:
                raise RuntimeError("idempotent candidate record is missing")
            return existing

        candidate_id = uuid.uuid4().hex
        note_id = str(uuid.uuid4())
        timestamp = _now()
        relative_path = proposed_path or (
            f"captures/{timestamp[:10]}-{_slug(body)}-{note_id[:8]}.md"
        )
        target = safe_target(self.index.vault_root, relative_path)
        if target.exists():
            raise ValueError(
                "candidate target already exists; explicit note updates are separate"
            )
        _target, before, before_hash = self.writer.inspect(relative_path)
        if before is not None:
            raise ValueError("candidate target unexpectedly exists")
        source = "user_correction" if correction else "user"
        planned = render_canonical_markdown(
            note_id=note_id,
            note_type=note_type,
            scope=scope,
            project=project,
            tags=tuple(tags),
            aliases=tuple(aliases),
            source=source,
            source_task_id=context.task_id,
            source_session_id=context.session_id,
            created_at=timestamp,
            updated_at=timestamp,
            body=body,
        )
        planned_diff = unified_diff("", planned, relative_path=relative_path)
        similar = self.retriever.search(body, top_k=5)
        conflict_state = self._candidate_conflict(
            body,
            similar_note_ids=[item.note_id for item in similar.candidates],
            conflict_key=conflict_key,
        )
        flow_active = bool(self.flow_authority and self.flow_authority.is_flow())
        risk_level = int(RiskLevel.REVERSIBLE_WORKSPACE)
        metadata = {
            "similar_note_ids": [item.note_id for item in similar.candidates],
            "similar_retrieval_id": similar.retrieval_id,
            "conflict_key": conflict_key,
            "source_priority": SOURCE_PRIORITY[source],
            "flow_direct": flow_active,
            "thread_id": context.thread_id,
            "turn_id": context.turn_id,
        }
        with self._lock, self.index.connection:
            self.index.connection.execute(
                """
                INSERT INTO memory_candidates (
                    candidate_id, task_id, session_id, correlation_id, note_id,
                    proposed_path, note_type, scope, project, source, body,
                    planned_markdown, planned_diff, before_hash,
                    expected_version, risk_level, status, conflict_state,
                    created_at, updated_at, metadata
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
                """,
                (
                    candidate_id,
                    context.task_id,
                    context.session_id,
                    context.correlation_id,
                    note_id,
                    relative_path,
                    note_type,
                    scope,
                    project,
                    source,
                    body,
                    planned,
                    planned_diff,
                    before_hash,
                    "absent",
                    risk_level,
                    CandidateStatus.PROPOSED.value,
                    conflict_state.value,
                    timestamp,
                    timestamp,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
        with self._lock, self.index.connection:
            self.index.connection.execute(
                """
                INSERT INTO memory_api_operations (
                    operation_key, operation, task_id, result, created_at
                ) VALUES (?, 'candidate.create', ?, ?, ?)
                """,
                (
                    operation_key,
                    context.task_id,
                    json.dumps({"candidate_id": candidate_id}),
                    _now(),
                ),
            )
            if conflict_state is not ConflictState.NONE:
                self._insert_candidate_conflict(
                    candidate_id,
                    note_id,
                    [item.note_id for item in similar.candidates],
                    conflict_state,
                    conflict_key,
                )
        self.task_bridge.event(
            context,
            event_type="memory.write_candidate_created",
            operation_id=candidate_id,
            payload={
                "candidate_id": candidate_id,
                "note_id": note_id,
                "path": relative_path,
                "risk_level": risk_level,
                "approval_id": None,
                "flow_direct": flow_active,
                "conflict_state": conflict_state.value,
                "diff_digest": _stable_id(planned_diff),
            },
        )
        created = self.get(candidate_id)
        if created is None:
            raise RuntimeError("candidate could not be read back")
        return (
            self.apply(created.candidate_id)
            if flow_active
            else created
        )

    def apply(self, candidate_id: str) -> MemoryCandidate:
        """Apply a proposal once while the owner-authenticated Flow is active."""

        with self._lock:
            candidate = self._require(candidate_id)
            if candidate.status is CandidateStatus.APPLIED:
                return candidate
            active_flow = bool(
                self.flow_authority and self.flow_authority.is_flow()
            )
            if not active_flow:
                raise PermissionError("memory writes require an active Flow session")
            operation_id = uuid.uuid4().hex
            context = self._context(candidate)
            try:
                result = self.writer.write(
                    candidate.proposed_path,
                    candidate.planned_markdown,
                    expected_hash=candidate.before_hash,
                    operation_id=operation_id,
                )
            except ConcurrentMemoryWrite as exc:
                self._record_failed_write(
                    candidate,
                    operation_id,
                    error=str(exc),
                    status="conflicted",
                )
                self._set_status(
                    candidate_id,
                    CandidateStatus.CONFLICTED,
                    conflict_state=ConflictState.EXTERNALLY_MODIFIED,
                )
                self._insert_candidate_conflict(
                    candidate_id,
                    candidate.note_id,
                    [],
                    ConflictState.EXTERNALLY_MODIFIED,
                    None,
                )
                self.task_bridge.event(
                    context,
                    event_type="memory.conflict_detected",
                    operation_id=operation_id,
                    payload={
                        "candidate_id": candidate_id,
                        "path": candidate.proposed_path,
                        "conflict_state": "externally_modified",
                    },
                )
                raise

            self._record_successful_write(candidate, result)
            applied = self._set_status(
                candidate_id,
                CandidateStatus.APPLIED,
                applied_at=result.completed_at,
                write_operation_id=result.operation_id,
            )
            self.task_bridge.event(
                context,
                event_type="memory.write_applied",
                operation_id=result.operation_id,
                payload={
                    "candidate_id": candidate_id,
                    "operation_id": result.operation_id,
                    "note_id": candidate.note_id,
                    "path": candidate.proposed_path,
                    "before_hash": result.before_hash,
                    "after_hash": result.after_hash,
                    "diff_digest": _stable_id(result.diff),
                    "restore_ref": Path(result.restore_path).name,
                },
            )
            try:
                report = self.index.sync()
            except Exception as exc:
                self.task_bridge.event(
                    context,
                    event_type="memory.index_failed",
                    operation_id=result.operation_id,
                    payload={
                        "candidate_id": candidate_id,
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            self.task_bridge.event(
                context,
                event_type="memory.index_updated",
                operation_id=report.run_id,
                payload={
                    "candidate_id": candidate_id,
                    "run_id": report.run_id,
                    "created": report.created,
                    "modified": report.modified,
                },
            )
            return applied

    def get(self, candidate_id: str) -> MemoryCandidate | None:
        row = self.index.connection.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
        return _candidate_from_row(row) if row else None

    def list(
        self,
        *,
        open_only: bool = False,
        limit: int = 100,
    ) -> list[MemoryCandidate]:
        if open_only:
            rows = self.index.connection.execute(
                """
                SELECT * FROM memory_candidates
                WHERE status IN (
                    'proposed', 'pending_approval', 'approved', 'conflicted'
                )
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self.index.connection.execute(
                """
                SELECT * FROM memory_candidates
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_candidate_from_row(row) for row in rows]

    def list_conflicts(
        self, *, open_only: bool = True, limit: int = 100
    ) -> list[MemoryConflict]:
        where = "WHERE resolved_at IS NULL" if open_only else ""
        rows = self.index.connection.execute(
            f"""
            SELECT * FROM memory_conflicts {where}
            ORDER BY updated_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_conflict_from_row(row) for row in rows]

    def resolve_conflict(
        self,
        conflict_id: str,
        *,
        winner_note_id: str,
        resolution: str,
    ) -> MemoryConflict:
        row = self.index.connection.execute(
            "SELECT * FROM memory_conflicts WHERE conflict_id=?",
            (conflict_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown memory conflict: {conflict_id}")
        note_ids = json.loads(row["note_ids"])
        if winner_note_id not in note_ids:
            raise ValueError("winner_note_id must belong to the conflict")
        timestamp = _now()
        with self.index.connection:
            self.index.connection.execute(
                """
                UPDATE memory_conflicts
                SET winner_note_id=?, resolution=?, resolved_at=?, updated_at=?,
                    state='none'
                WHERE conflict_id=?
                """,
                (
                    winner_note_id,
                    resolution,
                    timestamp,
                    timestamp,
                    conflict_id,
                ),
            )
        updated = self.index.connection.execute(
            "SELECT * FROM memory_conflicts WHERE conflict_id=?",
            (conflict_id,),
        ).fetchone()
        return _conflict_from_row(updated)

    def restore_write(self, operation_id: str) -> str | None:
        """Restore a test write from its external artifact and reindex."""

        row = self.index.connection.execute(
            "SELECT * FROM memory_write_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown memory write operation: {operation_id}")
        result = AtomicWriteResult(
            operation_id=row["operation_id"],
            path=row["path"],
            before_hash=row["before_hash"],
            after_hash=row["after_hash"],
            diff=row["diff"],
            restore_path=row["restore_path"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            created_file=row["before_hash"] is None,
        )
        restored_hash = self.writer.restore(result)
        with self.index.connection:
            self.index.connection.execute(
                """
                UPDATE memory_write_operations
                SET status='restored', completed_at=? WHERE operation_id=?
                """,
                (_now(), operation_id),
            )
        self.index.sync()
        return restored_hash

    def _candidate_conflict(
        self,
        body: str,
        *,
        similar_note_ids: list[str],
        conflict_key: str | None,
    ) -> ConflictState:
        normalized = normalize_query(body)
        for note_id in similar_note_ids:
            note = self.index.get_note(note_id)
            if note is not None and normalize_query(note.body) == normalized:
                return ConflictState.DUPLICATE
        if conflict_key:
            for note in self.index.list_notes():
                existing_key = str(
                    note.raw_frontmatter.get("conflict_key") or ""
                ).casefold()
                if (
                    existing_key == conflict_key.casefold()
                    and normalize_query(note.body) != normalized
                ):
                    return ConflictState.CONFIRMED_CONFLICT
        return ConflictState.NONE

    def _insert_candidate_conflict(
        self,
        candidate_id: str,
        note_id: str,
        similar_note_ids: list[str],
        state: ConflictState,
        conflict_key: str | None,
    ) -> None:
        conflict_type = {
            ConflictState.DUPLICATE: "candidate.duplicate",
            ConflictState.EXTERNALLY_MODIFIED: "write.external_change",
        }.get(state, "candidate.conflicting_fact")
        note_ids = [note_id, *similar_note_ids]
        conflict_id = _stable_id(conflict_type, candidate_id, *note_ids)
        timestamp = _now()
        self.index.connection.execute(
            """
            INSERT OR REPLACE INTO memory_conflicts (
                conflict_id, conflict_type, state, note_ids, candidate_id,
                summary, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conflict_id,
                conflict_type,
                state.value,
                json.dumps(note_ids),
                candidate_id,
                f"memory candidate requires review: {state.value}",
                json.dumps({"conflict_key": conflict_key}, sort_keys=True),
                timestamp,
                timestamp,
            ),
        )

    def _record_successful_write(
        self,
        candidate: MemoryCandidate,
        result: AtomicWriteResult,
    ) -> None:
        with self.index.connection:
            self.index.connection.execute(
                """
                INSERT INTO memory_write_operations (
                    operation_id, candidate_id, task_id, path, before_hash,
                    after_hash, diff, restore_path, status, created_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?)
                """,
                (
                    result.operation_id,
                    candidate.candidate_id,
                    candidate.task_id,
                    result.path,
                    result.before_hash,
                    result.after_hash,
                    result.diff,
                    result.restore_path,
                    result.created_at,
                    result.completed_at,
                ),
            )

    def _record_failed_write(
        self,
        candidate: MemoryCandidate,
        operation_id: str,
        *,
        error: str,
        status: str,
    ) -> None:
        timestamp = _now()
        with self.index.connection:
            self.index.connection.execute(
                """
                INSERT INTO memory_write_operations (
                    operation_id, candidate_id, task_id, path, before_hash,
                    diff, status, error, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    candidate.candidate_id,
                    candidate.task_id,
                    candidate.proposed_path,
                    candidate.before_hash,
                    candidate.planned_diff,
                    status,
                    error,
                    timestamp,
                    timestamp,
                ),
            )

    def _set_status(
        self,
        candidate_id: str,
        status: CandidateStatus,
        *,
        conflict_state: ConflictState | None = None,
        applied_at: str | None = None,
        write_operation_id: str | None = None,
    ) -> MemoryCandidate:
        updates = ["status=?", "updated_at=?"]
        params: list[Any] = [status.value, _now()]
        if conflict_state is not None:
            updates.append("conflict_state=?")
            params.append(conflict_state.value)
        if applied_at is not None:
            updates.append("applied_at=?")
            params.append(applied_at)
        if write_operation_id is not None:
            updates.append("write_operation_id=?")
            params.append(write_operation_id)
        params.append(candidate_id)
        with self.index.connection:
            self.index.connection.execute(
                f"""
                UPDATE memory_candidates SET {", ".join(updates)}
                WHERE candidate_id=?
                """,
                params,
            )
        return self._require(candidate_id)

    def _require(self, candidate_id: str) -> MemoryCandidate:
        candidate = self.get(candidate_id)
        if candidate is None:
            raise KeyError(f"unknown memory candidate: {candidate_id}")
        return candidate

    @staticmethod
    def _context(candidate: MemoryCandidate) -> MemoryTaskContext:
        return MemoryTaskContext(
            task_id=candidate.task_id,
            session_id=candidate.session_id,
            correlation_id=candidate.correlation_id,
            thread_id=candidate.metadata.get("thread_id"),
            turn_id=candidate.metadata.get("turn_id"),
        )

    @staticmethod
    def _operation_key(task_id: str, operation: str, key: str) -> str:
        if not key.strip():
            raise ValueError("idempotency_key must be non-empty")
        return f"{task_id}:{operation}:{key}"

    def _operation_candidate(self, operation_key: str) -> str | None:
        row = self.index.connection.execute(
            """
            SELECT result FROM memory_api_operations WHERE operation_key=?
            """,
            (operation_key,),
        ).fetchone()
        if row is None:
            return None
        return str(json.loads(row["result"])["candidate_id"])


def _candidate_from_row(row: Mapping[str, Any]) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=row["candidate_id"],
        task_id=row["task_id"],
        session_id=row["session_id"],
        correlation_id=row["correlation_id"],
        note_id=row["note_id"],
        proposed_path=row["proposed_path"],
        note_type=row["note_type"],
        scope=row["scope"],
        project=row["project"],
        source=row["source"],
        body=row["body"],
        planned_markdown=row["planned_markdown"],
        planned_diff=row["planned_diff"],
        before_hash=row["before_hash"],
        expected_version=row["expected_version"],
        risk_level=row["risk_level"],
        status=CandidateStatus(row["status"]),
        approval_id=row["approval_id"],
        conflict_state=ConflictState(row["conflict_state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        applied_at=row["applied_at"],
        write_operation_id=row["write_operation_id"],
        metadata=json.loads(row["metadata"]),
    )


def _conflict_from_row(row: Mapping[str, Any]) -> MemoryConflict:
    return MemoryConflict(
        conflict_id=row["conflict_id"],
        conflict_type=row["conflict_type"],
        state=ConflictState(row["state"]),
        note_ids=tuple(json.loads(row["note_ids"])),
        candidate_id=row["candidate_id"],
        summary=row["summary"],
        winner_note_id=row["winner_note_id"],
        resolution=row["resolution"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        resolved_at=row["resolved_at"],
        metadata=json.loads(row["metadata"]),
    )


def candidate_to_dict(candidate: MemoryCandidate) -> dict[str, Any]:
    """Serialize a candidate for API/UI use."""

    data = asdict(candidate)
    data["status"] = candidate.status.value
    data["conflict_state"] = candidate.conflict_state.value
    return data


__all__ = [
    "MemoryCandidateWorkflow",
    "candidate_to_dict",
    "has_memory_intent",
    "recognize_memory_request",
]
