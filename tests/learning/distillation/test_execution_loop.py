"""Tests for the per-edit execution loop."""

from __future__ import annotations

from pathlib import Path

from openjarvis.learning.distillation.execute.base import ApplyContext
from openjarvis.learning.distillation.models import (
    AutonomyMode,
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_ctx(tmp_path: Path) -> ApplyContext:
    (tmp_path / "config.toml").write_text(
        '[learning.routing.policy_map]\nmath = "qwen2.5-coder:3b"\n'
    )
    agents_dir = tmp_path / "agents" / "simple"
    agents_dir.mkdir(parents=True)
    (agents_dir / "system_prompt.md").write_text("You are helpful.\n")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "descriptions.toml").write_text(
        '[web_search]\ndescription = "Search"\n'
    )
    return ApplyContext(openjarvis_home=tmp_path, session_id="s1")


def _make_auto_edit(edit_id: str = "edit-001") -> Edit:
    return Edit(
        id=edit_id,
        pillar=EditPillar.INTELLIGENCE,
        op=EditOp.SET_MODEL_FOR_QUERY_CLASS,
        target="routing.math",
        payload={"query_class": "math", "model": "qwen2.5-coder:14b"},
        rationale="Route math to bigger model",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.AUTO,
    )


def _make_review_edit(edit_id: str = "edit-002") -> Edit:
    return Edit(
        id=edit_id,
        pillar=EditPillar.AGENT,
        op=EditOp.REPLACE_SYSTEM_PROMPT,
        target="agents.simple.system_prompt",
        payload={"new_content": "New prompt.\n"},
        rationale="Better prompt",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.REVIEW,
    )


def _make_lora_edit(edit_id: str = "edit-lora") -> Edit:
    return Edit(
        id=edit_id,
        pillar=EditPillar.INTELLIGENCE,
        op=EditOp.LORA_FINETUNE,
        target="models.qwen",
        payload={"target_model": "qwen", "data_source": "all"},
        rationale="Fine tune",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.MANUAL,
    )


class TestExecuteEdits:
    """Tests for execute_edits()."""

    def test_applies_auto_tier_edit(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.loop import execute_edits

        ctx = _make_ctx(tmp_path)
        outcomes = execute_edits(
            edits=[_make_auto_edit()],
            ctx=ctx,
            autonomy_mode=AutonomyMode.TIERED,
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == "applied"

    def test_review_edit_goes_to_pending_in_tiered_mode(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.loop import execute_edits

        ctx = _make_ctx(tmp_path)
        outcomes = execute_edits(
            edits=[_make_review_edit()],
            ctx=ctx,
            autonomy_mode=AutonomyMode.TIERED,
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == "pending_review"

    def test_review_edit_applied_in_auto_mode(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.loop import execute_edits

        ctx = _make_ctx(tmp_path)
        outcomes = execute_edits(
            edits=[_make_review_edit()],
            ctx=ctx,
            autonomy_mode=AutonomyMode.AUTO,
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == "applied"

    def test_manual_tier_skipped(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.loop import execute_edits

        ctx = _make_ctx(tmp_path)
        outcomes = execute_edits(
            edits=[_make_lora_edit()],
            ctx=ctx,
            autonomy_mode=AutonomyMode.TIERED,
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == "skipped"

    def test_all_edits_pending_in_manual_mode(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.loop import execute_edits

        ctx = _make_ctx(tmp_path)
        outcomes = execute_edits(
            edits=[_make_auto_edit()],
            ctx=ctx,
            autonomy_mode=AutonomyMode.MANUAL,
        )
        assert len(outcomes) == 1
        assert outcomes[0].status == "pending_review"

    def test_multiple_edits_processed(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.loop import execute_edits

        ctx = _make_ctx(tmp_path)
        outcomes = execute_edits(
            edits=[
                _make_auto_edit("e1"),
                _make_review_edit("e2"),
                _make_lora_edit("e3"),
            ],
            ctx=ctx,
            autonomy_mode=AutonomyMode.TIERED,
        )
        assert len(outcomes) == 3
        assert outcomes[0].status == "applied"
        assert outcomes[1].status == "pending_review"
        assert outcomes[2].status == "skipped"
