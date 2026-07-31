from __future__ import annotations

from datetime import datetime, timedelta, timezone

from openjarvis.learning.evaluation import (
    ApprovalState,
    BrowserRecoveryState,
    BudgetState,
    EvaluationClass,
    EvaluationInput,
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
    canonical_json,
    snapshot_from_runtime,
)
from openjarvis.tasks.policy import RiskLevel, ToolPolicyDecision
from openjarvis.tasks.types import (
    ExecutionLane,
    TaskEvent,
    TaskOutcome,
    TaskRecord,
    TaskStatus,
    TaskUsage,
)
from openjarvis.tools.actions import ActionStatus, ToolAction
from openjarvis.tools.actions import VerificationStatus as RuntimeVerificationStatus
from openjarvis.tools.manifest import SideEffectClass

from .conftest import NOW, complete_evidence


def synthetic_task() -> TaskRecord:
    return TaskRecord(
        task_id="task_runtime",
        session_id="session_runtime",
        correlation_id="correlation_runtime",
        description="PRIVATE SYNTHETIC DESCRIPTION MUST NOT BE COPIED",
        status=TaskStatus.DONE,
        outcome=TaskOutcome.COMPLETED,
        execution_lane=ExecutionLane.MODEL,
        backend="fake",
        risk_level=0,
        created_at="2026-07-31T12:00:00+00:00",
        updated_at="2026-07-31T12:01:00+00:00",
        version=2,
        result="PRIVATE SYNTHETIC RESULT MUST NOT BE COPIED",
    )


def synthetic_event() -> TaskEvent:
    return TaskEvent(
        event_id="event_runtime_done",
        task_id="task_runtime",
        sequence=3,
        event_type="task.completed",
        occurred_at="2026-07-31T12:01:00+00:00",
        cause="synthetic_test",
        component="test",
        correlation_id="correlation_runtime",
        session_id="session_runtime",
        status_from=TaskStatus.RUNNING,
        status_to=TaskStatus.DONE,
        artifact_id="artifact_runtime",
        payload={
            "messages": ["PRIVATE SYNTHETIC CHAT"],
            "tool_output": "PRIVATE SYNTHETIC TOOL OUTPUT",
        },
    )


