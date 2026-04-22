"""Tests for openjarvis.learning.distillation.plan.prompt_diff module."""

from __future__ import annotations

from pathlib import Path


class TestChangedLineRatio:
    """Tests for changed_line_ratio()."""

    def test_identical_strings(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            changed_line_ratio,
        )

        assert changed_line_ratio("hello\nworld\n", "hello\nworld\n") == 0.0

    def test_completely_different(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            changed_line_ratio,
        )

        ratio = changed_line_ratio("aaa\nbbb\nccc\n", "xxx\nyyy\nzzz\n")
        assert ratio == 1.0

    def test_partial_change(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            changed_line_ratio,
        )

        original = "line1\nline2\nline3\nline4\n"
        modified = "line1\nchanged\nline3\nline4\n"
        ratio = changed_line_ratio(original, modified)
        # 1 out of 4 lines changed
        assert 0.2 <= ratio <= 0.35

    def test_empty_original(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            changed_line_ratio,
        )

        # Adding to empty = 100% change
        ratio = changed_line_ratio("", "new content\n")
        assert ratio == 1.0

    def test_empty_both(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            changed_line_ratio,
        )

        assert changed_line_ratio("", "") == 0.0


class TestApplyUnifiedDiff:
    """Tests for apply_unified_diff()."""

    def test_applies_simple_patch(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            apply_unified_diff,
        )

        original = "line1\nline2\nline3\n"
        diff = (
            "--- a/prompt.md\n"
            "+++ b/prompt.md\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+changed_line2\n"
            " line3\n"
        )
        result = apply_unified_diff(original, diff)
        assert result == "line1\nchanged_line2\nline3\n"

    def test_returns_none_on_bad_diff(self) -> None:
        from openjarvis.learning.distillation.plan.prompt_diff import (
            apply_unified_diff,
        )

        result = apply_unified_diff("hello\n", "not a valid diff")
        assert result is None


class TestMaybeDowngradeToReplace:
    """Tests for maybe_downgrade_to_replace()."""

    def test_non_patch_op_passes_through(self) -> None:
        from openjarvis.learning.distillation.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
        )
        from openjarvis.learning.distillation.plan.prompt_diff import (
            maybe_downgrade_to_replace,
        )

        edit = Edit(
            id="edit-001",
            pillar=EditPillar.INTELLIGENCE,
            op=EditOp.SET_MODEL_FOR_QUERY_CLASS,
            target="routing.math",
            payload={"model": "qwen2.5-coder:14b"},
            rationale="test",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.AUTO,
        )
        result = maybe_downgrade_to_replace(edit, prompt_reader=lambda t: "")
        assert result.op == EditOp.SET_MODEL_FOR_QUERY_CLASS

    def test_small_diff_stays_patch(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
        )
        from openjarvis.learning.distillation.plan.prompt_diff import (
            maybe_downgrade_to_replace,
        )

        original = (
            "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n"
        )
        diff = (
            "--- a/prompt.md\n"
            "+++ b/prompt.md\n"
            "@@ -2,1 +2,1 @@\n"
            " line1\n"
            "-line2\n"
            "+changed\n"
            " line3\n"
        )
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.PATCH_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"diff": diff},
            rationale="Small fix",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.REVIEW,
        )
        result = maybe_downgrade_to_replace(edit, prompt_reader=lambda t: original)
        assert result.op == EditOp.PATCH_SYSTEM_PROMPT

    def test_large_diff_downgrades_to_replace(self) -> None:
        from openjarvis.learning.distillation.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
        )
        from openjarvis.learning.distillation.plan.prompt_diff import (
            maybe_downgrade_to_replace,
        )

        original = "old1\nold2\nold3\nold4\n"
        diff = (
            "--- a/prompt.md\n"
            "+++ b/prompt.md\n"
            "@@ -1,4 +1,4 @@\n"
            "-old1\n"
            "-old2\n"
            "-old3\n"
            "-old4\n"
            "+new1\n"
            "+new2\n"
            "+new3\n"
            "+new4\n"
        )
        edit = Edit(
            id="edit-002",
            pillar=EditPillar.AGENT,
            op=EditOp.PATCH_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"diff": diff},
            rationale="Major rewrite",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.REVIEW,
        )
        result = maybe_downgrade_to_replace(edit, prompt_reader=lambda t: original)
        assert result.op == EditOp.REPLACE_SYSTEM_PROMPT
        assert "new_content" in result.payload
        assert "new1" in result.payload["new_content"]

    def test_bad_diff_downgrades_to_replace_with_raw(self) -> None:
        from openjarvis.learning.distillation.models import (
            Edit,
            EditOp,
            EditPillar,
            EditRiskTier,
        )
        from openjarvis.learning.distillation.plan.prompt_diff import (
            maybe_downgrade_to_replace,
        )

        edit = Edit(
            id="edit-003",
            pillar=EditPillar.AGENT,
            op=EditOp.PATCH_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"diff": "this is not a valid unified diff"},
            rationale="Bad diff",
            expected_improvement="cluster-001",
            risk_tier=EditRiskTier.REVIEW,
        )
        result = maybe_downgrade_to_replace(
            edit, prompt_reader=lambda t: "original content\n"
        )
        # Can't apply the diff, so it should downgrade
        assert result.op == EditOp.REPLACE_SYSTEM_PROMPT
