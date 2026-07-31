"""Hermetic Phase-8B website staging contracts and safety gates."""

from __future__ import annotations

import hashlib
import json
import socket
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from openjarvis.tasks import ExecutionLane, TaskService, TaskStore
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tools.action_service import RegisteredToolRuntime, ToolActionService
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.actions import ActionStatus
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
from openjarvis.website.models import WebsiteExpectedFileType
from openjarvis.website.workspace import confined_path, scan_tree

FIXED_TIME = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


@dataclass
class Harness:
    root: Path
    staging: Path
    real_project: Path
    real_vault: Path
    task_store: TaskStore
    action_store: ActionStore
    tasks: TaskService
    actions: ToolActionService
    service: WebsiteStagingService
    context: ToolPolicyContext

    def close(self) -> None:
        self.action_store.close()
        self.task_store.close()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    real_project = tmp_path / "real-project"
    real_vault = tmp_path / "real-vault"
    real_project.mkdir()
    real_vault.mkdir()
    (real_project / "untouched.txt").write_text("project", encoding="utf-8")
    (real_vault / "untouched.md").write_text("vault", encoding="utf-8")
    staging = tmp_path / "isolated-pilot"
    staging.mkdir()
    task_store = TaskStore(tmp_path / "tasks.db")
    tasks = TaskService(task_store)
    action_store = ActionStore(tmp_path / "actions.db")
    context = ToolPolicyContext(
        granted_capabilities=frozenset({"website:stage"}),
        execution_lane=ExecutionLane.MODEL,
        requested_risk=RiskLevel.REVERSIBLE_WORKSPACE,
        proposal_capability="website:stage",
        allowed_roots=(staging,),
    )
    actions = ToolActionService(
        catalog=ToolManifestCatalog(()),
        store=action_store,
        context_factory=lambda _proposal: context,
        runtimes={},
        artifact_root=tmp_path / "tool-artifacts",
        task_service=tasks,
    )
    workspaces = WebsiteWorkspaceStore(
        staging,
        protected_roots=(real_project, real_vault),
    )
    service = WebsiteStagingService(
        workspace_store=workspaces,
        action_service=actions,
        task_service=tasks,
    )
    value = Harness(
        root=tmp_path,
        staging=staging,
        real_project=real_project,
        real_vault=real_vault,
        task_store=task_store,
        action_store=action_store,
        tasks=tasks,
        actions=actions,
        service=service,
        context=context,
    )
    yield value
    value.close()


def proposal(
    path: str,
    content: str,
    *,
    media_type: str | None = None,
    before: str | None = None,
) -> WebsiteFileProposal:
    suffix_types = {
        ".css": "text/css",
        ".html": "text/html",
        ".js": "text/javascript",
        ".json": "application/json",
        ".md": "text/markdown",
        ".svg": "image/svg+xml",
    }
    return WebsiteFileProposal.from_text(
        relative_path=path,
        media_type=media_type or suffix_types[Path(path).suffix],
        content=content,
        expected_before_sha256=before,
    )


