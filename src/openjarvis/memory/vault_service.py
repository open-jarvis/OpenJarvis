"""High-level authority for indexed vault memory operations."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from openjarvis.memory.candidates import MemoryCandidateWorkflow
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import (
    IndexReport,
    MemoryCandidate,
    MemoryHealth,
    MemoryRetrievalResult,
)
from openjarvis.memory.vault_retrieval import VaultRetriever


class VaultMemoryService:
    """Coordinate indexing, retrieval, and Phase-3 event correlation."""

    def __init__(
        self,
        index: VaultIndex,
        *,
        retriever: VaultRetriever | None = None,
        task_bridge: MemoryTaskBridge | None = None,
        candidate_workflow: MemoryCandidateWorkflow | None = None,
    ) -> None:
        self.index = index
        self.retriever = retriever or VaultRetriever(index)
        self.task_bridge = task_bridge
        self.candidate_workflow = candidate_workflow

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Mapping[str, Any] | None = None,
        context: MemoryTaskContext | None = None,
        retrieval_id: str | None = None,
    ) -> MemoryRetrievalResult:
        actual_id = retrieval_id or uuid.uuid4().hex
        clean_filters = dict(filters or {})
        if context is not None and self.task_bridge is not None:
            self.task_bridge.query_started(
                context,
                retrieval_id=actual_id,
                query=query,
                filters=clean_filters,
            )
        result = self.retriever.search(
            query,
            top_k=top_k,
            filters=clean_filters,
            retrieval_id=actual_id,
            task_id=context.task_id if context else None,
            session_id=context.session_id if context else None,
            correlation_id=context.correlation_id if context else None,
            thread_id=context.thread_id if context else None,
            turn_id=context.turn_id if context else None,
        )
        if context is not None and self.task_bridge is not None:
            self.task_bridge.record_result(context, result)
        return result

    def rebuild(self, *, context: MemoryTaskContext | None = None) -> IndexReport:
        try:
            report = self.index.rebuild()
        except Exception as exc:
            if context is not None and self.task_bridge is not None:
                self.task_bridge.event(
                    context,
                    event_type="memory.index_failed",
                    operation_id=uuid.uuid4().hex,
                    payload={"error_type": type(exc).__name__},
                )
            raise
        if context is not None and self.task_bridge is not None:
            self.task_bridge.event(
                context,
                event_type="memory.index_updated",
                operation_id=report.run_id,
                payload={
                    "run_id": report.run_id,
                    "mode": report.mode,
                    "indexed": report.indexed,
                    "parser_errors": report.parser_errors,
                    "conflicts": report.conflicts,
                },
            )
        return report

    def sync(self, *, context: MemoryTaskContext | None = None) -> IndexReport:
        report = self.index.sync()
        if context is not None and self.task_bridge is not None:
            self.task_bridge.event(
                context,
                event_type="memory.index_updated",
                operation_id=report.run_id,
                payload={
                    "run_id": report.run_id,
                    "mode": report.mode,
                    "created": report.created,
                    "modified": report.modified,
                    "moved": report.moved,
                    "deleted": report.deleted,
                },
            )
        return report

    def health(self) -> MemoryHealth:
        return self.index.health()

    def create_candidate(
        self,
        context: MemoryTaskContext,
        **kwargs: Any,
    ) -> MemoryCandidate:
        if self.candidate_workflow is None:
            raise RuntimeError("memory candidate workflow is not configured")
        return self.candidate_workflow.create(context, **kwargs)

    def decide_candidate(
        self,
        candidate_id: str,
        *,
        allow: bool,
        decision_id: str,
    ) -> MemoryCandidate:
        if self.candidate_workflow is None:
            raise RuntimeError("memory candidate workflow is not configured")
        return self.candidate_workflow.decide(
            candidate_id,
            allow=allow,
            decision_id=decision_id,
        )

    def close(self) -> None:
        self.index.close()


__all__ = ["VaultMemoryService"]
