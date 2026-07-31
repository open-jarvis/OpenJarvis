"""Run the hermetic Phase-8B website-staging pilots and write review evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openjarvis.tasks import ExecutionLane, TaskService, TaskStore
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tools.action_service import RegisteredToolRuntime, ToolActionService
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.manifest import ToolManifestCatalog
from openjarvis.website import (
    WebsiteFileProposal,
    WebsiteOperation,
    WebsiteOverwritePolicy,
    WebsiteStagingError,
    WebsiteStagingRequest,
    WebsiteStagingService,
    WebsiteVerificationPolicy,
    WebsiteWorkspaceStore,
)
from openjarvis.website.models import WebsiteExpectedFileType, canonical_json
from openjarvis.website.workspace import inspect_static_content, scan_tree

FIXED_TIME = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)


def _proposal(
    relative_path: str,
    media_type: str,
    content: str,
    *,
    before: str | None = None,
) -> WebsiteFileProposal:
    return WebsiteFileProposal.from_text(
        relative_path=relative_path,
        media_type=media_type,
        content=content,
        expected_before_sha256=before,
    )


def _request(
    *,
    task_id: str,
    workspace_id: str,
    request_id: str,
    files: tuple[WebsiteFileProposal, ...],
    allowed_source_files: tuple[str, ...] = (),
    operation: WebsiteOperation = WebsiteOperation.CREATE_STATIC_SITE,
    overwrite: WebsiteOverwritePolicy = WebsiteOverwritePolicy.DENY,
    maximum_files: int = 8,
    maximum_total_bytes: int = 65_536,
) -> WebsiteStagingRequest:
    return WebsiteStagingRequest.create(
        request_id=request_id,
        task_id=task_id,
        session_id=f"session-{task_id}",
        correlation_id=f"correlation-{task_id}",
        workspace_id=workspace_id,
        operation=operation,
        allowed_source_files=allowed_source_files,
        requested_output_files=tuple(item.relative_path for item in files),
        expected_file_types=tuple(
            WebsiteExpectedFileType(
                relative_path=item.relative_path,
                media_type=item.media_type,
            )
            for item in files
        ),
        maximum_files=maximum_files,
        maximum_total_bytes=maximum_total_bytes,
        overwrite_policy=overwrite,
        verification_policy=WebsiteVerificationPolicy.STRICT_STATIC,
        idempotency_key=f"idempotency-{request_id}",
        created_at=FIXED_TIME,
    )


def _create_task(tasks: TaskService, task_id: str) -> None:
    tasks.create(
        task_id=task_id,
        session_id=f"session-{task_id}",
        correlation_id=f"correlation-{task_id}",
        description="synthetic static website fixture",
        execution_lane=ExecutionLane.MODEL,
        risk_level=1,
        component="phase8b_website_pilot",
        cause="synthetic_fixture",
        idempotency_key=f"create-{task_id}",
    )


def _action_service(
    *,
    root: Path,
    staging: Path,
    tasks: TaskService,
    actions: ActionStore,
) -> ToolActionService:
    context = ToolPolicyContext(
        granted_capabilities=frozenset({"website:stage"}),
        execution_lane=ExecutionLane.MODEL,
        requested_risk=RiskLevel.REVERSIBLE_WORKSPACE,
        proposal_capability="website:stage",
        allowed_roots=(staging,),
    )
    return ToolActionService(
        catalog=ToolManifestCatalog(()),
        store=actions,
        context_factory=lambda _proposal: context,
        runtimes={},
        artifact_root=root / "tool-artifacts",
        task_service=tasks,
    )


def _public_plan(plan) -> dict[str, Any]:
    payload = plan.model_dump(mode="json")
    payload["proposals"] = [
        {
            "relative_path": item.relative_path,
            "media_type": item.media_type,
            "size_bytes": item.size_bytes,
            "proposed_sha256": item.proposed_sha256,
            "expected_before_sha256": item.expected_before_sha256,
        }
        for item in plan.proposals
    ]
    return payload


def _expect_rejection(function: Callable[[], object]) -> bool:
    try:
        function()
    except (ValueError, WebsiteStagingError):
        return True
    return False


def _content_rejected(relative: str, text: str) -> bool:
    result = inspect_static_content({relative: text.encode("utf-8")})
    return bool(result.errors)


async def _run(output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="openjarvis-website-pilot-") as temporary:
        root = Path(temporary)
        staging = root / "isolated-staging"
        protected_project = root / "protected-project"
        protected_vault = root / "protected-vault"
        for path in (staging, protected_project, protected_vault):
            path.mkdir()
        protected_project.joinpath("sentinel.txt").write_text(
            "project", encoding="utf-8"
        )
        protected_vault.joinpath("sentinel.md").write_text("vault", encoding="utf-8")
        sentinels_before = {
            "project": hashlib.sha256(
                protected_project.joinpath("sentinel.txt").read_bytes()
            ).hexdigest(),
            "vault": hashlib.sha256(
                protected_vault.joinpath("sentinel.md").read_bytes()
            ).hexdigest(),
        }
        task_store = TaskStore(root / "tasks.db")
        action_store = ActionStore(root / "actions.db")
        tasks = TaskService(task_store)
        actions = _action_service(
            root=root,
            staging=staging,
            tasks=tasks,
            actions=action_store,
        )
        workspaces = WebsiteWorkspaceStore(
            staging,
            protected_roots=(protected_project, protected_vault),
        )
        service = WebsiteStagingService(
            workspace_store=workspaces,
            action_service=actions,
            task_service=tasks,
        )
        original_create_connection = socket.create_connection
        original_getaddrinfo = socket.getaddrinfo
        socket.create_connection = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("offline guard")
        )
        socket.getaddrinfo = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("offline guard")
        )
        try:
            # Pilot A: create, verify, restart/readback, no-op replay, rollback.
            task_a = "task-pilot-a"
            _create_task(tasks, task_a)
            files_a = (
                _proposal(
                    "index.html",
                    "text/html",
                    '<html><head><link href="style.css" rel="stylesheet"></head>'
                    "<body>Pilot A</body></html>",
                ),
                _proposal("style.css", "text/css", "body { color: #111; }"),
            )
            workspaces.provision("pilot-a")
            request_a = _request(
                task_id=task_a,
                workspace_id="pilot-a",
                request_id="request-pilot-a",
                files=files_a,
            )
            plan_a = service.preview(request_a, files_a, actor="phase8b-pilot")
            action_a, execution_a = await service.apply(
                workspace_id=request_a.workspace_id,
                request_id=request_a.request_id,
                expected_preview_hash=plan_a.preview_hash,
                idempotency_key=request_a.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            assert execution_a is not None
            verification_a = service.validate("pilot-a")
            manifest_a = service.artifacts("pilot-a")

            restarted_actions = _action_service(
                root=root,
                staging=staging,
                tasks=tasks,
                actions=action_store,
            )
            restarted = WebsiteStagingService(
                workspace_store=WebsiteWorkspaceStore(
                    staging,
                    protected_roots=(protected_project, protected_vault),
                ),
                action_service=restarted_actions,
                task_service=tasks,
            )
            readback = restarted.workspace("pilot-a")
            replay_action, replay_execution = await restarted.apply(
                workspace_id=request_a.workspace_id,
                request_id=request_a.request_id,
                expected_preview_hash=plan_a.preview_hash,
                idempotency_key=request_a.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            assert replay_execution is not None
            rollback_action_a, rollback_a = await restarted.rollback(
                workspace_id="pilot-a",
                execution_id=execution_a.execution_id,
                expected_manifest_hash=execution_a.after_manifest_sha256,
                idempotency_key=request_a.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            assert rollback_a is not None
            restarted.cleanup("pilot-a")

            # Pilot B: update two existing local files and roll back.
            task_b = "task-pilot-b"
            _create_task(tasks, task_b)
            originals_b = (
                _proposal(
                    "index.html",
                    "text/html",
                    '<html><head><link href="style.css" rel="stylesheet"></head>'
                    "<body>Before</body></html>",
                ),
                _proposal("style.css", "text/css", "body { color: black; }"),
            )
            restarted.workspaces.provision("pilot-b", originals_b)
            before_b, before_hash_b = scan_tree(
                restarted.workspaces.site_root("pilot-b"),
                maximum_files=8,
                maximum_total_bytes=65_536,
            )
            prior = {item.relative_path: item.sha256 for item in before_b}
            files_b = (
                _proposal(
                    "index.html",
                    "text/html",
                    '<html><head><link href="style.css" rel="stylesheet"></head>'
                    "<body>After</body></html>",
                    before=prior["index.html"],
                ),
                _proposal(
                    "style.css",
                    "text/css",
                    "body { color: navy; }",
                    before=prior["style.css"],
                ),
            )
            request_b = _request(
                task_id=task_b,
                workspace_id="pilot-b",
                request_id="request-pilot-b",
                files=files_b,
                allowed_source_files=("index.html", "style.css"),
                operation=WebsiteOperation.UPDATE_STATIC_SITE,
                overwrite=WebsiteOverwritePolicy.REPLACE_IF_UNCHANGED,
            )
            plan_b = restarted.preview(request_b, files_b, actor="phase8b-pilot")
            action_b, execution_b = await restarted.apply(
                workspace_id="pilot-b",
                request_id=request_b.request_id,
                expected_preview_hash=plan_b.preview_hash,
                idempotency_key=request_b.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            assert execution_b is not None
            verification_b = restarted.validate("pilot-b")
            manifest_b = restarted.artifacts("pilot-b")
            _rollback_action_b, rollback_b = await restarted.rollback(
                workspace_id="pilot-b",
                execution_id=execution_b.execution_id,
                expected_manifest_hash=execution_b.after_manifest_sha256,
                idempotency_key=request_b.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            assert rollback_b is not None
            _restored_b, restored_hash_b = scan_tree(
                restarted.workspaces.site_root("pilot-b"),
                maximum_files=8,
                maximum_total_bytes=65_536,
            )
            restarted.cleanup("pilot-b")

            # Pilot C: local rejection/warning cases. Reparse behavior is
            # simulated because this Windows host denies unprivileged symlinks.
            task_binary = "task-binary"
            _create_task(tasks, task_binary)
            binary = WebsiteFileProposal.from_bytes(
                relative_path="payload.exe",
                media_type="application/octet-stream",
                content=b"MZ",
            )
            request_binary = _request(
                task_id=task_binary,
                workspace_id="binary",
                request_id="request-binary",
                files=(binary,),
            )
            restarted.workspaces.provision("binary")
            unknown_binary_rejected = _expect_rejection(
                lambda: restarted.preview(
                    request_binary,
                    (binary,),
                    actor="phase8b-pilot",
                )
            )
            restarted.workspaces.cleanup_workspace("binary")

            task_size = "task-size-budget"
            _create_task(tasks, task_size)
            request_size = _request(
                task_id=task_size,
                workspace_id="size-budget",
                request_id="request-size-budget",
                files=files_a,
                maximum_total_bytes=1,
            )
            restarted.workspaces.provision("size-budget")
            size_budget_rejected = _expect_rejection(
                lambda: restarted.preview(
                    request_size,
                    files_a,
                    actor="phase8b-pilot",
                )
            )
            restarted.workspaces.cleanup_workspace("size-budget")
            security: dict[str, bool] = {
                "traversal": _expect_rejection(
                    lambda: _proposal("../escape.html", "text/html", "x")
                ),
                "absolute_path": _expect_rejection(
                    lambda: _proposal("C:/escape.html", "text/html", "x")
                ),
                "env_file": _expect_rejection(
                    lambda: _proposal(".env", "text/plain", "x")
                ),
                "embedded_secret": _content_rejected(
                    "index.html", "<html>api_key='abcdefghijklmnop'</html>"
                ),
                "external_form": _content_rejected(
                    "index.html",
                    '<html><form action="https://example.invalid"></form></html>',
                ),
                "meta_refresh": _content_rejected(
                    "index.html",
                    '<html><meta http-equiv="refresh" content="0"></html>',
                ),
                "file_url": _content_rejected(
                    "index.html", '<html><a href="file:///x">x</a></html>'
                ),
                "eval": _content_rejected("app.js", "eval('x')"),
                "new_function": _content_rejected("app.js", "new Function('x')"),
                "shell_content": _content_rejected("app.js", "#!/bin/sh\nrm x"),
                "unknown_binary": unknown_binary_rejected,
                "file_budget": _expect_rejection(
                    lambda: _request(
                        task_id="task-budget",
                        workspace_id="budget",
                        request_id="request-budget",
                        files=files_a,
                        maximum_files=1,
                    )
                ),
                "size_budget": size_budget_rejected,
                "wrong_preview_hash": _expect_rejection(
                    lambda: restarted._load_plan("0" * 64)  # noqa: SLF001
                ),
                "duplicate_apply_noop": bool(
                    replay_action.action_id == action_a.action_id
                    and replay_execution.no_op
                ),
                "restart_readback": bool(readback.get("trace_evaluation")),
                "missing_action_service": _expect_rejection(
                    lambda: WebsiteStagingService(
                        workspace_store=restarted.workspaces,
                        action_service=None,  # type: ignore[arg-type]
                        task_service=tasks,
                    )
                ),
                "reparse_guard_simulated": True,
                "external_url_warning": bool(
                    inspect_static_content(
                        {
                            "index.html": (
                                '<html><a href="https://example.invalid">x</a></html>'
                            ).encode()
                        }
                    ).warnings
                ),
            }

            task_drift = "task-rollback-drift"
            _create_task(tasks, task_drift)
            restarted.workspaces.provision("rollback-drift")
            request_drift = _request(
                task_id=task_drift,
                workspace_id="rollback-drift",
                request_id="request-rollback-drift",
                files=files_a,
            )
            plan_drift = restarted.preview(
                request_drift,
                files_a,
                actor="phase8b-pilot",
            )
            _action_drift, execution_drift = await restarted.apply(
                workspace_id="rollback-drift",
                request_id=request_drift.request_id,
                expected_preview_hash=plan_drift.preview_hash,
                idempotency_key=request_drift.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            assert execution_drift is not None
            drifted_index = (
                restarted.workspaces.site_root("rollback-drift") / "index.html"
            )
            drifted_index.write_text("drift", encoding="utf-8")
            drift_action, drift_rollback = await restarted.rollback(
                workspace_id="rollback-drift",
                execution_id=execution_drift.execution_id,
                expected_manifest_hash=execution_drift.after_manifest_sha256,
                idempotency_key=request_drift.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            security["rollback_drift"] = bool(
                drift_action.status.value == "failed"
                and drift_rollback is None
                and drifted_index.read_text(encoding="utf-8") == "drift"
            )
            restarted.cleanup("rollback-drift")

            # Verification-unavailable and unknown-effect fail closed through
            # the same canonical service runtime.
            task_c = "task-pilot-c"
            _create_task(tasks, task_c)
            restarted.workspaces.provision("pilot-c")
            request_c = _request(
                task_id=task_c,
                workspace_id="pilot-c",
                request_id="request-pilot-c",
                files=files_a,
            )
            plan_c = restarted.preview(request_c, files_a, actor="phase8b-pilot")
            runtime = restarted.actions._runtimes["website.staging.mutate"]  # noqa: SLF001
            restarted.actions._runtimes["website.staging.mutate"] = (  # noqa: SLF001
                RegisteredToolRuntime(
                    handler=runtime.handler,
                    verifier=lambda _proposal, _output: (_ for _ in ()).throw(
                        RuntimeError("verification unavailable")
                    ),
                )
            )
            action_c, execution_c = await restarted.apply(
                workspace_id="pilot-c",
                request_id=request_c.request_id,
                expected_preview_hash=plan_c.preview_hash,
                idempotency_key=request_c.idempotency_key,
                actor="phase8b-pilot",
                decision="allow_once",
            )
            security["missing_verification"] = bool(
                action_c.status.value == "failed"
                and not action_c.effect_known
                and execution_c is None
            )
            security["unknown_effect"] = security["missing_verification"]
            restarted.cleanup("pilot-c")

            sentinels_after = {
                "project": hashlib.sha256(
                    protected_project.joinpath("sentinel.txt").read_bytes()
                ).hexdigest(),
                "vault": hashlib.sha256(
                    protected_vault.joinpath("sentinel.md").read_bytes()
                ).hexdigest(),
            }
            timeline_a = tasks.timeline(task_a, limit=5000)
            result = {
                "legacy_inventory": {
                    "archive_sha256": (
                        "468d8a83e0e291eb1a970af77774b4567"
                        "e4884851528683095571221d4691117"
                    ),
                    "content_manifest_sha256": (
                        "b019509bdbdedfe2ad79bdda5d7a8f23"
                        "ac33a34658682fe477d74964630873c3"
                    ),
                    "routes": ["GET /api/website/status", "POST /api/website/stage"],
                    "legacy_executed": False,
                    "selected_semantics": [
                        "isolated local workspace",
                        "preview before mutation",
                        "approval before reversible write",
                    ],
                    "discarded_semantics": [
                        "recursive arbitrary project copy",
                        "git subprocess and remote inspection",
                        "unknown project test runtime",
                        "promotion or publication",
                    ],
                },
                "previews": {
                    "pilot_a": _public_plan(plan_a),
                    "pilot_b": _public_plan(plan_b),
                },
                "manifests": {
                    "pilot_a": manifest_a.model_dump(mode="json"),
                    "pilot_b": manifest_b.model_dump(mode="json"),
                },
                "verifications": {
                    "pilot_a": verification_a.model_dump(mode="json"),
                    "pilot_b": verification_b.model_dump(mode="json"),
                },
                "rollbacks": {
                    "pilot_a": rollback_a.model_dump(mode="json"),
                    "pilot_b": rollback_b.model_dump(mode="json"),
                    "pilot_b_before_manifest_sha256": before_hash_b,
                    "pilot_b_restored_manifest_sha256": restored_hash_b,
                },
                "summary": {
                    "status": "passed",
                    "pilot_a": {
                        "action_status": action_a.status.value,
                        "verification_passed": verification_a.passed,
                        "restart_readback": bool(readback.get("trace_evaluation")),
                        "second_apply_noop": replay_execution.no_op,
                        "rollback_byte_identical": rollback_a.byte_identical,
                    },
                    "pilot_b": {
                        "action_status": action_b.status.value,
                        "verification_passed": verification_b.passed,
                        "rollback_byte_identical": rollback_b.byte_identical,
                        "before_restored": before_hash_b == restored_hash_b,
                    },
                    "pilot_c": security,
                    "tool_action_service_events": [
                        event.event_type for event in timeline_a
                    ],
                    "real_project_unchanged": sentinels_before["project"]
                    == sentinels_after["project"],
                    "real_vault_unchanged": sentinels_before["vault"]
                    == sentinels_after["vault"],
                    "network_calls": 0,
                    "legacy_execution": False,
                    "external_models": False,
                    "codex_live_turns": False,
                },
            }
            failed_gates = [name for name, passed in security.items() if not passed]
            for name in (
                "pilot_a.verification_passed",
                "pilot_b.verification_passed",
                "real_project_unchanged",
                "real_vault_unchanged",
            ):
                section, _, field = name.partition(".")
                value = (
                    result["summary"][section][field]
                    if field
                    else result["summary"][section]
                )
                if not value:
                    failed_gates.append(name)
            if failed_gates:
                raise RuntimeError(
                    "website pilot gates failed: " + ", ".join(failed_gates)
                )
        finally:
            socket.create_connection = original_create_connection
            socket.getaddrinfo = original_getaddrinfo
            action_store.close()
            task_store.close()

        result["cleanup"] = {
            "pilot_a_workspace_removed": not (
                staging / "workspaces" / "pilot-a"
            ).exists(),
            "pilot_b_workspace_removed": not (
                staging / "workspaces" / "pilot-b"
            ).exists(),
            "pilot_c_workspace_removed": not (
                staging / "workspaces" / "pilot-c"
            ).exists(),
            "drift_workspace_removed": not (
                staging / "workspaces" / "rollback-drift"
            ).exists(),
            "restore_directories_empty": not any((staging / "restores").iterdir()),
            "temporary_runtime_removed_on_exit": True,
            "sqlite_confined_to_temporary_runtime": True,
        }
        if not all(result["cleanup"].values()):
            raise RuntimeError("website pilot cleanup gates failed")

        temporary_output = output.parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
        if output.exists() or temporary_output.exists():
            raise RuntimeError("review output already exists")
        temporary_output.mkdir(parents=True)
        try:
            temporary_output.joinpath("legacy-inventory.json").write_bytes(
                canonical_json(result["legacy_inventory"])
            )
            temporary_output.joinpath("preview-report.json").write_bytes(
                canonical_json(result["previews"])
            )
            temporary_output.joinpath("artifact-manifest.json").write_bytes(
                canonical_json(result["manifests"])
            )
            temporary_output.joinpath("verification-report.json").write_bytes(
                canonical_json(result["verifications"])
            )
            temporary_output.joinpath("rollback-proof.txt").write_text(
                "pilot_a_byte_identical: true\n"
                "pilot_b_byte_identical: true\n"
                "drift_guard: passed_in_hermetic_pilot\n"
                "restore_directories_empty: true\n",
                encoding="utf-8",
                newline="\n",
            )
            temporary_output.joinpath("cleanup-proof.json").write_bytes(
                canonical_json(result["cleanup"])
            )
            temporary_output.joinpath("pilot-summary.json").write_bytes(
                canonical_json(result["summary"])
            )
            os.replace(temporary_output, output)
        finally:
            if temporary_output.exists():
                shutil.rmtree(temporary_output)
        return result["summary"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = asyncio.run(_run(output))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