def create_request(
    harness: Harness,
    *,
    workspace_id: str = "workspace-1",
    request_id: str = "request-1",
    files: tuple[WebsiteFileProposal, ...],
    allowed_source_files: tuple[str, ...] = (),
    operation: WebsiteOperation = WebsiteOperation.CREATE_STATIC_SITE,
    overwrite: WebsiteOverwritePolicy = WebsiteOverwritePolicy.DENY,
    maximum_files: int = 16,
    maximum_total_bytes: int = 65_536,
) -> WebsiteStagingRequest:
    task_id = f"task-{request_id}"
    session_id = f"session-{request_id}"
    correlation_id = f"correlation-{request_id}"
    if harness.tasks.get(task_id) is None:
        harness.tasks.create(
            task_id=task_id,
            session_id=session_id,
            correlation_id=correlation_id,
            description="synthetic static website pilot",
            execution_lane=ExecutionLane.MODEL,
            risk_level=1,
            component="website_test",
            cause="synthetic_fixture",
            idempotency_key=f"create-{task_id}",
        )
    return WebsiteStagingRequest.create(
        request_id=request_id,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
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


def create_plan(
    harness: Harness,
    files: tuple[WebsiteFileProposal, ...],
    *,
    workspace_id: str = "workspace-1",
    request_id: str = "request-1",
):
    files = tuple(sorted(files, key=lambda item: item.relative_path.casefold()))
    harness.service.workspaces.provision(workspace_id)
    request = create_request(
        harness,
        workspace_id=workspace_id,
        request_id=request_id,
        files=files,
    )
    return request, harness.service.preview(request, files, actor="local-test")


async def apply_plan(harness: Harness, request, plan, *, decision="allow_once"):
    return await harness.service.apply(
        workspace_id=request.workspace_id,
        request_id=request.request_id,
        expected_preview_hash=plan.preview_hash,
        idempotency_key=request.idempotency_key,
        actor="local-test",
        decision=decision,
    )


def safe_files() -> tuple[WebsiteFileProposal, ...]:
    return (
        proposal(
            "about.html",
            '<!doctype html><html><body><a href="index.html">Home</a></body></html>',
        ),
        proposal(
            "index.html",
            '<!doctype html><html><head><link href="style.css" rel="stylesheet">'
            '</head><body><a href="about.html">About</a></body></html>',
        ),
        proposal("style.css", "body { color: #111; }"),
    )


def test_valid_request_is_accepted_and_frozen(harness: Harness) -> None:
    request, _plan = create_plan(harness, safe_files())
    assert request.request_hash
    with pytest.raises(ValidationError):
        request.workspace_id = "changed"  # type: ignore[misc]


def test_unknown_request_field_is_rejected(harness: Harness) -> None:
    harness.service.workspaces.provision("workspace-1")
    request = create_request(harness, files=(proposal("index.html", "<html></html>"),))
    payload = request.model_dump(mode="json")
    payload["unknown"] = True
    with pytest.raises(ValidationError, match="unknown"):
        WebsiteStagingRequest.model_validate(payload)


@pytest.mark.parametrize(
    "operation",
    ["unknown", "deploy", "publish", "upload", "synchronize_remote", "modify_dns"],
)
def test_unknown_and_remote_operations_are_rejected(operation: str) -> None:
    payload = {
        "request_id": "request-1",
        "task_id": "task-1",
        "session_id": "session-1",
        "correlation_id": "correlation-1",
        "workspace_id": "workspace-1",
        "operation": operation,
        "allowed_source_files": [],
        "requested_output_files": [],
        "expected_file_types": [],
        "maximum_files": 1,
        "maximum_total_bytes": 1,
        "overwrite_policy": "deny",
        "verification_policy": "strict_static",
        "idempotency_key": "once",
        "created_at": FIXED_TIME.isoformat(),
        "request_hash": "0" * 64,
    }
    with pytest.raises(ValidationError):
        WebsiteStagingRequest.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        r"C:/secret/index.html",
        "/absolute/index.html",
        "../escape.html",
        "a/../b.html",
        ".env",
        "config/.env",
    ],
)
def test_absolute_and_traversal_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        proposal(path, "<html></html>", media_type="text/plain")


