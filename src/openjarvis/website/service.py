"""Canonical ToolActionService orchestration for isolated website staging."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from openjarvis.learning.evaluation import (
    ApprovalState,
    BrowserRecoveryState,
    BudgetState,
    EvidenceReference,
    EvidenceSourceKind,
    EvidenceState,
    EvidenceType,
    EvidenceVerificationState,
    ExternalEffectState,
    PolicyResult,
    TraceClassifier,
    TrustedBoundary,
    VerificationState,
    snapshot_from_runtime,
)
from openjarvis.tasks import ExecutionLane, TaskOutcome, TaskService, TaskStatus
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tools.action_service import (
    RegisteredToolRuntime,
    ToolActionError,
    ToolActionService,
)
from openjarvis.tools.actions import (
    ActionStatus,
    ParameterSource,
    ToolAction,
    ToolProposal,
    VerificationResult,
)
from openjarvis.tools.manifest import (
    IdempotencyPolicy,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
)
from openjarvis.website.models import (
    WebsiteArtifactEntry,
    WebsiteArtifactManifest,
    WebsiteChangeKind,
    WebsiteExecutionStatus,
    WebsiteFileDiff,
    WebsiteFileProposal,
    WebsiteFileState,
    WebsiteOperation,
    WebsiteOverwritePolicy,
    WebsiteRollbackRecord,
    WebsiteStagingExecution,
    WebsiteStagingPlan,
    WebsiteStagingRequest,
    WebsiteVerificationResult,
    WebsiteVerificationStatus,
    canonical_json,
    sha256_payload,
    utc_now,
)
from openjarvis.website.workspace import (
    MEDIA_TYPES,
    WebsiteStagingError,
    WebsiteWorkspaceStore,
    confined_path,
    inspect_static_content,
    read_tree,
    replace_tree_atomically,
    scan_tree,
    write_proposals_atomically,
)

WEBSITE_TOOL_ID = "website.staging.mutate"
WEBSITE_CAPABILITY = "website:stage"

WEBSITE_STAGING_MANIFEST = ToolManifest(
    tool_id=WEBSITE_TOOL_ID,
    name=WEBSITE_TOOL_ID,
    version="1.0.0",
    description="Apply or roll back one hash-bound isolated static website plan.",
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["apply", "rollback"]},
            "workspace_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "request_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "binding_hash": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
            "execution_id": {"type": "string", "maxLength": 256},
        },
        "required": [
            "operation",
            "workspace_id",
            "request_id",
            "binding_hash",
            "execution_id",
        ],
        "additionalProperties": False,
    },
    output_schema={"type": "object"},
    capability=WEBSITE_CAPABILITY,
    risk_level=RiskLevel.REVERSIBLE_WORKSPACE,
    allowed_lanes=(ExecutionLane.MODEL,),
    supported_platforms=("windows", "linux", "darwin"),
    timeout=30,
    max_retries=0,
    idempotency_policy=IdempotencyPolicy.KEY_REQUIRED,
    side_effect_class=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
    verification_strategy="static manifest and hash-bound postcondition verification",
    undo_strategy="byte-identical restore copy with after-hash drift guard",
    required_approval=True,
    network_policy=NetworkPolicy.DENY,
    secret_policy=SecretPolicy.REJECT,
    log_redaction_policy="relative paths and hashes only",
)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _states_from_content(
    content: dict[str, bytes],
) -> tuple[tuple[WebsiteFileState, ...], str]:
    states = tuple(
        WebsiteFileState(
            relative_path=relative,
            size_bytes=len(value),
            sha256=hashlib.sha256(value).hexdigest(),
            media_type=MEDIA_TYPES[Path(relative).suffix.casefold()],
        )
        for relative, value in sorted(
            content.items(), key=lambda item: item[0].casefold()
        )
    )
    return states, sha256_payload([item.model_dump(mode="json") for item in states])


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _build_plan(
    *,
    request: WebsiteStagingRequest,
    proposals: tuple[WebsiteFileProposal, ...],
    before_files: tuple[WebsiteFileState, ...],
    after_files: tuple[WebsiteFileState, ...],
    diffs: tuple[WebsiteFileDiff, ...],
    before_hash: str,
    after_hash: str,
    warnings: tuple[str, ...],
    external_urls: tuple[str, ...],
    script_files: tuple[str, ...],
) -> WebsiteStagingPlan:
    created_at = request.created_at
    payload = {
        "plan_id": f"plan_{request.request_hash[:32]}",
        "request": request.model_dump(mode="json"),
        "proposals": [item.model_dump(mode="json") for item in proposals],
        "before_files": [item.model_dump(mode="json") for item in before_files],
        "after_files": [item.model_dump(mode="json") for item in after_files],
        "file_diffs": [item.model_dump(mode="json") for item in diffs],
        "before_manifest_sha256": before_hash,
        "predicted_manifest_sha256": after_hash,
        "risk_level": int(RiskLevel.REVERSIBLE_WORKSPACE),
        "warnings": list(warnings),
        "external_urls": list(external_urls),
        "script_files": list(script_files),
        "predicted_total_bytes": sum(item.size_bytes for item in after_files),
        "created_at": _json_datetime(created_at),
    }
    return WebsiteStagingPlan(**payload, preview_hash=sha256_payload(payload))


def _build_manifest(
    *,
    plan: WebsiteStagingPlan,
    states: tuple[WebsiteFileState, ...],
    warnings_by_file: dict[str, tuple[str, ...]],
) -> WebsiteArtifactManifest:
    before = {item.relative_path: item.sha256 for item in plan.before_files}
    proposed = {item.relative_path for item in plan.proposals}
    artifacts: list[WebsiteArtifactEntry] = []
    for state in states:
        prior = before.get(state.relative_path)
        change = (
            WebsiteChangeKind.CREATED
            if prior is None
            else WebsiteChangeKind.UNCHANGED
            if prior == state.sha256
            else WebsiteChangeKind.MODIFIED
        )
        item_warnings = warnings_by_file.get(state.relative_path, ())
        artifacts.append(
            WebsiteArtifactEntry(
                artifact_id=(
                    "artifact_"
                    + hashlib.sha256(
                        (
                            plan.request.request_id
                            + "\n"
                            + state.relative_path
                            + "\n"
                            + state.sha256
                        ).encode("utf-8")
                    ).hexdigest()[:32]
                ),
                workspace_id=plan.request.workspace_id,
                request_id=plan.request.request_id,
                task_id=plan.request.task_id,
                relative_path=state.relative_path,
                media_type=state.media_type,
                size_bytes=state.size_bytes,
                sha256=state.sha256,
                source_class=(
                    "website_proposal"
                    if state.relative_path in proposed
                    else "synthetic_fixture"
                ),
                created_or_modified=change,
                verification_status=(
                    WebsiteVerificationStatus.WARNING
                    if item_warnings
                    else WebsiteVerificationStatus.PASSED
                ),
                warnings=item_warnings,
                created_at=plan.request.created_at,
            )
        )
    payload = {
        "workspace_id": plan.request.workspace_id,
        "request_id": plan.request.request_id,
        "task_id": plan.request.task_id,
        "artifacts": [item.model_dump(mode="json") for item in artifacts],
        "created_at": _json_datetime(plan.request.created_at),
    }
    return WebsiteArtifactManifest(**payload, manifest_sha256=sha256_payload(payload))


def _build_verification(
    *,
    plan: WebsiteStagingPlan,
    states: tuple[WebsiteFileState, ...],
    manifest_hash: str,
    errors: tuple[str, ...],
    warnings: tuple[str, ...],
) -> WebsiteVerificationResult:
    status = (
        WebsiteVerificationStatus.FAILED
        if errors
        else WebsiteVerificationStatus.WARNING
        if warnings
        else WebsiteVerificationStatus.PASSED
    )
    payload = {
        "workspace_id": plan.request.workspace_id,
        "request_id": plan.request.request_id,
        "status": status.value,
        "passed": status is WebsiteVerificationStatus.PASSED,
        "file_count": len(states),
        "total_bytes": sum(item.size_bytes for item in states),
        "manifest_sha256": manifest_hash,
        "errors": list(errors),
        "warnings": list(warnings),
        "checked_at": _json_datetime(plan.request.created_at),
    }
    return WebsiteVerificationResult(
        **payload,
        verification_hash=sha256_payload(payload),
    )


class WebsiteStagingService:
    """Own preview, canonical action dispatch, verification, and rollback."""

    def __init__(
        self,
        *,
        workspace_store: WebsiteWorkspaceStore,
        action_service: ToolActionService,
        task_service: TaskService,
    ) -> None:
        if action_service is None:
            raise WebsiteStagingError("ToolActionService is required")
        self.workspaces = workspace_store
        self.actions = action_service
        self.tasks = task_service
        self.actions.register_runtime(
            WEBSITE_STAGING_MANIFEST,
            RegisteredToolRuntime(
                handler=self._handle_tool,
                verifier=self._verify_tool,
            ),
        )

    def preview(
        self,
        request: WebsiteStagingRequest,
        proposals: tuple[WebsiteFileProposal, ...],
        *,
        actor: str,
    ) -> WebsiteStagingPlan:
        """Create metadata-only preview state without changing website files."""

        if request.operation not in {
            WebsiteOperation.CREATE_STATIC_SITE,
            WebsiteOperation.UPDATE_STATIC_SITE,
            WebsiteOperation.PREVIEW_DIFF,
            WebsiteOperation.VALIDATE_STATIC_SITE,
            WebsiteOperation.PACKAGE_ARTIFACT,
        }:
            raise WebsiteStagingError("operation is not valid for preview")
        self._validate_task(request)
        site = self.workspaces.site_root(request.workspace_id)
        before_files, before_hash = scan_tree(
            site,
            maximum_files=request.maximum_files,
            maximum_total_bytes=request.maximum_total_bytes,
        )
        if (
            tuple(item.relative_path for item in before_files)
            != request.allowed_source_files
        ):
            raise WebsiteStagingError("allowed source files do not match the workspace")
        ordered = tuple(
            sorted(proposals, key=lambda item: item.relative_path.casefold())
        )
        if ordered != proposals:
            raise WebsiteStagingError("file proposals must be canonically sorted")
        if (
            tuple(item.relative_path for item in proposals)
            != request.requested_output_files
        ):
            raise WebsiteStagingError(
                "file proposals do not match requested output files"
            )
        expected_types = {
            item.relative_path: item.media_type for item in request.expected_file_types
        }
        current = {item.relative_path: item for item in before_files}
        content = read_tree(site, before_files)
        for proposal in proposals:
            if expected_types[proposal.relative_path] != proposal.media_type:
                raise WebsiteStagingError("proposal media type differs from request")
            expected_media = MEDIA_TYPES.get(
                Path(proposal.relative_path).suffix.casefold()
            )
            if expected_media != proposal.media_type:
                raise WebsiteStagingError("proposal media type differs from extension")
            existing = current.get(proposal.relative_path)
            if existing is None:
                if proposal.expected_before_sha256 is not None:
                    raise WebsiteStagingError(
                        "new file declares an unexpected before hash"
                    )
            else:
                if request.overwrite_policy is WebsiteOverwritePolicy.DENY:
                    raise WebsiteStagingError(
                        "overwrite policy forbids an existing target"
                    )
                if proposal.expected_before_sha256 != existing.sha256:
                    raise WebsiteStagingError("proposal before hash does not match")
            content[proposal.relative_path] = proposal.content_bytes()
        after_files, after_hash = _states_from_content(content)
        if len(after_files) > request.maximum_files:
            raise WebsiteStagingError("website file budget exceeded")
        if sum(item.size_bytes for item in after_files) > request.maximum_total_bytes:
            raise WebsiteStagingError("website byte budget exceeded")
        expected_after = set(request.allowed_source_files) | set(
            request.requested_output_files
        )
        if {item.relative_path for item in after_files} != expected_after:
            raise WebsiteStagingError("predicted website contains unexpected files")
        inspection = inspect_static_content(content)
        if inspection.errors:
            raise WebsiteStagingError("; ".join(inspection.errors))
        diffs = tuple(
            WebsiteFileDiff(
                relative_path=item.relative_path,
                change=(
                    WebsiteChangeKind.CREATED
                    if item.relative_path not in current
                    else WebsiteChangeKind.UNCHANGED
                    if current[item.relative_path].sha256 == item.sha256
                    else WebsiteChangeKind.MODIFIED
                ),
                before_sha256=(
                    current[item.relative_path].sha256
                    if item.relative_path in current
                    else None
                ),
                after_sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
            for item in after_files
            if item.relative_path in request.requested_output_files
        )
        plan = _build_plan(
            request=request,
            proposals=proposals,
            before_files=before_files,
            after_files=after_files,
            diffs=diffs,
            before_hash=before_hash,
            after_hash=after_hash,
            warnings=inspection.warnings,
            external_urls=inspection.external_urls,
            script_files=inspection.script_files,
        )
        self.workspaces.save_preview(plan.preview_hash, plan.model_dump_json().encode())
        record = self._record(request.workspace_id)
        record.update(
            {
                "schema_version": "1.0",
                "workspace_id": request.workspace_id,
                "plan": plan.model_dump(mode="json"),
            }
        )
        self._save_record(request.workspace_id, record)
        task = self.tasks.get(request.task_id)
        assert task is not None
        if task.status is TaskStatus.PENDING:
            self.tasks.transition(
                request.task_id,
                TaskStatus.RUNNING,
                component="website_staging",
                cause="website_preview",
                idempotency_key=f"website-preview-running:{request.idempotency_key}",
                active_thread_id=f"website-{request.task_id}",
                active_turn_id=f"preview-{request.request_id}",
            )
        self._audit(
            request,
            event_type="website.staging.previewed",
            source=f"website-preview:{request.request_id}:{request.idempotency_key}",
            actor=actor,
            payload={
                "preview_hash": plan.preview_hash,
                "before_manifest_sha256": plan.before_manifest_sha256,
                "predicted_manifest_sha256": plan.predicted_manifest_sha256,
                "risk_level": plan.risk_level,
                "warning_count": len(plan.warnings),
            },
        )
        return plan

    async def apply(
        self,
        *,
        workspace_id: str,
        request_id: str,
        expected_preview_hash: str,
        idempotency_key: str,
        actor: str,
        decision: Literal["request_approval", "allow_once", "deny"],
    ) -> tuple[ToolAction, WebsiteStagingExecution | None]:
        plan = self._load_plan(expected_preview_hash)
        if (
            plan.request.workspace_id != workspace_id
            or plan.request.request_id != request_id
        ):
            raise WebsiteStagingError("preview identity does not match apply")
        prior_record = self._record(workspace_id)
        prior_execution_value = prior_record.get("execution")
        if prior_execution_value:
            prior_execution = WebsiteStagingExecution.model_validate(
                prior_execution_value
            )
            prior_action = self.actions.store.get_action(prior_execution.action_id)
            prior_proposal = (
                self.actions.store.get_proposal(prior_action.proposal_id)
                if prior_action is not None
                else None
            )
            if (
                prior_action is not None
                and prior_action.status is ActionStatus.COMPLETED
                and prior_proposal is not None
                and prior_proposal.idempotency_key == f"{idempotency_key}:apply"
                and prior_execution.preview_hash == expected_preview_hash
            ):
                return prior_action, prior_execution.model_copy(
                    update={
                        "status": WebsiteExecutionStatus.NOOP,
                        "no_op": True,
                    }
                )
        current_files, current_hash = scan_tree(
            self.workspaces.site_root(workspace_id),
            maximum_files=plan.request.maximum_files,
            maximum_total_bytes=plan.request.maximum_total_bytes,
        )
        if (
            current_hash != plan.before_manifest_sha256
            or current_files != plan.before_files
        ):
            raise WebsiteStagingError("before-manifest CAS failed")
        proposal = self._tool_proposal(
            plan=plan,
            operation="apply",
            binding_hash=expected_preview_hash,
            execution_id="",
            idempotency_key=f"{idempotency_key}:apply",
        )
        self._require_bound_action_context(proposal)
        try:
            action = self.actions.create(proposal)
            action = await self._decide(action, decision, idempotency_key)
        except ToolActionError as exc:
            raise WebsiteStagingError(str(exc)) from exc
        execution = None
        if action.status is ActionStatus.COMPLETED:
            execution = self._finalize_apply(action, plan, actor=actor)
        elif action.status in {ActionStatus.FAILED, ActionStatus.DENIED}:
            self._fail_task(plan.request, action)
        return action, execution

    def validate(self, workspace_id: str) -> WebsiteVerificationResult:
        record = self._record(workspace_id)
        if "plan" not in record:
            raise WebsiteStagingError("workspace has no preview plan")
        plan = WebsiteStagingPlan.model_validate(record["plan"])
        site = self.workspaces.site_root(workspace_id)
        states, digest = scan_tree(
            site,
            maximum_files=plan.request.maximum_files,
            maximum_total_bytes=plan.request.maximum_total_bytes,
        )
        content = read_tree(site, states)
        inspection = inspect_static_content(content)
        expected = {item.relative_path for item in plan.after_files}
        actual = {item.relative_path for item in states}
        errors = list(inspection.errors)
        if actual != expected:
            errors.append("workspace files differ from the planned file set")
        if digest != plan.predicted_manifest_sha256:
            errors.append("workspace manifest differs from the predicted manifest")
        return _build_verification(
            plan=plan,
            states=states,
            manifest_hash=digest,
            errors=tuple(sorted(set(errors))),
            warnings=inspection.warnings,
        )

    async def rollback(
        self,
        *,
        workspace_id: str,
        execution_id: str,
        expected_manifest_hash: str,
        idempotency_key: str,
        actor: str,
        decision: Literal["request_approval", "allow_once", "deny"],
    ) -> tuple[ToolAction, WebsiteRollbackRecord | None]:
        record = self._record(workspace_id)
        execution_value = record.get("execution")
        plan_value = record.get("plan")
        if not execution_value or not plan_value:
            raise WebsiteStagingError("workspace has no rollbackable execution")
        execution = WebsiteStagingExecution.model_validate(execution_value)
        plan = WebsiteStagingPlan.model_validate(plan_value)
        if execution.execution_id != execution_id:
            raise WebsiteStagingError("execution identity does not match rollback")
        if execution.after_manifest_sha256 != expected_manifest_hash:
            raise WebsiteStagingError("expected manifest does not match execution")
        proposal = self._tool_proposal(
            plan=plan,
            operation="rollback",
            binding_hash=expected_manifest_hash,
            execution_id=execution_id,
            idempotency_key=f"{idempotency_key}:rollback",
        )
        self._require_bound_action_context(proposal)
        try:
            action = self.actions.create(proposal)
            action = await self._decide(action, decision, idempotency_key)
        except ToolActionError as exc:
            raise WebsiteStagingError(str(exc)) from exc
        rollback_record = None
        if action.status is ActionStatus.COMPLETED:
            rollback_record = self._finalize_rollback(action, plan, execution, actor)
        return action, rollback_record

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        record = self._record(workspace_id)
        plan_value = record.get("plan")
        if plan_value:
            plan = WebsiteStagingPlan.model_validate(plan_value)
            public = plan.model_dump(mode="json")
            public["proposals"] = [
                {
                    "relative_path": item.relative_path,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "proposed_sha256": item.proposed_sha256,
                    "expected_before_sha256": item.expected_before_sha256,
                }
                for item in plan.proposals
            ]
            record = dict(record)
            record["plan"] = public
        return record

    def artifacts(self, workspace_id: str) -> WebsiteArtifactManifest:
        value = self._record(workspace_id).get("artifact_manifest")
        if not value:
            raise WebsiteStagingError("workspace has no artifact manifest")
        return WebsiteArtifactManifest.model_validate(value)

    def cleanup(self, workspace_id: str) -> None:
        record = self._record(workspace_id)
        execution = record.get("execution")
        if execution:
            restore_id = WebsiteStagingExecution.model_validate(execution).restore_id
            self.workspaces.remove_restore(restore_id)
        self.workspaces.cleanup_workspace(workspace_id)

    async def _decide(
        self,
        action: ToolAction,
        decision: str,
        decision_id: str,
    ) -> ToolAction:
        if action.status is ActionStatus.COMPLETED:
            return action
        if decision == "request_approval":
            return action
        if action.status is not ActionStatus.WAITING_APPROVAL:
            return action
        bound_decision_id = f"{decision_id}:{action.action_id}"
        if decision == "deny":
            return self.actions.deny(
                action.action_id,
                decision_id=bound_decision_id,
            )
        return await self.actions.approve(
            action.action_id,
            decision_id=bound_decision_id,
        )

    def _handle_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if arguments["operation"] == "apply":
                plan = self._load_plan(arguments["binding_hash"])
                if (
                    plan.request.workspace_id != arguments["workspace_id"]
                    or plan.request.request_id != arguments["request_id"]
                ):
                    raise WebsiteStagingError("tool binding differs from preview")
                return self._apply_bound_plan(plan)
            return self._rollback_bound_execution(arguments)
        except WebsiteStagingError as exc:
            return {"ok": False, "error": str(exc), "effect_known": True}

    def _apply_bound_plan(self, plan: WebsiteStagingPlan) -> dict[str, Any]:
        request = plan.request
        site = self.workspaces.site_root(request.workspace_id)
        before_files, before_hash = scan_tree(
            site,
            maximum_files=request.maximum_files,
            maximum_total_bytes=request.maximum_total_bytes,
        )
        if (
            before_hash != plan.before_manifest_sha256
            or before_files != plan.before_files
        ):
            raise WebsiteStagingError("before-manifest CAS failed")
        restore_id = f"restore_{plan.preview_hash[:32]}"
        restore = self.workspaces.create_restore(restore_id, site)
        restore_files, restore_hash = scan_tree(
            restore,
            maximum_files=request.maximum_files,
            maximum_total_bytes=request.maximum_total_bytes,
        )
        if restore_hash != before_hash or restore_files != before_files:
            self.workspaces.remove_restore(restore_id)
            raise WebsiteStagingError("restore copy did not verify")
        try:
            write_proposals_atomically(site, plan.proposals)
            after_files, after_hash = scan_tree(
                site,
                maximum_files=request.maximum_files,
                maximum_total_bytes=request.maximum_total_bytes,
            )
            if (
                after_hash != plan.predicted_manifest_sha256
                or after_files != plan.after_files
            ):
                raise WebsiteStagingError("after-manifest differs from preview")
            content = read_tree(site, after_files)
            inspection = inspect_static_content(content)
            expected = set(request.allowed_source_files) | set(
                request.requested_output_files
            )
            errors = list(inspection.errors)
            if {item.relative_path for item in after_files} != expected:
                errors.append("website contains an unexpected file")
            manifest = _build_manifest(
                plan=plan,
                states=after_files,
                warnings_by_file=inspection.warnings_by_file,
            )
            verification = _build_verification(
                plan=plan,
                states=after_files,
                manifest_hash=after_hash,
                errors=tuple(sorted(set(errors))),
                warnings=inspection.warnings,
            )
        except Exception as exc:
            self._restore_after_failed_apply(plan, restore)
            self.workspaces.remove_restore(restore_id)
            if isinstance(exc, WebsiteStagingError):
                raise
            raise WebsiteStagingError("website apply failed and was restored") from exc
        result = {
            "ok": verification.passed,
            "workspace_id": request.workspace_id,
            "request_id": request.request_id,
            "execution_id": f"execution_{plan.preview_hash[:32]}",
            "restore_id": restore_id,
            "before_manifest_sha256": before_hash,
            "after_manifest_sha256": after_hash,
            "artifact_manifest": manifest.model_dump(mode="json"),
            "verification": verification.model_dump(mode="json"),
            "no_op": before_hash == after_hash,
            "effect_known": True,
        }
        record = self._record(request.workspace_id)
        record["apply_result"] = result
        record["artifact_manifest"] = result["artifact_manifest"]
        record["verification"] = result["verification"]
        self._save_record(request.workspace_id, record)
        return result

    def _restore_after_failed_apply(
        self,
        plan: WebsiteStagingPlan,
        restore: Path,
    ) -> None:
        workspace_root = self.workspaces.workspace_root(plan.request.workspace_id)
        replacement = workspace_root / f".failed-apply-{uuid.uuid4().hex}"
        replacement.mkdir()
        try:
            self._copy_verified_tree(restore, replacement, plan.request)
            replace_tree_atomically(
                workspace_root / "site",
                replacement,
                owner=workspace_root,
            )
        finally:
            if replacement.exists():
                shutil.rmtree(replacement)

    def _rollback_bound_execution(self, arguments: dict[str, Any]) -> dict[str, Any]:
        record = self._record(arguments["workspace_id"])
        plan_value = record.get("plan")
        execution_value = record.get("execution")
        if not plan_value or not execution_value:
            raise WebsiteStagingError("workspace has no rollbackable execution")
        plan = WebsiteStagingPlan.model_validate(plan_value)
        execution = WebsiteStagingExecution.model_validate(execution_value)
        if (
            execution.execution_id != arguments["execution_id"]
            or execution.after_manifest_sha256 != arguments["binding_hash"]
            or execution.request_id != arguments["request_id"]
        ):
            raise WebsiteStagingError("rollback binding differs from execution")
        site = self.workspaces.site_root(plan.request.workspace_id)
        current_files, current_hash = scan_tree(
            site,
            maximum_files=plan.request.maximum_files,
            maximum_total_bytes=plan.request.maximum_total_bytes,
        )
        if (
            current_hash != execution.after_manifest_sha256
            or current_files != plan.after_files
        ):
            return {
                "ok": False,
                "error": "rollback blocked because the website drifted",
                "drift_detected": True,
                "effect_known": True,
            }
        restore = self.workspaces.restores / execution.restore_id / "site"
        if not restore.is_dir():
            raise WebsiteStagingError("restore copy is unavailable")
        workspace_root = self.workspaces.workspace_root(plan.request.workspace_id)
        replacement = workspace_root / f".rollback-{uuid.uuid4().hex}"
        replacement.mkdir()
        try:
            self._copy_verified_tree(restore, replacement, plan.request)
            restored_files, restored_hash = scan_tree(
                replacement,
                maximum_files=plan.request.maximum_files,
                maximum_total_bytes=plan.request.maximum_total_bytes,
            )
            if (
                restored_hash != execution.before_manifest_sha256
                or restored_files != plan.before_files
            ):
                raise WebsiteStagingError("rollback restore copy did not verify")
            replace_tree_atomically(site, replacement, owner=workspace_root)
            final_files, final_hash = scan_tree(
                site,
                maximum_files=plan.request.maximum_files,
                maximum_total_bytes=plan.request.maximum_total_bytes,
            )
            if final_hash != restored_hash or final_files != restored_files:
                raise WebsiteStagingError("rollback final verification failed")
        finally:
            if replacement.exists():
                shutil.rmtree(replacement)
        self.workspaces.remove_restore(execution.restore_id)
        result = {
            "ok": True,
            "workspace_id": plan.request.workspace_id,
            "request_id": plan.request.request_id,
            "execution_id": execution.execution_id,
            "expected_after_manifest_sha256": execution.after_manifest_sha256,
            "restored_manifest_sha256": execution.before_manifest_sha256,
            "byte_identical": True,
            "drift_detected": False,
            "restore_probe_removed": True,
            "effect_known": True,
        }
        record["rollback_result"] = result
        self._save_record(plan.request.workspace_id, record)
        return result

    @staticmethod
    def _copy_verified_tree(
        source: Path,
        destination: Path,
        request: WebsiteStagingRequest,
    ) -> None:
        states, _digest = scan_tree(
            source,
            maximum_files=request.maximum_files,
            maximum_total_bytes=request.maximum_total_bytes,
        )
        for relative, content in read_tree(source, states).items():
            target = confined_path(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def _verify_tool(
        self,
        proposal: ToolProposal,
        output: Any,
    ) -> VerificationResult:
        if not isinstance(output, dict) or output.get("ok") is not True:
            return VerificationResult(
                passed=False,
                observed_state=(
                    str(output.get("error", "unknown website effect"))
                    if isinstance(output, dict)
                    else "invalid website tool output"
                ),
                expected_state="hash-bound website mutation verified",
            )
        if proposal.arguments["operation"] == "rollback":
            passed = bool(
                output.get("byte_identical")
                and output.get("restore_probe_removed")
                and not output.get("drift_detected")
            )
            return VerificationResult(
                passed=passed,
                observed_state="byte-identical rollback"
                if passed
                else "rollback unverified",
                expected_state="byte-identical rollback",
            )
        verification = WebsiteVerificationResult.model_validate(output["verification"])
        manifest = WebsiteArtifactManifest.model_validate(output["artifact_manifest"])
        return VerificationResult(
            passed=verification.passed,
            observed_state=verification.status.value,
            expected_state="passed",
            artifact_ids=tuple(item.artifact_id for item in manifest.artifacts),
        )

    def _tool_proposal(
        self,
        *,
        plan: WebsiteStagingPlan,
        operation: str,
        binding_hash: str,
        execution_id: str,
        idempotency_key: str,
    ) -> ToolProposal:
        arguments = {
            "operation": operation,
            "workspace_id": plan.request.workspace_id,
            "request_id": plan.request.request_id,
            "binding_hash": binding_hash,
            "execution_id": execution_id,
        }
        return ToolProposal(
            task_id=plan.request.task_id,
            session_id=plan.request.session_id,
            correlation_id=plan.request.correlation_id,
            thread_id=f"website-{plan.request.task_id}",
            turn_id=f"website-{plan.request.request_id}",
            item_id=f"website-{operation}-{plan.request.request_id}",
            tool_id=WEBSITE_TOOL_ID,
            arguments=arguments,
            expected_result=f"verified isolated website {operation}",
            expected_side_effect=SideEffectClass.REVERSIBLE_LOCAL_WRITE,
            risk_level=RiskLevel.REVERSIBLE_WORKSPACE,
            capability=WEBSITE_CAPABILITY,
            target=f"isolated-workspace:{plan.request.workspace_id}",
            verification_plan=(
                "compare manifest, artifact hashes, and static verification"
            ),
            undo_plan="hash-bound byte-identical restore copy",
            idempotency_key=idempotency_key,
            timeout_seconds=30,
            rationale="explicit local website staging pilot request",
            parameter_sources={key: ParameterSource.SYSTEM for key in arguments},
            created_at=plan.request.created_at.isoformat(),
        )

    def _require_bound_action_context(self, proposal: ToolProposal) -> None:
        if not self.actions.runtime_available(WEBSITE_TOOL_ID):
            raise WebsiteStagingError("ToolActionService runtime is unavailable")
        context = self.actions.policy_context(proposal)
        root = self.workspaces.root.resolve(strict=True)
        allowed = tuple(path.resolve(strict=False) for path in context.allowed_roots)
        if not any(_inside(root, candidate) for candidate in allowed):
            raise WebsiteStagingError("tool policy does not bind the staging root")

    def _load_plan(self, preview_hash: str) -> WebsiteStagingPlan:
        try:
            plan = WebsiteStagingPlan.model_validate_json(
                self.workspaces.load_preview(preview_hash)
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise WebsiteStagingError("preview record is invalid") from exc
        if plan.preview_hash != preview_hash:
            raise WebsiteStagingError("preview hash binding failed")
        return plan

    def _validate_task(self, request: WebsiteStagingRequest) -> None:
        task = self.tasks.get(request.task_id)
        if task is None:
            raise WebsiteStagingError("website request references an unknown task")
        if (
            task.session_id != request.session_id
            or task.correlation_id != request.correlation_id
        ):
            raise WebsiteStagingError("website request identity differs from task")
        if task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            raise WebsiteStagingError("task is not open for website staging")

    def _finalize_apply(
        self,
        action: ToolAction,
        plan: WebsiteStagingPlan,
        *,
        actor: str,
    ) -> WebsiteStagingExecution:
        record = self._record(plan.request.workspace_id)
        existing = record.get("execution")
        if existing:
            return WebsiteStagingExecution.model_validate(existing)
        raw = record.get("apply_result")
        if not raw:
            raise WebsiteStagingError("completed action has no website result")
        verification = WebsiteVerificationResult.model_validate(raw["verification"])
        manifest = WebsiteArtifactManifest.model_validate(raw["artifact_manifest"])
        if not verification.passed:
            raise WebsiteStagingError("website verification did not fully pass")
        execution = WebsiteStagingExecution(
            execution_id=raw["execution_id"],
            workspace_id=plan.request.workspace_id,
            request_id=plan.request.request_id,
            task_id=plan.request.task_id,
            action_id=action.action_id,
            preview_hash=plan.preview_hash,
            before_manifest_sha256=raw["before_manifest_sha256"],
            after_manifest_sha256=raw["after_manifest_sha256"],
            artifact_manifest_sha256=manifest.manifest_sha256,
            verification_hash=verification.verification_hash,
            restore_id=raw["restore_id"],
            status=(
                WebsiteExecutionStatus.NOOP
                if raw["no_op"]
                else WebsiteExecutionStatus.COMPLETED
            ),
            no_op=bool(raw["no_op"]),
            created_at=plan.request.created_at,
        )
        record["execution"] = execution.model_dump(mode="json")
        self._save_record(plan.request.workspace_id, record)
        manifest_artifact = self.tasks.store.save_artifact(
            artifact_id=f"website-manifest-{manifest.manifest_sha256[:24]}",
            task_id=plan.request.task_id,
            kind="website_artifact_manifest",
            media_type="application/json",
            content=canonical_json(manifest.model_dump(mode="json")),
            metadata={
                "workspace_id": plan.request.workspace_id,
                "manifest_sha256": manifest.manifest_sha256,
            },
        )
        verification_artifact = self.tasks.store.save_artifact(
            artifact_id=f"website-verification-{verification.verification_hash[:24]}",
            task_id=plan.request.task_id,
            kind="website_verification",
            media_type="application/json",
            content=canonical_json(verification.model_dump(mode="json")),
            metadata={
                "workspace_id": plan.request.workspace_id,
                "verification_hash": verification.verification_hash,
            },
        )
        task = self.tasks.get(plan.request.task_id)
        assert task is not None
        if task.status is TaskStatus.RUNNING:
            task = self.tasks.transition(
                task.task_id,
                TaskStatus.DONE,
                outcome=TaskOutcome.COMPLETED,
                result="isolated website staging verified",
                component="website_staging",
                cause="website_apply_verified",
                idempotency_key=f"website-done:{action.action_id}",
            )
        approvals = (
            (self.tasks.store.get_approval(action.approval_id),)
            if action.approval_id
            else ()
        )
        approvals = tuple(item for item in approvals if item is not None)
        evidence = EvidenceReference(
            evidence_id=f"evidence-{manifest.manifest_sha256[:24]}",
            evidence_type=EvidenceType.ARTIFACT_DIGEST,
            source_kind=EvidenceSourceKind.ARTIFACT,
            source_id=manifest_artifact.artifact_id,
            digest=manifest.manifest_sha256,
            verification_state=EvidenceVerificationState.VERIFIED,
            trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
            created_at=plan.request.created_at,
        )
        snapshot = snapshot_from_runtime(
            task,
            trace_id=f"website-trace-{execution.execution_id}",
            task_type="website_staging",
            requested_goal="verify an isolated local static website staging plan",
            events=self.tasks.timeline(task.task_id, limit=5000),
            tool_actions=self.actions.store.list_actions(task.task_id),
            approval_records=approvals,
            evidence_state=EvidenceState.SUFFICIENT,
            evidence_references=(evidence,),
            relevant_artifact_ids=(
                manifest_artifact.artifact_id,
                verification_artifact.artifact_id,
            ),
            verification_state=VerificationState.PASSED,
            approval_state=ApprovalState.APPROVED,
            policy_result=PolicyResult.ALLOWED,
            browser_recovery_state=BrowserRecoveryState.NOT_APPLICABLE,
            budget_state=BudgetState.WITHIN_LIMITS,
            external_effect_state=ExternalEffectState.KNOWN,
        )
        evaluation = TraceClassifier().evaluate(snapshot)
        self.tasks.store.save_artifact(
            artifact_id=f"website-evaluation-{evaluation.evaluation_hash[:24]}",
            task_id=task.task_id,
            kind="trace_evaluation",
            media_type="application/json",
            content=canonical_json(evaluation.model_dump(mode="json")),
            metadata={"evaluation_hash": evaluation.evaluation_hash},
        )
        execution = execution.model_copy(
            update={"trace_evaluation_hash": evaluation.evaluation_hash}
        )
        record["execution"] = execution.model_dump(mode="json")
        record["trace_evaluation"] = evaluation.model_dump(mode="json")
        self._save_record(plan.request.workspace_id, record)
        self._audit(
            plan.request,
            event_type="website.staging.verified",
            source=f"website-verified:{action.action_id}",
            actor=actor,
            payload={
                "action_id": action.action_id,
                "manifest_sha256": manifest.manifest_sha256,
                "verification_hash": verification.verification_hash,
                "evaluation_hash": evaluation.evaluation_hash,
                "no_op": execution.no_op,
            },
            action_id=action.action_id,
            artifact_id=manifest_artifact.artifact_id,
        )
        return execution

    def _finalize_rollback(
        self,
        action: ToolAction,
        plan: WebsiteStagingPlan,
        execution: WebsiteStagingExecution,
        actor: str,
    ) -> WebsiteRollbackRecord:
        record = self._record(plan.request.workspace_id)
        existing = record.get("rollback")
        if existing:
            return WebsiteRollbackRecord.model_validate(existing)
        raw = record.get("rollback_result")
        if not raw:
            raise WebsiteStagingError("completed action has no rollback result")
        payload = {
            "rollback_id": f"rollback_{action.action_id[-32:]}",
            "workspace_id": plan.request.workspace_id,
            "request_id": plan.request.request_id,
            "task_id": plan.request.task_id,
            "action_id": action.action_id,
            "execution_id": execution.execution_id,
            "expected_after_manifest_sha256": raw["expected_after_manifest_sha256"],
            "restored_manifest_sha256": raw["restored_manifest_sha256"],
            "byte_identical": raw["byte_identical"],
            "drift_detected": raw["drift_detected"],
            "restore_probe_removed": raw["restore_probe_removed"],
            "created_at": _json_datetime(utc_now()),
        }
        rollback = WebsiteRollbackRecord(
            **payload,
            record_hash=sha256_payload(payload),
        )
        record["rollback"] = rollback.model_dump(mode="json")
        record["execution"] = execution.model_copy(
            update={"status": WebsiteExecutionStatus.ROLLED_BACK}
        ).model_dump(mode="json")
        self._save_record(plan.request.workspace_id, record)
        self._audit(
            plan.request,
            event_type="website.staging.rolled_back",
            source=f"website-rollback:{action.action_id}",
            actor=actor,
            payload={
                "action_id": action.action_id,
                "record_hash": rollback.record_hash,
                "byte_identical": rollback.byte_identical,
            },
            action_id=action.action_id,
        )
        return rollback

    def _fail_task(self, request: WebsiteStagingRequest, action: ToolAction) -> None:
        task = self.tasks.get(request.task_id)
        if task and task.status is TaskStatus.RUNNING:
            self.tasks.transition(
                task.task_id,
                TaskStatus.FAILED,
                outcome=TaskOutcome.FAILED,
                error_category="website_staging_failed",
                component="website_staging",
                cause=action.status.value,
                idempotency_key=f"website-failed:{action.action_id}",
            )

    def _audit(
        self,
        request: WebsiteStagingRequest,
        *,
        event_type: str,
        source: str,
        actor: str,
        payload: dict[str, Any],
        action_id: str | None = None,
        artifact_id: str | None = None,
    ) -> None:
        event, inserted = self.tasks.store.append_event(
            task_id=request.task_id,
            source_event_id=source,
            event_type=event_type,
            occurred_at=utc_now().isoformat(),
            cause="explicit_local_actor",
            component="website_staging",
            thread_id=f"website-{request.task_id}",
            turn_id=f"website-{request.request_id}",
            item_id=f"website-{request.request_id}",
            action_id=action_id,
            artifact_id=artifact_id,
            payload={"actor": actor, **payload},
        )
        if inserted:
            self.tasks.project_committed(event)

    def _record(self, workspace_id: str) -> dict[str, Any]:
        raw = self.workspaces.load_workspace_record(workspace_id)
        if raw is None:
            return {"schema_version": "1.0", "workspace_id": workspace_id}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WebsiteStagingError("workspace record is invalid") from exc
        if not isinstance(value, dict) or value.get("workspace_id") != workspace_id:
            raise WebsiteStagingError("workspace record identity is invalid")
        return value

    def _save_record(self, workspace_id: str, record: dict[str, Any]) -> None:
        self.workspaces.save_workspace_record(workspace_id, canonical_json(record))


__all__ = [
    "WEBSITE_CAPABILITY",
    "WEBSITE_STAGING_MANIFEST",
    "WEBSITE_TOOL_ID",
    "WebsiteStagingService",
]
