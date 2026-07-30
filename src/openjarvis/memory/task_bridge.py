"""Phase-3 task, source, and trace correlation for vault memory."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from openjarvis.codex.redaction import redact_data, redact_text
from openjarvis.memory.vault_models import MemoryRetrievalResult, MemorySource
from openjarvis.tasks.store import TaskStore
from openjarvis.traces.store import TraceStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryTaskContext:
    """Canonical identifiers that follow one memory operation."""

    task_id: str
    session_id: str
    correlation_id: str
    thread_id: str | None = None
    turn_id: str | None = None


class MemoryTaskBridge:
    """Append bounded memory events and exact selected Task Sources."""

    def __init__(
        self,
        task_store: TaskStore,
        *,
        trace_store: TraceStore | None = None,
    ) -> None:
        self.task_store = task_store
        self.trace_store = trace_store

    def validate(self, context: MemoryTaskContext) -> None:
        task = self.task_store.get_task(context.task_id)
        if task is None:
            raise KeyError(f"unknown task: {context.task_id}")
        if task.session_id != context.session_id:
            raise ValueError("memory session_id does not match the canonical task")
        if task.correlation_id != context.correlation_id:
            raise ValueError("memory correlation_id does not match the canonical task")

    def query_started(
        self,
        context: MemoryTaskContext,
        *,
        retrieval_id: str,
        query: str,
        filters: Mapping[str, Any],
    ) -> None:
        self.validate(context)
        safe_preview = redact_text(query)[:160]
        self._emit(
            context,
            retrieval_id=retrieval_id,
            event_type="memory.query_started",
            discriminator="query",
            payload={
                "retrieval_id": retrieval_id,
                "query_preview": safe_preview,
                "query_digest": _digest(query),
                "filters": redact_data(dict(filters)),
            },
        )

    def record_result(
        self,
        context: MemoryTaskContext,
        result: MemoryRetrievalResult,
    ) -> None:
        self.validate(context)
        for candidate in result.candidates:
            self._emit(
                context,
                retrieval_id=result.retrieval_id,
                event_type="memory.candidate_found",
                discriminator=f"candidate:{candidate.note_id}",
                payload={
                    "retrieval_id": result.retrieval_id,
                    "note_id": candidate.note_id,
                    "path": candidate.path,
                    "content_hash": candidate.content_hash,
                    "score": candidate.score,
                    "reason": candidate.reason,
                    "conflict_state": candidate.conflict_state.value,
                },
            )
        for source in result.selected_sources:
            self._attach_source(context, source)
            self._emit(
                context,
                retrieval_id=result.retrieval_id,
                event_type="memory.source_selected",
                discriminator=f"source:{source.source_id}",
                payload=_source_payload(source),
            )
        if result.evidence_status.value == "insufficient":
            self._emit(
                context,
                retrieval_id=result.retrieval_id,
                event_type="memory.evidence_insufficient",
                discriminator="insufficient",
                payload={
                    "retrieval_id": result.retrieval_id,
                    "evidence_status": "insufficient",
                    "warning_count": len(result.warnings),
                },
            )
        if result.evidence_status.value == "conflicting":
            self._emit(
                context,
                retrieval_id=result.retrieval_id,
                event_type="memory.conflict_detected",
                discriminator="conflict",
                payload={
                    "retrieval_id": result.retrieval_id,
                    "note_ids": [
                        source.note_id for source in result.selected_sources
                    ],
                },
            )

    def event(
        self,
        context: MemoryTaskContext,
        *,
        event_type: str,
        operation_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Record a bounded non-retrieval memory event."""

        self.validate(context)
        self._emit(
            context,
            retrieval_id=operation_id,
            event_type=event_type,
            discriminator=operation_id,
            payload=payload,
        )

    def _attach_source(
        self,
        context: MemoryTaskContext,
        source: MemorySource,
    ) -> None:
        self.task_store.add_source(
            context.task_id,
            source_kind="memory_note",
            external_id=source.source_id,
            source_id=source.source_id,
            metadata={
                "retrieval_id": source.retrieval_id,
                "note_id": source.note_id,
                "path": source.path,
                "title": source.title,
                "content_hash": source.content_hash,
                "indexed_at": source.indexed_at,
                "score": source.score,
                "line_start": source.line_start,
                "line_end": source.line_end,
                "section": source.section,
                "relevant_preview": source.relevant_text[:320],
                "relevant_digest": _digest(source.relevant_text),
            },
        )

    def _emit(
        self,
        context: MemoryTaskContext,
        *,
        retrieval_id: str,
        event_type: str,
        discriminator: str,
        payload: Mapping[str, Any],
    ) -> None:
        source_event_id = (
            f"memory:{retrieval_id}:{event_type}:{_digest(discriminator)[:16]}"
        )
        event, _created = self.task_store.append_event(
            task_id=context.task_id,
            source_event_id=source_event_id,
            event_type=event_type,
            occurred_at=_now(),
            cause="memory_operation",
            component="vault_memory",
            thread_id=context.thread_id,
            turn_id=context.turn_id,
            payload=redact_data(dict(payload)),
        )
        if self.trace_store is not None:
            self.trace_store.save_task_event(event)


def _source_payload(source: MemorySource) -> dict[str, Any]:
    return {
        "retrieval_id": source.retrieval_id,
        "source_id": source.source_id,
        "note_id": source.note_id,
        "path": source.path,
        "content_hash": source.content_hash,
        "indexed_at": source.indexed_at,
        "score": source.score,
        "selection_reason": source.selection_reason,
        "line_start": source.line_start,
        "line_end": source.line_end,
        "section": source.section,
        "relevant_preview": source.relevant_text[:320],
        "relevant_digest": _digest(source.relevant_text),
    }


__all__ = ["MemoryTaskBridge", "MemoryTaskContext"]