def test_reparse_point_is_rejected_before_read(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.service.workspaces.provision("workspace-1")
    site = harness.service.workspaces.site_root("workspace-1")
    target = site / "linked"
    target.mkdir()
    import openjarvis.website.workspace as workspace_module

    original = workspace_module._is_reparse
    monkeypatch.setattr(
        workspace_module,
        "_is_reparse",
        lambda path: path == target or original(path),
    )
    with pytest.raises(WebsiteStagingError, match="reparse"):
        scan_tree(site, maximum_files=4, maximum_total_bytes=4096)


def test_workspace_escape_is_rejected(harness: Harness) -> None:
    harness.service.workspaces.provision("workspace-1")
    site = harness.service.workspaces.site_root("workspace-1")
    with pytest.raises(ValueError, match="traversal"):
        confined_path(site, "../escape.html")


def test_preview_changes_no_website_file(harness: Harness) -> None:
    harness.service.workspaces.provision("workspace-1")
    site = harness.service.workspaces.site_root("workspace-1")
    before = tuple(site.rglob("*"))
    request = create_request(harness, files=safe_files())
    harness.service.preview(request, safe_files(), actor="local-test")
    assert tuple(site.rglob("*")) == before


@pytest.mark.asyncio
async def test_apply_requires_exact_preview_hash(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    with pytest.raises(WebsiteStagingError, match="preview"):
        await harness.service.apply(
            workspace_id=request.workspace_id,
            request_id=request.request_id,
            expected_preview_hash="0" * 64,
            idempotency_key=request.idempotency_key,
            actor="local-test",
            decision="allow_once",
        )
    assert plan.preview_hash != "0" * 64


@pytest.mark.asyncio
async def test_before_manifest_cas_blocks_drift(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    (
        harness.service.workspaces.site_root(request.workspace_id) / "drift.md"
    ).write_text("drift", encoding="utf-8")
    with pytest.raises(WebsiteStagingError, match="CAS"):
        await apply_plan(harness, request, plan)


def test_tool_action_service_is_mandatory(harness: Harness) -> None:
    with pytest.raises(WebsiteStagingError, match="ToolActionService"):
        WebsiteStagingService(
            workspace_store=harness.service.workspaces,
            action_service=None,  # type: ignore[arg-type]
            task_service=harness.tasks,
        )


@pytest.mark.asyncio
async def test_no_write_occurs_before_canonical_allow_once(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    site = harness.service.workspaces.site_root(request.workspace_id)
    action, execution = await apply_plan(
        harness, request, plan, decision="request_approval"
    )
    assert action.status is ActionStatus.WAITING_APPROVAL
    assert execution is None
    assert not list(site.iterdir())
    action, execution = await apply_plan(harness, request, plan)
    assert action.status is ActionStatus.COMPLETED
    assert execution is not None


@pytest.mark.asyncio
async def test_policy_risk_floor_and_exactly_one_approval(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    action, _execution = await apply_plan(harness, request, plan)
    assert action.risk_level >= RiskLevel.REVERSIBLE_WORKSPACE
    assert action.approval_id
    approval = harness.tasks.store.get_approval(action.approval_id)
    assert approval is not None
    assert approval.status.value == "approved"
    events = harness.action_store.list_events(action.action_id)
    assert sum(event.event_type == "tool.waiting_approval" for event in events) == 1
    assert all(event.payload.get("allow_once_only") is not False for event in events)
    assert "always" not in json.dumps([event.payload for event in events]).lower()


def test_file_budget_is_enforced_by_contract(harness: Harness) -> None:
    files = safe_files()
    with pytest.raises(ValidationError, match="maximum_files"):
        create_request(harness, files=files, maximum_files=2)


def test_byte_budget_is_enforced_before_apply(harness: Harness) -> None:
    harness.service.workspaces.provision("workspace-1")
    files = (proposal("index.html", "<html>larger than budget</html>"),)
    request = create_request(harness, files=files, maximum_total_bytes=8)
    with pytest.raises(WebsiteStagingError, match="byte budget"):
        harness.service.preview(request, files, actor="local-test")


def test_forbidden_extension_is_rejected(harness: Harness) -> None:
    harness.service.workspaces.provision("workspace-1")
    binary = WebsiteFileProposal.from_bytes(
        relative_path="payload.exe",
        media_type="application/octet-stream",
        content=b"MZ",
    )
    request = create_request(harness, files=(binary,))
    with pytest.raises(WebsiteStagingError, match="extension"):
        harness.service.preview(request, (binary,), actor="local-test")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<html><body>api_key = 'abcdefghijklmnop'</body></html>", "secret-like"),
        ("<html><body></html>", "malformed"),
        ('<html><body><img src="missing.png"></body></html>', "missing local"),
        ('<html><body><a href="file:///secret">x</a></body></html>', "file URL"),
        (
            '<html><body><form action="https://example.invalid/send"></form></body></html>',
            "external form",
        ),
        (
            '<html><head><meta http-equiv="refresh" content="0;url=/x"></head></html>',
            "meta refresh",
        ),
        ("<html><script>eval('1')</script></html>", "eval"),
        ("<html><script>new Function('x')</script></html>", "new Function"),
        (
            '<html><script src="https://example.invalid/app.js"></script></html>',
            "external executable",
        ),
        ("<html><body>#!/bin/sh\nrm everything</body></html>", "shell or installer"),
    ],
)
def test_static_security_failures_are_rejected(
    harness: Harness,
    content: str,
    message: str,
) -> None:
    harness.service.workspaces.provision("workspace-1")
    files = (proposal("index.html", content),)
    request = create_request(harness, files=files)
    with pytest.raises(WebsiteStagingError, match=message):
        harness.service.preview(request, files, actor="local-test")


def test_local_links_and_html_parse_are_verified(harness: Harness) -> None:
    _request, plan = create_plan(harness, safe_files())
    assert not plan.warnings
    assert {item.relative_path for item in plan.after_files} == {
        "about.html",
        "index.html",
        "style.css",
    }


def test_external_url_is_warning_only_and_never_called(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.service.workspaces.provision("workspace-1")
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("DNS used")),
    )
    files = (
        proposal(
            "index.html",
            '<html><body><a href="https://example.invalid/info">Info</a></body></html>',
        ),
    )
    request = create_request(harness, files=files)
    plan = harness.service.preview(request, files, actor="local-test")
    assert plan.external_urls == ("https://example.invalid/info",)
    assert any("not fetched" in warning for warning in plan.warnings)


def test_javascript_is_inventoried_but_never_executed(harness: Harness) -> None:
    harness.service.workspaces.provision("workspace-1")
    files = (
        proposal("app.js", "window.syntheticPilot = true;"),
        proposal("index.html", '<html><script src="app.js"></script></html>'),
    )
    request = create_request(harness, files=files)
    plan = harness.service.preview(request, files, actor="local-test")
    assert plan.script_files == ("app.js",)
    assert "window" not in globals()


@pytest.mark.asyncio
async def test_manifest_and_artifact_hashes_are_deterministic(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    action, execution = await apply_plan(harness, request, plan)
    assert action.status is ActionStatus.COMPLETED
    assert execution is not None
    manifest = harness.service.artifacts(request.workspace_id)
    payload = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    assert (
        manifest.manifest_sha256
        == hashlib.sha256(
            (
                json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
                + "\n"
            ).encode()
        ).hexdigest()
    )
    site = harness.service.workspaces.site_root(request.workspace_id)
    for artifact in manifest.artifacts:
        content = (site / artifact.relative_path).read_bytes()
        assert artifact.sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_extra_file_fails_static_validation(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    _action, execution = await apply_plan(harness, request, plan)
    assert execution is not None
    (
        harness.service.workspaces.site_root(request.workspace_id) / "extra.md"
    ).write_text("extra", encoding="utf-8")
    result = harness.service.validate(request.workspace_id)
    assert result.passed is False
    assert any("file set" in error for error in result.errors)


@pytest.mark.asyncio
async def test_second_apply_is_persistent_noop(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    first_action, first = await apply_plan(harness, request, plan)
    second_action, second = await apply_plan(harness, request, plan)
    assert first is not None and second is not None
    assert second_action.action_id == first_action.action_id
    assert second.no_op is True
    assert second.status.value == "noop"
    assert len(harness.action_store.list_actions(request.task_id)) == 1


@pytest.mark.asyncio
async def test_idempotency_survives_service_restart(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    first_action, first = await apply_plan(harness, request, plan)
    assert first is not None
    restarted_actions = ToolActionService(
        catalog=ToolManifestCatalog(()),
        store=harness.action_store,
        context_factory=lambda _proposal: harness.context,
        runtimes={},
        artifact_root=harness.root / "tool-artifacts",
        task_service=harness.tasks,
    )
    restarted = WebsiteStagingService(
        workspace_store=WebsiteWorkspaceStore(
            harness.staging,
            protected_roots=(harness.real_project, harness.real_vault),
        ),
        action_service=restarted_actions,
        task_service=harness.tasks,
    )
    second_action, second = await restarted.apply(
        workspace_id=request.workspace_id,
        request_id=request.request_id,
        expected_preview_hash=plan.preview_hash,
        idempotency_key=request.idempotency_key,
        actor="local-test",
        decision="allow_once",
    )
    assert second_action.action_id == first_action.action_id
    assert second is not None and second.no_op


@pytest.mark.asyncio
async def test_rollback_is_byte_identical_and_cleanup_is_complete(
    harness: Harness,
) -> None:
    request, plan = create_plan(harness, safe_files())
    _action, execution = await apply_plan(harness, request, plan)
    assert execution is not None
    rollback_action, rollback = await harness.service.rollback(
        workspace_id=request.workspace_id,
        execution_id=execution.execution_id,
        expected_manifest_hash=execution.after_manifest_sha256,
        idempotency_key=request.idempotency_key,
        actor="local-test",
        decision="allow_once",
    )
    assert rollback_action.status is ActionStatus.COMPLETED
    assert rollback is not None and rollback.byte_identical
    states, digest = scan_tree(
        harness.service.workspaces.site_root(request.workspace_id),
        maximum_files=request.maximum_files,
        maximum_total_bytes=request.maximum_total_bytes,
    )
    assert states == plan.before_files
    assert digest == plan.before_manifest_sha256
    harness.service.cleanup(request.workspace_id)
    assert not harness.service.workspaces.workspace_root(request.workspace_id).exists()
    assert not any(harness.service.workspaces.restores.iterdir())


@pytest.mark.asyncio
async def test_drift_blocks_rollback_without_overwrite(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    _action, execution = await apply_plan(harness, request, plan)
    assert execution is not None
    index = harness.service.workspaces.site_root(request.workspace_id) / "index.html"
    index.write_text("drift", encoding="utf-8")
    rollback_action, rollback = await harness.service.rollback(
        workspace_id=request.workspace_id,
        execution_id=execution.execution_id,
        expected_manifest_hash=execution.after_manifest_sha256,
        idempotency_key=request.idempotency_key,
        actor="local-test",
        decision="allow_once",
    )
    assert rollback_action.status is ActionStatus.FAILED
    assert rollback is None
    assert index.read_text(encoding="utf-8") == "drift"


@pytest.mark.asyncio
async def test_update_pilot_previews_applies_links_and_rolls_back(
    harness: Harness,
) -> None:
    original = (
        proposal(
            "index.html",
            '<html><head><link href="style.css" rel="stylesheet"></head>'
            "<body>Before</body></html>",
        ),
        proposal("style.css", "body { color: black; }"),
    )
    harness.service.workspaces.provision("workspace-update", original)
    site = harness.service.workspaces.site_root("workspace-update")
    before_states, before_hash = scan_tree(
        site,
        maximum_files=4,
        maximum_total_bytes=4096,
    )
    before = {item.relative_path: item.sha256 for item in before_states}
    changed = (
        proposal(
            "index.html",
            '<html><head><link href="style.css" rel="stylesheet"></head>'
            "<body>After</body></html>",
            before=before["index.html"],
        ),
        proposal(
            "style.css",
            "body { color: navy; }",
            before=before["style.css"],
        ),
    )
    request = create_request(
        harness,
        workspace_id="workspace-update",
        request_id="request-update",
        files=changed,
        allowed_source_files=("index.html", "style.css"),
        operation=WebsiteOperation.UPDATE_STATIC_SITE,
        overwrite=WebsiteOverwritePolicy.REPLACE_IF_UNCHANGED,
    )
    plan = harness.service.preview(request, changed, actor="local-test")
    assert {item.change.value for item in plan.file_diffs} == {"modified"}
    _action, execution = await apply_plan(harness, request, plan)
    assert execution is not None
    _rollback_action, rollback = await harness.service.rollback(
        workspace_id=request.workspace_id,
        execution_id=execution.execution_id,
        expected_manifest_hash=execution.after_manifest_sha256,
        idempotency_key=request.idempotency_key,
        actor="local-test",
        decision="allow_once",
    )
    assert rollback is not None and rollback.byte_identical
    _restored, restored_hash = scan_tree(
        site,
        maximum_files=4,
        maximum_total_bytes=4096,
    )
    assert restored_hash == before_hash


@pytest.mark.asyncio
async def test_missing_verifier_fails_closed(harness: Harness) -> None:
    request, plan = create_plan(harness, safe_files())
    runtime = harness.actions._runtimes["website.staging.mutate"]  # noqa: SLF001
    harness.actions._runtimes["website.staging.mutate"] = RegisteredToolRuntime(  # noqa: SLF001
        handler=runtime.handler,
        verifier=lambda _proposal, _output: (_ for _ in ()).throw(
            RuntimeError("verification unavailable")
        ),
    )
    action, execution = await apply_plan(harness, request, plan)
    assert action.status is ActionStatus.FAILED
    assert action.effect_known is False
    assert execution is None


@pytest.mark.asyncio
async def test_unknown_tool_effect_is_never_reported_as_success(
    harness: Harness,
) -> None:
    request, plan = create_plan(harness, safe_files())
    runtime = harness.actions._runtimes["website.staging.mutate"]  # noqa: SLF001
    harness.actions._runtimes["website.staging.mutate"] = RegisteredToolRuntime(  # noqa: SLF001
        handler=lambda _arguments: (_ for _ in ()).throw(RuntimeError("unknown")),
        verifier=runtime.verifier,
    )
    action, execution = await apply_plan(harness, request, plan)
    assert action.status is ActionStatus.FAILED
    assert action.effect_known is False
    assert execution is None


@pytest.mark.asyncio
async def test_real_project_vault_legacy_network_and_models_remain_untouched(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_before = hashlib.sha256(
        (harness.real_project / "untouched.txt").read_bytes()
    ).hexdigest()
    vault_before = hashlib.sha256(
        (harness.real_vault / "untouched.md").read_bytes()
    ).hexdigest()
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network used")),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("DNS used")),
    )
    request, plan = create_plan(harness, safe_files())
    _action, execution = await apply_plan(harness, request, plan)
    assert execution is not None
    assert (
        hashlib.sha256(
            (harness.real_project / "untouched.txt").read_bytes()
        ).hexdigest()
        == project_before
    )
    assert (
        hashlib.sha256((harness.real_vault / "untouched.md").read_bytes()).hexdigest()
        == vault_before
    )
    assert not any(name.startswith("jarvis_backend") for name in sys.modules)
    timeline = harness.tasks.timeline(request.task_id, limit=5000)
    payload = json.dumps([dict(event.payload) for event in timeline])
    assert "external_model" not in payload
    assert "codex_live" not in payload


def test_policy_cannot_lower_untrusted_risk(harness: Harness) -> None:
    raised = replace(
        harness.context,
        untrusted_risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
    )
    decision = harness.actions._policy.authorize_tool(  # noqa: SLF001
        harness.actions.catalog.get("website.staging.mutate"),
        raised,
    )
    assert decision.effective_risk is RiskLevel.DESTRUCTIVE_OR_SENSITIVE
    assert decision.status == "waiting_approval"
