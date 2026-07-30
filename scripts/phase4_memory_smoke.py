"""End-to-end Phase-4 smoke using only a temporary synthetic vault."""

from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path

from fastapi.testclient import TestClient

from openjarvis.memory.candidates import MemoryCandidateWorkflow
from openjarvis.memory.safe_write import AtomicMarkdownWriter
from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.memory.vault_service import VaultMemoryService
from openjarvis.server.app import create_app
from openjarvis.tasks.service import TaskService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import ExecutionLane
from openjarvis.traces.store import TraceStore


def _note(path: Path, *, note_id: str, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {note_id}\n"
        "schema_version: 1\n"
        "type: fact\n"
        "status: active\n"
        "scope: personal\n"
        "source: manual\n"
        f"title: {title}\n"
        "---\n"
        f"{body.rstrip()}\n",
        encoding="utf-8",
    )


def _close_safely(resource: object) -> None:
    try:
        resource.close()  # type: ignore[attr-defined]
    except Exception:
        pass


def run() -> dict[str, object]:
    with (
        tempfile.TemporaryDirectory(prefix="openjarvis-phase4-smoke-") as raw,
        ExitStack() as cleanup,
    ):
        root = Path(raw)
        vault = root / "synthetic-vault"
        state = root / "external-state"
        restore = root / "external-restore"
        vault.mkdir()
        python_id = str(uuid.uuid4())
        graph_id = str(uuid.uuid4())
        windows_id = str(uuid.uuid4())
        _note(
            vault / "preferences" / "python.md",
            note_id=python_id,
            title="Python Preference",
            body="The synthetic user prefers Python for Codex integrations.",
        )
        _note(
            vault / "projects" / "graph.md",
            note_id=graph_id,
            title="Memory Graph",
            body="The memory graph links to [[Python Preference]].",
        )
        _note(
            vault / "windows.md",
            note_id=windows_id,
            title="Windows Notes",
            body="The synthetic index runs on Windows without embeddings.",
        )

        task_store = TaskStore(state / "tasks.sqlite3")
        trace_store = TraceStore(state / "traces.sqlite3")
        cleanup.callback(_close_safely, task_store)
        cleanup.callback(_close_safely, trace_store)
        task_store.create_task(
            task_id="phase4-smoke-task",
            session_id="phase4-smoke-session",
            correlation_id="phase4-smoke-correlation",
            description="Synthetic Phase 4 memory smoke",
            execution_lane=ExecutionLane.MODEL,
            backend="codex",
            risk_level=1,
            component="phase4_smoke",
            cause="verification",
            idempotency_key="phase4-smoke-task-create",
        )
        index = VaultIndex(
            vault,
            state / "vault-index.sqlite3",
            mode="writable-test",
        )
        retriever = VaultRetriever(index)
        bridge = MemoryTaskBridge(task_store, trace_store=trace_store)
        writer = AtomicMarkdownWriter(vault, restore)
        workflow = MemoryCandidateWorkflow(index, retriever, bridge, writer)
        service = VaultMemoryService(
            index,
            retriever=retriever,
            task_bridge=bridge,
            candidate_workflow=workflow,
        )
        cleanup.callback(_close_safely, service)
        context = MemoryTaskContext(
            task_id="phase4-smoke-task",
            session_id="phase4-smoke-session",
            correlation_id="phase4-smoke-correlation",
            thread_id="phase4-smoke-thread",
            turn_id="phase4-smoke-turn",
        )

        rebuilt = service.rebuild(context=context)
        retrieval = service.search(
            "Python Preference Codex integrations",
            context=context,
        )
        assert rebuilt.indexed == 3
        assert retrieval.selected_sources
        assert retrieval.selected_sources[0].note_id == python_id
        assert retrieval.evidence_status.value in {
            "sufficient",
            "partial",
            "insufficient",
        }

        original = vault / "preferences" / "python.md"
        moved_path = vault / "archive-test" / "renamed-python.md"
        moved_path.parent.mkdir()
        original.replace(moved_path)
        moved = service.sync(context=context)
        assert moved.moved == 1
        moved_note = service.index.get_note(python_id)
        assert moved_note is not None
        assert moved_note.path == "archive-test/renamed-python.md"

        candidate = service.create_candidate(
            context,
            body="The synthetic user prefers bounded evidence previews.",
            note_type="preference",
            idempotency_key="phase4-smoke-candidate",
        )
        candidate_path = vault / candidate.proposed_path
        assert not candidate_path.exists()
        applied = service.decide_candidate(
            candidate.candidate_id,
            allow=True,
            decision_id="phase4-smoke-allow-once",
        )
        assert candidate_path.is_file()
        assert applied.write_operation_id
        graph_after_apply = service.index.graph()
        assert any(
            node["id"] == candidate.note_id
            for node in graph_after_apply["nodes"]
        )
        restore_artifact = service.index.connection.execute(
            """
            SELECT restore_path FROM memory_write_operations
            WHERE operation_id=?
            """,
            (applied.write_operation_id,),
        ).fetchone()["restore_path"]
        assert Path(restore_artifact).is_file()
        workflow.restore_write(applied.write_operation_id)
        assert not candidate_path.exists()
        assert service.index.get_note(candidate.note_id) is None

        source_count = len(task_store.list_sources("phase4-smoke-task"))
        assert source_count == len(retrieval.selected_sources)
        app = create_app(
            object(),
            "phase4-smoke-model",
            vault_memory_service=service,
            task_store=task_store,
            task_service=TaskService(task_store),
        )
        with TestClient(app) as client:
            server_health = client.get("/v1/memory/health")
            assert server_health.status_code == 200
            assert server_health.json()["note_count"] == 3
        try:
            _ = service.index.connection
        except RuntimeError:
            server_shutdown_closed_index = True
        else:
            server_shutdown_closed_index = False
        assert server_shutdown_closed_index
        return {
            "status": "passed",
            "vault_kind": "temporary_synthetic",
            "vault_removed_after_run": True,
            "initial_indexed_notes": rebuilt.indexed,
            "retrieval_method": retrieval.retrieval_method,
            "evidence_status": retrieval.evidence_status.value,
            "selected_source_ids": [
                source.source_id for source in retrieval.selected_sources
            ],
            "task_source_count": source_count,
            "stable_note_id_after_move": python_id,
            "move_detected": moved.moved,
            "candidate_status_before_approval": candidate.status.value,
            "candidate_status_after_approval": applied.status.value,
            "allow_once": True,
            "atomic_write": True,
            "graph_updated": True,
            "restore_artifact_external": not Path(restore_artifact).is_relative_to(
                vault
            ),
            "restore_verified": True,
            "server_health_status": server_health.status_code,
            "server_shutdown_closed_index": server_shutdown_closed_index,
            "embeddings_enabled": False,
        }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
