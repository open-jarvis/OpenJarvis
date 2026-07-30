"""One controlled Codex Python SDK retrieval smoke with synthetic evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

from openjarvis.memory.task_bridge import MemoryTaskBridge, MemoryTaskContext
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.memory.vault_service import VaultMemoryService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import ExecutionLane
from openjarvis.traces.store import TraceStore


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _item_type(item: Any) -> str:
    root = getattr(item, "root", None)
    if root is not None:
        item = root
    for key in ("type", "item_type"):
        value = getattr(item, key, None)
        if value:
            return str(getattr(value, "value", value))
    return type(item).__name__


async def run() -> dict[str, object]:
    with (
        tempfile.TemporaryDirectory(prefix="openjarvis-phase4-codex-") as raw,
        ExitStack() as cleanup,
    ):
        root = Path(raw)
        vault = root / "synthetic-vault"
        workspace = root / "empty-read-only-workspace"
        state = root / "external-state"
        vault.mkdir()
        workspace.mkdir()
        note_id = str(uuid.uuid4())
        note_path = vault / "verified-answer.md"
        note_path.write_text(
            "---\n"
            f"id: {note_id}\n"
            "schema_version: 1\n"
            "type: fact\n"
            "status: active\n"
            "scope: personal\n"
            "source: manual\n"
            "title: Verified Synthetic Answer\n"
            "---\n"
            "The verified Phase 4 synthetic answer code is COBALT-47.\n",
            encoding="utf-8",
        )
        task_store = TaskStore(state / "tasks.sqlite3")
        trace_store = TraceStore(state / "traces.sqlite3")
        cleanup.callback(task_store.close)
        cleanup.callback(trace_store.close)
        task_store.create_task(
            task_id="phase4-codex-smoke-task",
            session_id="phase4-codex-smoke-session",
            correlation_id="phase4-codex-smoke-correlation",
            description="Answer one question from bounded synthetic evidence",
            execution_lane=ExecutionLane.MODEL,
            backend="codex",
            risk_level=0,
            component="phase4_codex_smoke",
            cause="verification",
            idempotency_key="phase4-codex-smoke-create",
        )
        index = VaultIndex(
            vault,
            state / "vault-index.sqlite3",
            mode="read-only",
        )
        bridge = MemoryTaskBridge(task_store, trace_store=trace_store)
        service = VaultMemoryService(
            index,
            retriever=VaultRetriever(index),
            task_bridge=bridge,
        )
        cleanup.callback(service.close)
        service.rebuild()
        context = MemoryTaskContext(
            task_id="phase4-codex-smoke-task",
            session_id="phase4-codex-smoke-session",
            correlation_id="phase4-codex-smoke-correlation",
            thread_id="phase4-codex-smoke-thread",
            turn_id="phase4-codex-smoke-turn",
        )
        retrieval = service.search(
            "What is the verified Phase 4 synthetic answer code?",
            context=context,
            top_k=1,
        )
        assert retrieval.selected_sources
        assert retrieval.selected_sources[0].note_id == note_id
        sources = retrieval.selected_sources
        evidence = "\n\n".join(
            (
                f"SOURCE_ID: {source.source_id}\n"
                f"NOTE_ID: {source.note_id}\n"
                f"PATH: {source.path}\n"
                f"SPAN: {source.relevant_text}"
            )
            for source in sources
        )
        expected = f"COBALT-47 [source: {note_id}]"
        prompt = (
            "Answer only from the bounded EVIDENCE below. Do not inspect files, "
            "run commands, call tools, browse, or use outside knowledge. Return "
            f"exactly this single line if supported: {expected}\n"
            "Otherwise return exactly: insufficient_evidence\n\n"
            f"EVIDENCE\n{evidence}"
        )
        before_workspace = _tree_digest(workspace)
        config = CodexConfig(
            cwd=str(workspace),
            client_name="openjarvis-phase4-smoke",
            client_title="OpenJarvis Phase 4 Retrieval Smoke",
            experimental_api=False,
        )
        async with AsyncCodex(config) as codex:
            thread = await codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                developer_instructions=(
                    "This is a read-only evidence formatting check. Never use "
                    "tools or external context."
                ),
                ephemeral=True,
                sandbox=Sandbox.read_only,
            )
            result = await thread.run(
                prompt,
                approval_mode=ApprovalMode.deny_all,
                cwd=str(workspace),
                sandbox=Sandbox.read_only,
            )
        after_workspace = _tree_digest(workspace)
        item_types = [_item_type(item) for item in result.items]
        prohibited = {
            "commandExecution",
            "fileChange",
            "mcpToolCall",
            "dynamicToolCall",
            "collabAgentToolCall",
        }
        task_sources = task_store.list_sources("phase4-codex-smoke-task")
        task_source_note_ids = {
            str(source.metadata.get("note_id")) for source in task_sources
        }
        selected_note_ids = {source.note_id for source in sources}
        assert result.final_response == expected
        assert prohibited.isdisjoint(item_types)
        assert before_workspace == after_workspace
        assert task_source_note_ids == selected_note_ids
        assert note_path.read_text(encoding="utf-8").endswith("COBALT-47.\n")
        return {
            "status": "passed",
            "sdk": "openai-codex",
            "sandbox": "read-only",
            "approval_mode": "deny_all",
            "temporary_vault": True,
            "retrieval_before_codex": True,
            "retrieval_method": retrieval.retrieval_method,
            "evidence_status": retrieval.evidence_status.value,
            "selected_note_ids": sorted(selected_note_ids),
            "task_source_note_ids": sorted(task_source_note_ids),
            "exact_response": result.final_response,
            "item_types": item_types,
            "tool_items": sorted(prohibited.intersection(item_types)),
            "workspace_unchanged": before_workspace == after_workspace,
            "vault_note_unchanged": True,
            "codex_turns": 1,
        }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))
