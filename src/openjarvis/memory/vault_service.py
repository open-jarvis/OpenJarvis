"""High-level authority for indexed vault memory operations."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Mapping

from openjarvis.memory.candidates import MemoryCandidateWorkflow
from openjarvis.memory.safe_write import AtomicMarkdownWriter
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import (
    IndexReport,
    MemoryCandidate,
    MemoryHealth,
    MemoryRetrievalResult,
)
from openjarvis.memory.vault_policy import RetrievalPurpose
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.memory.vault_watcher import PollingVaultWatcher
from openjarvis.tasks.store import TaskStore
from openjarvis.traces.store import TraceStore


class VaultMemoryService:
    """Coordinate indexing, retrieval, and Phase-3 event correlation."""

    def __init__(
        self,
        index: VaultIndex,
        *,
        retriever: VaultRetriever | None = None,
        task_bridge: MemoryTaskBridge | None = None,
        candidate_workflow: MemoryCandidateWorkflow | None = None,
        watcher: PollingVaultWatcher | None = None,
    ) -> None:
        self.index = index
        self.retriever = retriever or VaultRetriever(index)
        self.task_bridge = task_bridge
        self.candidate_workflow = candidate_workflow
        self.watcher = watcher

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

    def review_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Mapping[str, Any] | None = None,
    ) -> MemoryRetrievalResult:
        """Search review-only sources without attaching them to a task context."""

        return self.retriever.search(
            query,
            top_k=top_k,
            filters=dict(filters or {}),
            purpose=RetrievalPurpose.EXPLICIT_REVIEW,
            persist_sources=False,
        )

    def structure_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Mapping[str, Any] | None = None,
    ) -> MemoryRetrievalResult:
        """Search taxonomy/navigation notes outside normal answer retrieval."""

        return self.retriever.search(
            query,
            top_k=top_k,
            filters=dict(filters or {}),
            purpose=RetrievalPurpose.VAULT_STRUCTURE,
            persist_sources=False,
        )

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
                    "discovered": report.discovered,
                    "schema_valid": report.schema_valid,
                    "type_supported": report.type_supported,
                    "retrieval_eligible": report.retrieval_eligible,
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
        if self.watcher is not None:
            self.watcher.stop()
        self.index.close()


def build_vault_memory_service(
    config: Any,
    *,
    task_store: TaskStore | None,
    trace_store: TraceStore | None = None,
    initial_index: bool = True,
    flow_authority=None,
) -> VaultMemoryService | None:
    """Build configured vault memory without inventing or creating a vault.

    Task persistence is mandatory because every retrieval and candidate must be
    correlated with the canonical Phase-3 task authority.
    """

    memory_config = getattr(config, "memory", None)
    configured_path = str(getattr(memory_config, "vault_path", "") or "").strip()
    if not configured_path:
        return None
    if task_store is None:
        raise RuntimeError(
            "vault memory requires the canonical task runtime to be enabled"
        )
    vault_root = Path(configured_path).expanduser().resolve(strict=True)
    if not vault_root.is_dir():
        raise ValueError("configured vault_path must be an existing directory")
    mode = str(getattr(memory_config, "vault_mode", "read-only"))
    index_path = Path(
        str(getattr(memory_config, "vault_index_path", "") or "")
    ).expanduser()
    restore_path = Path(
        str(getattr(memory_config, "vault_restore_path", "") or "")
    ).expanduser()
    if not str(index_path):
        raise ValueError("vault_index_path must be configured outside the vault")
    if not str(restore_path):
        raise ValueError("vault_restore_path must be configured outside the vault")

    index = VaultIndex(
        vault_root,
        index_path,
        mode=mode,
        embeddings_enabled=bool(
            getattr(memory_config, "vault_embeddings_enabled", False)
        ),
    )
    try:
        retriever = VaultRetriever(index)
        bridge = MemoryTaskBridge(task_store, trace_store=trace_store)
        writer = AtomicMarkdownWriter(vault_root, restore_path)
        workflow = MemoryCandidateWorkflow(
            index,
            retriever,
            bridge,
            writer,
            flow_authority=flow_authority,
        )
        service = VaultMemoryService(
            index,
            retriever=retriever,
            task_bridge=bridge,
            candidate_workflow=workflow,
        )
        if initial_index:
            service.rebuild()
        if bool(getattr(memory_config, "vault_watch_enabled", False)):
            watcher = PollingVaultWatcher(
                service,
                interval_seconds=float(
                    getattr(
                        memory_config,
                        "vault_poll_interval_seconds",
                        2.0,
                    )
                ),
            )
            service.watcher = watcher
            watcher.start()
        return service
    except Exception:
        index.close()
        raise


__all__ = ["VaultMemoryService", "build_vault_memory_service"]
