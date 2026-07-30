"""Closed-loop tool execution, trace, approval, artifact, and retry tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from openjarvis.tasks import ExecutionLane, TaskService, TaskStore
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tools.action_service import (
    RegisteredToolRuntime,
    ToolActionError,
    ToolActionService,
)
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.actions import (
    ActionStatus,
    ParameterSource,
    ToolProposal,
    VerificationResult,
)
from openjarvis.tools.manifest import (
    IdempotencyPolicy,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
    ToolManifestCatalog,
)


def _manifest(
    *,
    risk: RiskLevel = RiskLevel.READ_ONLY,
    approval: bool = False,
    retries: int = 1,
) -> ToolManifest:
    return ToolManifest(
        tool_id="test.observe",
        name="test.observe",
        description="Observe a synthetic value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        output_schema={"type": "object"},
        capability="test:observe",
        risk_level=risk,
        allowed_lanes=(
            ExecutionLane.INTERACTIVE
            if risk >= RiskLevel.EXTERNAL_PREPARATION
            else ExecutionLane.MODEL,
        ),
        supported_platforms=("windows", "linux", "darwin"),
        timeout=2,
        max_retries=retries,
        idempotency_policy=IdempotencyPolicy.SAFE_RETRY,
        side_effect_class=(
            SideEffectClass.EXTERNAL_WRITE
            if risk >= RiskLevel.DESTRUCTIVE_OR_SENSITIVE
            else SideEffectClass.LOCAL_READ
        ),
        verification_strategy="compare synthetic value",
        undo_strategy="none",
        required_approval=approval,
        network_policy=NetworkPolicy.DENY,
        secret_policy=SecretPolicy.REDACT,
        log_redaction_policy="all credentials",
    )


def _proposal(manifest: ToolManifest, **changes) -> ToolProposal:
    payload = {
        "task_id": "task-1",
        "session_id": "session-1",
        "correlation_id": "correlation-1",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "item_id": "item-1",
        "tool_id": manifest.tool_id,
        "arguments": {"value": "synthetic"},
        "expected_result": "synthetic value observed",
        "expected_side_effect": manifest.side_effect_class,
        "risk_level": manifest.risk_level,
        "capability": manifest.capability,
        "target": "synthetic target",
        "verification_plan": "compare exact values",
        "undo_plan": "not applicable",
        "idempotency_key": "action-once",
        "timeout_seconds": 1,
        "rationale": "synthetic test",
        "parameter_sources": {"value": ParameterSource.USER},
    }
    payload.update(changes)
    return ToolProposal(**payload)


def _service(
    tmp_path: Path,
    manifest: ToolManifest,
    *,
    handler=None,
    verifier=None,
    context_changes=None,
    inline_limit: int = 16_384,
) -> tuple[ToolActionService, TaskService, ActionStore, TaskStore]:
    task_store = TaskStore(tmp_path / "tasks.db")
    tasks = TaskService(task_store)
    tasks.create(
        task_id="task-1",
        session_id="session-1",
        correlation_id="correlation-1",
        description="synthetic tool task",
        execution_lane=manifest.allowed_lanes[0],
        risk_level=int(manifest.risk_level),
        component="test",
        cause="test",
        idempotency_key="create-task",
    )
    context = ToolPolicyContext(
        granted_capabilities=frozenset({manifest.capability}),
        execution_lane=manifest.allowed_lanes[0],
        requested_risk=manifest.risk_level,
        proposal_capability=manifest.capability,
        allowed_roots=(tmp_path,),
    )
    if context_changes:
        context = replace(context, **context_changes)
    actions = ActionStore(tmp_path / "actions.db")
    service = ToolActionService(
        catalog=ToolManifestCatalog((manifest,)),
        store=actions,
        context_factory=lambda _proposal: context,
        runtimes={
            manifest.tool_id: RegisteredToolRuntime(
                handler=handler or (lambda arguments: {"value": arguments["value"]}),
                verifier=verifier
                or (
                    lambda proposal, output: VerificationResult(
                        passed=output["value"] == proposal.arguments["value"],
                        observed_state=output["value"],
                        expected_state=proposal.arguments["value"],
                    )
                ),
            )
        },
        artifact_root=tmp_path / "artifacts",
        task_service=tasks,
        inline_output_limit=inline_limit,
    )
    return service, tasks, actions, task_store


@pytest.mark.asyncio
async def test_action_executes_only_after_policy_and_verification(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    service, tasks, actions, task_store = _service(tmp_path, manifest)
    action = service.create(_proposal(manifest))
    assert action.status is ActionStatus.VALIDATED
    completed = await service.execute(action.action_id)
    assert completed.status is ActionStatus.COMPLETED
    assert completed.verification_status.value == "passed"
    names = [event.event_type for event in actions.list_events(action.action_id)]
    assert names == [
        "tool.proposed",
        "tool.validated",
        "tool.started",
        "tool.output",
        "tool.verification_started",
        "tool.verified",
        "tool.completed",
    ]
    assert "tool.completed" in [event.event_type for event in tasks.timeline("task-1")]
    actions.close()
    task_store.close()


def test_unknown_parameter_is_denied_before_handler(tmp_path: Path) -> None:
    manifest = _manifest()
    called = False

    def handler(_arguments):
        nonlocal called
        called = True

    service, _, actions, task_store = _service(tmp_path, manifest, handler=handler)
    proposal = _proposal(
        manifest,
        arguments={"value": "synthetic", "unknown": True},
        parameter_sources={
            "value": ParameterSource.USER,
            "unknown": ParameterSource.WEBSITE,
        },
    )
    action = service.create(proposal)
    assert action.status is ActionStatus.DENIED
    assert "unknown" in action.error
    assert called is False
    actions.close()
    task_store.close()


def test_model_capability_cannot_create_a_grant(tmp_path: Path) -> None:
    manifest = _manifest()
    service, _, actions, task_store = _service(
        tmp_path,
        manifest,
        context_changes={"granted_capabilities": frozenset()},
    )
    action = service.create(_proposal(manifest))
    assert action.status is ActionStatus.DENIED
    assert "not granted" in action.error
    actions.close()
    task_store.close()


def test_untrusted_input_can_raise_risk_and_force_approval(tmp_path: Path) -> None:
    manifest = _manifest()
    service, _, actions, task_store = _service(
        tmp_path,
        manifest,
        context_changes={
            "untrusted_risk": RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
        },
    )
    action = service.create(_proposal(manifest))
    assert action.risk_level is RiskLevel.DESTRUCTIVE_OR_SENSITIVE
    assert action.status is ActionStatus.WAITING_APPROVAL
    actions.close()
    task_store.close()


@pytest.mark.asyncio
async def test_allow_once_is_exact_and_executes(tmp_path: Path) -> None:
    manifest = _manifest(
        risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
        approval=True,
        retries=0,
    )
    service, _, actions, task_store = _service(tmp_path, manifest)
    action = service.create(_proposal(manifest))
    assert action.status is ActionStatus.WAITING_APPROVAL
    with pytest.raises(ToolActionError, match="allow-once"):
        await service.execute(action.action_id)
    completed = await service.approve(action.action_id, decision_id="allow-once-1")
    assert completed.status is ActionStatus.COMPLETED
    repeated = await service.approve(action.action_id, decision_id="allow-once-1")
    assert repeated == completed
    actions.close()
    task_store.close()


def test_deny_is_idempotent_and_never_executes(tmp_path: Path) -> None:
    manifest = _manifest(
        risk=RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
        approval=True,
        retries=0,
    )
    called = False

    def handler(_arguments):
        nonlocal called
        called = True

    service, _, actions, task_store = _service(tmp_path, manifest, handler=handler)
    action = service.create(_proposal(manifest))
    denied = service.deny(action.action_id, decision_id="deny-1")
    assert service.deny(action.action_id, decision_id="deny-1") == denied
    assert called is False
    actions.close()
    task_store.close()


@pytest.mark.asyncio
async def test_failed_verification_never_reports_success(tmp_path: Path) -> None:
    manifest = _manifest()

    def verifier(_proposal, _output):
        return VerificationResult(
            passed=False,
            observed_state="wrong",
            expected_state="synthetic",
        )
    service, _, actions, task_store = _service(
        tmp_path,
        manifest,
        verifier=verifier,
    )
    action = service.create(_proposal(manifest))
    failed = await service.execute(action.action_id)
    assert failed.status is ActionStatus.FAILED
    assert "verified" in failed.error
    actions.close()
    task_store.close()


@pytest.mark.asyncio
async def test_large_redacted_output_is_an_artifact(tmp_path: Path) -> None:
    manifest = _manifest()

    def handler(_arguments):
        return {"api_key": "sk-secret-value", "data": "x" * 200}

    def verifier(_proposal, _output):
        return VerificationResult(
            passed=True,
            observed_state="bounded artifact",
            expected_state="bounded artifact",
        )
    service, tasks, actions, task_store = _service(
        tmp_path,
        manifest,
        handler=handler,
        verifier=verifier,
        inline_limit=32,
    )
    action = service.create(_proposal(manifest))
    completed = await service.execute(action.action_id)
    artifacts = actions.list_artifacts(completed.action_id)
    assert len(artifacts) == 1
    assert "secret-value" not in Path(artifacts[0].path).read_text(encoding="utf-8")
    assert tasks.store.get_artifact(artifacts[0].artifact_id) is not None
    actions.close()
    task_store.close()


@pytest.mark.asyncio
async def test_retry_is_blocked_after_unknown_effect(tmp_path: Path) -> None:
    manifest = _manifest()

    def handler(_arguments):
        raise RuntimeError("ambiguous")

    service, _, actions, task_store = _service(tmp_path, manifest, handler=handler)
    action = service.create(_proposal(manifest))
    failed = await service.execute(action.action_id)
    # Reads remain effect-known. Force the persisted ambiguity to exercise the guard.
    actions.transition(failed.action_id, ActionStatus.FAILED, effect_known=False)
    with pytest.raises(ToolActionError, match="unknown"):
        await service.retry(action.action_id)
    actions.close()
    task_store.close()


@pytest.mark.asyncio
async def test_interactive_lane_is_exclusive_but_model_lane_remains_free(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    service, _, actions, task_store = _service(tmp_path, manifest)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_interactive():
        entered.set()
        await release.wait()

    holder = asyncio.create_task(
        service.lanes.run(ExecutionLane.INTERACTIVE, hold_interactive)
    )
    await entered.wait()
    model_done = await asyncio.wait_for(
        service.lanes.run(ExecutionLane.MODEL, lambda: asyncio.sleep(0, result=True)),
        timeout=0.2,
    )
    assert model_done is True
    release.set()
    await holder
    actions.close()
    task_store.close()
