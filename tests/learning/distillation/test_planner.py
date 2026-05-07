"""Tests for openjarvis.learning.distillation.plan.planner module.

All tests use mocked CloudEngine — no live API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from openjarvis.learning.distillation.models import (
    EditOp,
    EditRiskTier,
    FailureCluster,
)


def _make_clusters() -> list[FailureCluster]:
    return [
        FailureCluster(
            id="cluster-001",
            description="Math queries routed to qwen-3b",
            sample_trace_ids=["t1", "t2", "t3"],
            student_failure_rate=0.8,
            teacher_success_rate=0.95,
            skill_gap="Student lacks chain-of-thought on multi-step math",
        ),
        FailureCluster(
            id="cluster-002",
            description="Calculator tool not used",
            sample_trace_ids=["t4", "t5", "t6"],
            student_failure_rate=0.6,
            teacher_success_rate=0.9,
            skill_gap="Student does not invoke calculator",
        ),
    ]


def _make_teacher_response(edits_json: list[dict]) -> dict:
    """Create a mock engine.generate() response with edit list."""
    return {
        "content": json.dumps({"edits": edits_json}),
        "usage": {"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
        "cost_usd": 0.03,
        "finish_reason": "stop",
    }


def _make_edit_dict(
    edit_id: str = "edit-001",
    pillar: str = "intelligence",
    op: str = "set_model_for_query_class",
    target: str = "learning.routing.policy_map.math",
    payload: dict | None = None,
    expected_improvement: str = "cluster-001",
) -> dict:
    return {
        "id": edit_id,
        "pillar": pillar,
        "op": op,
        "target": target,
        "payload": payload or {"query_class": "math", "model": "qwen2.5-coder:14b"},
        "rationale": "Route math queries to a bigger model",
        "expected_improvement": expected_improvement,
        "risk_tier": "auto",
        "references": ["t1", "t2"],
    }


class TestLearningPlanner:
    """Tests for LearningPlanner."""

    def test_produces_learning_plan(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        engine.generate.return_value = _make_teacher_response([_make_edit_dict()])

        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=tmp_path / "session-001",
            prompt_reader=lambda t: "",
        )
        plan = planner.run(
            diagnosis_md="## Diagnosis\nMath routing is broken.",
            clusters=_make_clusters(),
        )

        assert plan.session_id == "session-001"
        assert len(plan.edits) == 1
        assert plan.edits[0].op == EditOp.SET_MODEL_FOR_QUERY_CLASS
        assert plan.teacher_model == "claude-opus-4-6"

    def test_assigns_risk_tiers(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        # Teacher incorrectly sets MANUAL for an auto-tier op
        edit_dict = _make_edit_dict()
        edit_dict["risk_tier"] = "manual"
        engine.generate.return_value = _make_teacher_response([edit_dict])

        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=tmp_path / "session-001",
            prompt_reader=lambda t: "",
        )
        plan = planner.run(
            diagnosis_md="## Diagnosis",
            clusters=_make_clusters(),
        )

        # Should be overwritten to AUTO
        assert plan.edits[0].risk_tier == EditRiskTier.AUTO

    def test_persists_plan_json(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        engine.generate.return_value = _make_teacher_response([_make_edit_dict()])

        session_dir = tmp_path / "session-001"
        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=session_dir,
            prompt_reader=lambda t: "",
        )
        planner.run(
            diagnosis_md="## Diagnosis",
            clusters=_make_clusters(),
        )

        plan_path = session_dir / "plan.json"
        assert plan_path.exists()
        data = json.loads(plan_path.read_text())
        assert data["session_id"] == "session-001"

    def test_drops_cluster_with_zero_rates(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        engine.generate.return_value = _make_teacher_response([_make_edit_dict()])

        clusters = [
            FailureCluster(
                id="cluster-bad",
                description="No evidence",
                sample_trace_ids=[],
                student_failure_rate=0.0,
                teacher_success_rate=0.0,
                skill_gap="Speculative",
            ),
            FailureCluster(
                id="cluster-good",
                description="Real evidence",
                sample_trace_ids=["t1", "t2", "t3"],
                student_failure_rate=0.8,
                teacher_success_rate=0.9,
                skill_gap="Verified gap",
            ),
        ]

        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=tmp_path / "session-001",
            prompt_reader=lambda t: "",
        )
        plan = planner.run(
            diagnosis_md="## Diagnosis",
            clusters=clusters,
        )

        # cluster-bad should be dropped (marked in skill_gap)
        bad = next(c for c in plan.failure_clusters if c.id == "cluster-bad")
        assert "dropped" in bad.skill_gap.lower()
        assert bad.addressed_by_edit_ids == []
        # cluster-good should survive
        good = next(c for c in plan.failure_clusters if c.id == "cluster-good")
        assert "dropped" not in good.skill_gap.lower()

    def test_all_clusters_dropped_returns_empty_edits(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        engine.generate.return_value = _make_teacher_response([])

        clusters = [
            FailureCluster(
                id="cluster-bad",
                description="No evidence",
                sample_trace_ids=[],
                student_failure_rate=0.0,
                teacher_success_rate=0.0,
                skill_gap="Speculative",
            ),
        ]

        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=tmp_path / "session-001",
            prompt_reader=lambda t: "",
        )
        plan = planner.run(
            diagnosis_md="## Diagnosis",
            clusters=clusters,
        )

        assert plan.edits == []
        assert plan.failure_clusters[0].addressed_by_edit_ids == []

    def test_persists_teacher_trace_jsonl(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        engine.generate.return_value = _make_teacher_response([_make_edit_dict()])

        session_dir = tmp_path / "session-001"
        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=session_dir,
            prompt_reader=lambda t: "",
        )
        planner.run(
            diagnosis_md="## Diagnosis",
            clusters=_make_clusters(),
        )

        jsonl_path = session_dir / "teacher_traces" / "plan.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text().strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert "cost_usd" in record

    def test_handles_malformed_teacher_output(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.plan.planner import LearningPlanner

        engine = MagicMock()
        engine.generate.return_value = {
            "content": "This is not valid JSON at all",
            "usage": {"total_tokens": 100},
            "cost_usd": 0.01,
            "finish_reason": "stop",
        }

        planner = LearningPlanner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            session_id="session-001",
            session_dir=tmp_path / "session-001",
            prompt_reader=lambda t: "",
        )
        plan = planner.run(
            diagnosis_md="## Diagnosis",
            clusters=_make_clusters(),
        )

        # Should return a plan with no edits rather than crashing
        assert plan.edits == []
