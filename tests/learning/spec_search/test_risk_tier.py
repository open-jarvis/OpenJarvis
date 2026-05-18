"""Tests for openjarvis.learning.spec_search.plan.risk_tier module."""

from __future__ import annotations


class TestTierTable:
    """Tests for TIER_TABLE completeness."""

    def test_every_edit_op_has_a_tier(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp
        from openjarvis.learning.spec_search.plan.risk_tier import TIER_TABLE

        for op in EditOp:
            assert op in TIER_TABLE, f"Missing tier for {op}"

    def test_no_extra_keys(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp
        from openjarvis.learning.spec_search.plan.risk_tier import TIER_TABLE

        for key in TIER_TABLE:
            assert key in EditOp, f"Extra key in TIER_TABLE: {key}"


class TestAssignTier:
    """Tests for assign_tier() function."""

    def test_intelligence_ops_are_auto(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.SET_MODEL_FOR_QUERY_CLASS) == EditRiskTier.AUTO
        assert assign_tier(EditOp.SET_MODEL_PARAM) == EditRiskTier.AUTO

    def test_tool_ops_are_auto(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.ADD_TOOL_TO_AGENT) == EditRiskTier.AUTO
        assert assign_tier(EditOp.REMOVE_TOOL_FROM_AGENT) == EditRiskTier.AUTO
        assert assign_tier(EditOp.EDIT_TOOL_DESCRIPTION) == EditRiskTier.AUTO

    def test_agent_param_is_auto(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.SET_AGENT_PARAM) == EditRiskTier.AUTO

    def test_prompt_ops_are_review(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.PATCH_SYSTEM_PROMPT) == EditRiskTier.REVIEW
        assert assign_tier(EditOp.REPLACE_SYSTEM_PROMPT) == EditRiskTier.REVIEW

    def test_agent_class_is_review(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.SET_AGENT_CLASS) == EditRiskTier.REVIEW

    def test_few_shot_is_review(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.EDIT_FEW_SHOT_EXEMPLARS) == EditRiskTier.REVIEW

    def test_lora_is_manual(self) -> None:
        from openjarvis.learning.spec_search.models import EditOp, EditRiskTier
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tier

        assert assign_tier(EditOp.LORA_FINETUNE) == EditRiskTier.MANUAL


class TestAssignTiers:
    """Tests for assign_tiers() batch function."""

    def test_overwrites_teacher_tier(self) -> None:
        from openjarvis.learning.spec_search.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
        )
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tiers

        # Teacher incorrectly sets AUTO for a prompt edit
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.PATCH_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"diff": "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new"},
            rationale="Improve prompt",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.AUTO,  # Wrong — should be REVIEW
        )
        result = assign_tiers([edit])
        assert result[0].risk_tier == EditRiskTier.REVIEW

    def test_preserves_correct_tier(self) -> None:
        from openjarvis.learning.spec_search.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
        )
        from openjarvis.learning.spec_search.plan.risk_tier import assign_tiers

        edit = Edit(
            id="edit-002",
            pillar=EditPillar.INTELLIGENCE,
            op=EditOp.SET_MODEL_FOR_QUERY_CLASS,
            target="learning.routing.policy_map.math",
            payload={"query_class": "math", "model": "qwen2.5-coder:14b"},
            rationale="Route math to bigger model",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.AUTO,  # Correct
        )
        result = assign_tiers([edit])
        assert result[0].risk_tier == EditRiskTier.AUTO