def test_synthetic_phase_3_to_6_task_and_event_normalize_read_only() -> None:
    task = synthetic_task()
    event = synthetic_event()

    snapshot = snapshot_from_runtime(
        task,
        trace_id="trace_runtime",
        task_type="synthetic.compatibility",
        requested_goal="Redacted synthetic compatibility goal",
        events=(event,),
        verification_state=VerificationState.PASSED,
        approval_state=ApprovalState.NOT_REQUIRED,
        policy_result=PolicyResult.NOT_REQUIRED,
        browser_recovery_state=BrowserRecoveryState.NOT_APPLICABLE,
        budget_state=BudgetState.WITHIN_LIMITS,
        external_effect_state=ExternalEffectState.NONE,
        evidence_state=EvidenceState.SUFFICIENT,
        evidence_references=complete_evidence(),
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert evaluation.evaluation_class is EvaluationClass.COMPLETED
    assert snapshot.state_history[0].event_id == event.event_id
    assert snapshot.relevant_event_ids == (event.event_id,)
    assert snapshot.relevant_artifact_ids == ("artifact_runtime",)
    assert task.description == "PRIVATE SYNTHETIC DESCRIPTION MUST NOT BE COPIED"
    assert task.result == "PRIVATE SYNTHETIC RESULT MUST NOT BE COPIED"


def test_runtime_adapter_does_not_copy_private_payloads() -> None:
    snapshot = snapshot_from_runtime(
        synthetic_task(),
        trace_id="trace_runtime",
        task_type="synthetic.compatibility",
        requested_goal="Redacted synthetic compatibility goal",
        events=(synthetic_event(),),
    )
    serialized = canonical_json(snapshot)

    assert "PRIVATE SYNTHETIC" not in serialized
    assert "messages" not in serialized
    assert "tool_output" not in serialized


def test_synthetic_tool_policy_and_usage_objects_are_normalized() -> None:
    action = ToolAction(
        action_id="action_runtime",
        proposal_id="proposal_runtime",
        task_id="task_runtime",
        session_id="session_runtime",
        correlation_id="correlation_runtime",
        thread_id="thread_runtime",
        turn_id="turn_runtime",
        item_id="item_runtime",
        tool_id="synthetic.read",
        manifest_version="1.0.0",
        capability="synthetic:read",
        risk_level=RiskLevel.READ_ONLY,
        target="synthetic_target",
        expected_side_effect=SideEffectClass.LOCAL_READ,
        verification_plan="verify synthetic metadata",
        undo_plan="not applicable",
        idempotency_key="synthetic-action-once",
        status=ActionStatus.COMPLETED,
        verification_status=RuntimeVerificationStatus.PASSED,
        output_summary="PRIVATE SYNTHETIC TOOL OUTPUT MUST NOT BE COPIED",
        effect_known=True,
    )
    policy = ToolPolicyDecision(
        allowed=True,
        status="allowed",
        effective_risk=RiskLevel.READ_ONLY,
        capability="synthetic:read",
        reason="synthetic policy allowed",
        allowed_roots=(),
    )
    usage = TaskUsage(
        task_id="task_runtime",
        turn_id="turn_runtime",
        turn_input_tokens=10,
        turn_output_tokens=5,
        thread_input_tokens=10,
        thread_output_tokens=5,
        warning=False,
        hard_exceeded=False,
        reason=None,
        source_event_id="event_usage",
        updated_at="2026-07-31T12:01:00+00:00",
    )

    snapshot = snapshot_from_runtime(
        synthetic_task(),
        trace_id="trace_runtime",
        task_type="synthetic.compatibility",
        requested_goal="Redacted synthetic compatibility goal",
        events=(synthetic_event(),),
        tool_actions=(action,),
        approval_state=ApprovalState.NOT_REQUIRED,
        policy_decision=policy,
        usage=usage,
        evidence_state=EvidenceState.SUFFICIENT,
        evidence_references=complete_evidence(),
    )
    serialized = canonical_json(snapshot)

    assert snapshot.verification_state is VerificationState.PASSED
    assert snapshot.policy_result is PolicyResult.ALLOWED
    assert snapshot.budget_state is BudgetState.WITHIN_LIMITS
    assert snapshot.external_effect_state is ExternalEffectState.KNOWN
    assert "PRIVATE SYNTHETIC TOOL OUTPUT" not in serialized
    assert (
        TraceClassifier().evaluate(snapshot).evaluation_class
        is EvaluationClass.COMPLETED
    )


def test_runtime_adapter_preserves_legacy_success_only_as_untrusted_hint() -> None:
    snapshot = snapshot_from_runtime(
        synthetic_task(),
        trace_id="trace_runtime",
        task_type="synthetic.compatibility",
        requested_goal="Redacted synthetic compatibility goal",
        legacy_trace_outcome="success",
        model_claimed_success=True,
        legacy_exit_code=0,
        legacy_http_status=200,
    )

    evaluation = TraceClassifier().evaluate(snapshot)

    assert snapshot.legacy_hints.untrusted is True
    assert evaluation.evaluation_class is EvaluationClass.INSUFFICIENT_EVIDENCE


def test_runtime_adapter_does_not_mutate_input_objects() -> None:
    task = synthetic_task()
    event = synthetic_event()
    before_task = repr(task)
    before_event = repr(event)

    snapshot_from_runtime(
        task,
        trace_id="trace_runtime",
        task_type="synthetic.compatibility",
        requested_goal="Redacted synthetic compatibility goal",
        events=(event,),
    )

    assert repr(task) == before_task
    assert repr(event) == before_event


def test_utc_offsets_are_normalized_before_hashing(
    completed_snapshot: EvaluationInput,
) -> None:
    reference = EvidenceReference(
        evidence_id="evidence_shifted",
        evidence_type=EvidenceType.TASK_STATE,
        source_kind=EvidenceSourceKind.TASK_EVENT,
        source_id="event_shifted",
        digest="0" * 64,
        verification_state=EvidenceVerificationState.VERIFIED,
        trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
        created_at=datetime(
            2026,
            7,
            31,
            14,
            0,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    )

    assert reference.created_at == NOW
    assert reference.created_at.tzinfo is timezone.utc
    assert completed_snapshot.evidence_references[0].created_at == NOW
