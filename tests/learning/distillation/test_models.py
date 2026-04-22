"""Tests for openjarvis.learning.distillation.models module."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEditPillar:
    """Tests for EditPillar enum."""

    def test_has_four_pillars(self) -> None:
        from openjarvis.learning.distillation.models import EditPillar

        assert EditPillar.INTELLIGENCE.value == "intelligence"
        assert EditPillar.AGENT.value == "agent"
        assert EditPillar.TOOLS.value == "tools"
        assert EditPillar.ENGINE.value == "engine"

    def test_is_string_enum(self) -> None:
        from openjarvis.learning.distillation.models import EditPillar

        assert isinstance(EditPillar.AGENT, str)
        assert EditPillar("agent") is EditPillar.AGENT


class TestEditRiskTier:
    """Tests for EditRiskTier enum."""

    def test_has_three_tiers(self) -> None:
        from openjarvis.learning.distillation.models import EditRiskTier

        assert EditRiskTier.AUTO.value == "auto"
        assert EditRiskTier.REVIEW.value == "review"
        assert EditRiskTier.MANUAL.value == "manual"


class TestEditOp:
    """Tests for EditOp enum — must contain all v1 ops plus v2 placeholders."""

    def test_intelligence_ops(self) -> None:
        from openjarvis.learning.distillation.models import EditOp

        assert EditOp.SET_MODEL_FOR_QUERY_CLASS.value == "set_model_for_query_class"
        assert EditOp.SET_MODEL_PARAM.value == "set_model_param"

    def test_agent_ops(self) -> None:
        from openjarvis.learning.distillation.models import EditOp

        assert EditOp.PATCH_SYSTEM_PROMPT.value == "patch_system_prompt"
        assert EditOp.REPLACE_SYSTEM_PROMPT.value == "replace_system_prompt"
        assert EditOp.SET_AGENT_CLASS.value == "set_agent_class"
        assert EditOp.SET_AGENT_PARAM.value == "set_agent_param"
        assert EditOp.EDIT_FEW_SHOT_EXEMPLARS.value == "edit_few_shot_exemplars"

    def test_tools_ops(self) -> None:
        from openjarvis.learning.distillation.models import EditOp

        assert EditOp.ADD_TOOL_TO_AGENT.value == "add_tool_to_agent"
        assert EditOp.REMOVE_TOOL_FROM_AGENT.value == "remove_tool_from_agent"
        assert EditOp.EDIT_TOOL_DESCRIPTION.value == "edit_tool_description"

    def test_v2_placeholder_ops(self) -> None:
        from openjarvis.learning.distillation.models import EditOp

        assert EditOp.LORA_FINETUNE.value == "lora_finetune"


class TestTriggerKind:
    """Tests for TriggerKind enum."""

    def test_four_trigger_kinds(self) -> None:
        from openjarvis.learning.distillation.models import TriggerKind

        assert TriggerKind.SCHEDULED.value == "scheduled"
        assert TriggerKind.CLUSTER.value == "cluster"
        assert TriggerKind.USER_FLAG.value == "user_flag"
        assert TriggerKind.ON_DEMAND.value == "on_demand"


class TestAutonomyMode:
    """Tests for AutonomyMode enum."""

    def test_three_modes(self) -> None:
        from openjarvis.learning.distillation.models import AutonomyMode

        assert AutonomyMode.AUTO.value == "auto"
        assert AutonomyMode.TIERED.value == "tiered"
        assert AutonomyMode.MANUAL.value == "manual"


class TestSessionStatus:
    """Tests for SessionStatus enum."""

    def test_all_statuses(self) -> None:
        from openjarvis.learning.distillation.models import SessionStatus

        assert SessionStatus.INITIATED.value == "initiated"
        assert SessionStatus.DIAGNOSING.value == "diagnosing"
        assert SessionStatus.PLANNING.value == "planning"
        assert SessionStatus.EXECUTING.value == "executing"
        assert SessionStatus.AWAITING_REVIEW.value == "awaiting_review"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.FAILED.value == "failed"
        assert SessionStatus.ROLLED_BACK.value == "rolled_back"


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


class TestEdit:
    """Tests for Edit pydantic model."""

    def _valid_edit_kwargs(self) -> dict:
        from openjarvis.learning.distillation.models import (
            EditOp,
            EditPillar,
            EditRiskTier,
        )

        return {
            "id": "11111111-2222-3333-4444-555555555555",
            "pillar": EditPillar.INTELLIGENCE,
            "op": EditOp.SET_MODEL_FOR_QUERY_CLASS,
            "target": "learning.routing.policy_map.math",
            "payload": {"query_class": "math", "model": "qwen2.5-coder:14b"},
            "rationale": "Math queries are misrouted to qwen-3b",
            "expected_improvement": "math_failures cluster",
            "risk_tier": EditRiskTier.AUTO,
            "references": ["trace-001", "trace-002"],
        }

    def test_constructs_with_valid_fields(self) -> None:
        from openjarvis.learning.distillation.models import Edit

        edit = Edit(**self._valid_edit_kwargs())

        assert edit.id == "11111111-2222-3333-4444-555555555555"
        assert edit.target == "learning.routing.policy_map.math"
        assert edit.payload == {"query_class": "math", "model": "qwen2.5-coder:14b"}
        assert edit.references == ["trace-001", "trace-002"]

    def test_round_trip_via_json(self) -> None:
        from openjarvis.learning.distillation.models import Edit

        edit = Edit(**self._valid_edit_kwargs())
        as_json = edit.model_dump_json()
        restored = Edit.model_validate_json(as_json)

        assert restored == edit

    def test_pillar_must_be_valid_enum(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import Edit

        kwargs = self._valid_edit_kwargs()
        kwargs["pillar"] = "not_a_pillar"

        with pytest.raises(ValidationError):
            Edit(**kwargs)

    def test_op_must_be_valid_enum(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import Edit

        kwargs = self._valid_edit_kwargs()
        kwargs["op"] = "not_an_op"

        with pytest.raises(ValidationError):
            Edit(**kwargs)

    def test_payload_can_be_empty_dict(self) -> None:
        from openjarvis.learning.distillation.models import Edit

        kwargs = self._valid_edit_kwargs()
        kwargs["payload"] = {}

        edit = Edit(**kwargs)
        assert edit.payload == {}

    def test_references_default_empty_list(self) -> None:
        from openjarvis.learning.distillation.models import Edit

        kwargs = self._valid_edit_kwargs()
        del kwargs["references"]

        edit = Edit(**kwargs)
        assert edit.references == []


# ---------------------------------------------------------------------------
# FailureCluster
# ---------------------------------------------------------------------------


class TestFailureCluster:
    """Tests for FailureCluster pydantic model."""

    def _valid_cluster_kwargs(self) -> dict:
        return {
            "id": "cluster-001",
            "description": "Math word problems routed to qwen-3b",
            "sample_trace_ids": ["trace-001", "trace-002", "trace-003"],
            "student_failure_rate": 0.85,
            "teacher_success_rate": 0.95,
            "skill_gap": (
                "Student lacks chain-of-thought reasoning on multi-step arithmetic."
            ),
            "addressed_by_edit_ids": ["edit-001", "edit-002"],
        }

    def test_constructs_with_valid_fields(self) -> None:
        from openjarvis.learning.distillation.models import FailureCluster

        cluster = FailureCluster(**self._valid_cluster_kwargs())

        assert cluster.id == "cluster-001"
        assert cluster.student_failure_rate == 0.85
        assert cluster.teacher_success_rate == 0.95
        assert len(cluster.sample_trace_ids) == 3
        assert len(cluster.addressed_by_edit_ids) == 2

    def test_round_trip_via_json(self) -> None:
        from openjarvis.learning.distillation.models import FailureCluster

        cluster = FailureCluster(**self._valid_cluster_kwargs())
        as_json = cluster.model_dump_json()
        restored = FailureCluster.model_validate_json(as_json)

        assert restored == cluster

    def test_addressed_by_edit_ids_defaults_empty(self) -> None:
        from openjarvis.learning.distillation.models import FailureCluster

        kwargs = self._valid_cluster_kwargs()
        del kwargs["addressed_by_edit_ids"]

        cluster = FailureCluster(**kwargs)
        assert cluster.addressed_by_edit_ids == []

    def test_failure_rate_must_be_between_zero_and_one(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import FailureCluster

        kwargs = self._valid_cluster_kwargs()
        kwargs["student_failure_rate"] = 1.5

        with pytest.raises(ValidationError):
            FailureCluster(**kwargs)

    def test_success_rate_must_be_between_zero_and_one(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import FailureCluster

        kwargs = self._valid_cluster_kwargs()
        kwargs["teacher_success_rate"] = -0.1

        with pytest.raises(ValidationError):
            FailureCluster(**kwargs)


# ---------------------------------------------------------------------------
# LearningPlan
# ---------------------------------------------------------------------------


class TestLearningPlan:
    """Tests for LearningPlan pydantic model."""

    def _valid_plan_kwargs(self) -> dict:
        from datetime import datetime, timezone

        from openjarvis.learning.distillation.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
            FailureCluster,
        )

        cluster = FailureCluster(
            id="cluster-001",
            description="Math routed to qwen-3b",
            sample_trace_ids=["t1", "t2", "t3"],
            student_failure_rate=0.8,
            teacher_success_rate=0.9,
            skill_gap="needs CoT",
            addressed_by_edit_ids=["edit-001"],
        )
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.INTELLIGENCE,
            op=EditOp.SET_MODEL_FOR_QUERY_CLASS,
            target="learning.routing.policy_map.math",
            payload={"query_class": "math", "model": "qwen2.5-coder:14b"},
            rationale="Math fails on small model",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.AUTO,
            references=["t1"],
        )
        return {
            "session_id": "session-001",
            "diagnosis_summary": "## Diagnosis\nThe student misroutes math.",
            "failure_clusters": [cluster],
            "edits": [edit],
            "teacher_model": "claude-opus-4-6",
            "estimated_cost_usd": 1.42,
            "created_at": datetime(2026, 4, 8, 14, 22, 1, tzinfo=timezone.utc),
        }

    def test_constructs_with_valid_fields(self) -> None:
        from openjarvis.learning.distillation.models import LearningPlan

        plan = LearningPlan(**self._valid_plan_kwargs())

        assert plan.session_id == "session-001"
        assert len(plan.failure_clusters) == 1
        assert len(plan.edits) == 1
        assert plan.teacher_model == "claude-opus-4-6"
        assert plan.estimated_cost_usd == 1.42

    def test_round_trip_via_json(self) -> None:
        from openjarvis.learning.distillation.models import LearningPlan

        plan = LearningPlan(**self._valid_plan_kwargs())
        as_json = plan.model_dump_json()
        restored = LearningPlan.model_validate_json(as_json)

        assert restored == plan

    def test_empty_clusters_and_edits_allowed(self) -> None:
        # An aborted session may produce a plan with no clusters and no edits.
        from openjarvis.learning.distillation.models import LearningPlan

        kwargs = self._valid_plan_kwargs()
        kwargs["failure_clusters"] = []
        kwargs["edits"] = []

        plan = LearningPlan(**kwargs)
        assert plan.failure_clusters == []
        assert plan.edits == []

    def test_estimated_cost_must_be_non_negative(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import LearningPlan

        kwargs = self._valid_plan_kwargs()
        kwargs["estimated_cost_usd"] = -1.0

        with pytest.raises(ValidationError):
            LearningPlan(**kwargs)


# ---------------------------------------------------------------------------
# BenchmarkSnapshot
# ---------------------------------------------------------------------------


class TestBenchmarkSnapshot:
    """Tests for BenchmarkSnapshot pydantic model."""

    def _valid_snapshot_kwargs(self) -> dict:
        return {
            "benchmark_version": "personal_v3",
            "overall_score": 0.72,
            "cluster_scores": {"cluster-001": 0.65, "cluster-002": 0.80},
            "task_count": 50,
            "elapsed_seconds": 184.3,
        }

    def test_constructs_with_valid_fields(self) -> None:
        from openjarvis.learning.distillation.models import BenchmarkSnapshot

        snap = BenchmarkSnapshot(**self._valid_snapshot_kwargs())

        assert snap.benchmark_version == "personal_v3"
        assert snap.overall_score == 0.72
        assert snap.cluster_scores["cluster-001"] == 0.65
        assert snap.task_count == 50
        assert snap.elapsed_seconds == 184.3

    def test_round_trip_via_json(self) -> None:
        from openjarvis.learning.distillation.models import BenchmarkSnapshot

        snap = BenchmarkSnapshot(**self._valid_snapshot_kwargs())
        restored = BenchmarkSnapshot.model_validate_json(snap.model_dump_json())

        assert restored == snap

    def test_score_bounds(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import BenchmarkSnapshot

        kwargs = self._valid_snapshot_kwargs()
        kwargs["overall_score"] = 1.5

        with pytest.raises(ValidationError):
            BenchmarkSnapshot(**kwargs)

    def test_task_count_must_be_non_negative(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import BenchmarkSnapshot

        kwargs = self._valid_snapshot_kwargs()
        kwargs["task_count"] = -1

        with pytest.raises(ValidationError):
            BenchmarkSnapshot(**kwargs)


# ---------------------------------------------------------------------------
# EditOutcome
# ---------------------------------------------------------------------------


class TestEditOutcome:
    """Tests for EditOutcome pydantic model."""

    def _valid_outcome_kwargs(self) -> dict:
        from datetime import datetime, timezone

        return {
            "edit_id": "edit-001",
            "status": "applied",
            "benchmark_delta": 0.04,
            "cluster_deltas": {"cluster-001": 0.10, "cluster-002": 0.0},
            "error": None,
            "applied_at": datetime(2026, 4, 8, 14, 25, 0, tzinfo=timezone.utc),
        }

    def test_applied_outcome(self) -> None:
        from openjarvis.learning.distillation.models import EditOutcome

        outcome = EditOutcome(**self._valid_outcome_kwargs())
        assert outcome.status == "applied"
        assert outcome.benchmark_delta == 0.04

    def test_rejected_outcome_has_no_applied_at(self) -> None:
        from openjarvis.learning.distillation.models import EditOutcome

        outcome = EditOutcome(
            edit_id="edit-002",
            status="rejected_by_gate",
            benchmark_delta=-0.02,
            cluster_deltas={},
            error="regression: cluster-001 dropped 0.06",
            applied_at=None,
        )
        assert outcome.status == "rejected_by_gate"
        assert outcome.applied_at is None
        assert outcome.error is not None

    def test_status_must_be_valid_literal(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import EditOutcome

        kwargs = self._valid_outcome_kwargs()
        kwargs["status"] = "totally_made_up"

        with pytest.raises(ValidationError):
            EditOutcome(**kwargs)

    def test_round_trip_via_json(self) -> None:
        from openjarvis.learning.distillation.models import EditOutcome

        outcome = EditOutcome(**self._valid_outcome_kwargs())
        restored = EditOutcome.model_validate_json(outcome.model_dump_json())

        assert restored == outcome


# ---------------------------------------------------------------------------
# LearningSession
# ---------------------------------------------------------------------------


class TestLearningSession:
    """Tests for LearningSession pydantic model."""

    def _valid_session_kwargs(self) -> dict:
        from datetime import datetime, timezone
        from pathlib import Path

        from openjarvis.learning.distillation.models import (
            AutonomyMode,
            BenchmarkSnapshot,
            SessionStatus,
            TriggerKind,
        )

        snap = BenchmarkSnapshot(
            benchmark_version="personal_v1",
            overall_score=0.65,
            cluster_scores={"cluster-001": 0.50},
            task_count=30,
            elapsed_seconds=92.0,
        )
        return {
            "id": "session-001",
            "parent_session_id": None,
            "trigger": TriggerKind.SCHEDULED,
            "trigger_metadata": {"cron": "0 3 * * *"},
            "status": SessionStatus.INITIATED,
            "autonomy_mode": AutonomyMode.TIERED,
            "started_at": datetime(2026, 4, 8, 3, 0, 0, tzinfo=timezone.utc),
            "ended_at": None,
            "diagnosis_path": Path("/tmp/sessions/session-001/diagnosis.md"),
            "plan_path": Path("/tmp/sessions/session-001/plan.json"),
            "benchmark_before": snap,
            "benchmark_after": None,
            "edit_outcomes": [],
            "git_checkpoint_pre": "abc1234",
            "git_checkpoint_post": None,
            "teacher_cost_usd": 0.0,
            "error": None,
        }

    def test_constructs_with_valid_fields(self) -> None:
        from openjarvis.learning.distillation.models import LearningSession

        session = LearningSession(**self._valid_session_kwargs())
        assert session.id == "session-001"
        assert session.parent_session_id is None
        assert session.git_checkpoint_pre == "abc1234"
        assert session.benchmark_after is None

    def test_round_trip_via_json(self) -> None:
        from openjarvis.learning.distillation.models import LearningSession

        session = LearningSession(**self._valid_session_kwargs())
        as_json = session.model_dump_json()
        restored = LearningSession.model_validate_json(as_json)

        assert restored == session

    def test_supports_parent_session_chain(self) -> None:
        from openjarvis.learning.distillation.models import LearningSession

        kwargs = self._valid_session_kwargs()
        kwargs["parent_session_id"] = "session-000"

        session = LearningSession(**kwargs)
        assert session.parent_session_id == "session-000"

    def test_status_must_be_valid_enum(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import LearningSession

        kwargs = self._valid_session_kwargs()
        kwargs["status"] = "not_a_status"

        with pytest.raises(ValidationError):
            LearningSession(**kwargs)

    def test_teacher_cost_must_be_non_negative(self) -> None:
        import pytest
        from pydantic import ValidationError

        from openjarvis.learning.distillation.models import LearningSession

        kwargs = self._valid_session_kwargs()
        kwargs["teacher_cost_usd"] = -0.01

        with pytest.raises(ValidationError):
            LearningSession(**kwargs)
