"""Tests for agent-pillar appliers."""

from __future__ import annotations

import json
from pathlib import Path

from openjarvis.learning.spec_search.execute.base import ApplyContext
from openjarvis.learning.spec_search.models import (
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_ctx(tmp_path: Path) -> ApplyContext:
    agents_dir = tmp_path / "agents" / "simple"
    agents_dir.mkdir(parents=True)
    (agents_dir / "system_prompt.md").write_text(
        "You are a helpful assistant.\nBe concise.\n"
    )
    (tmp_path / "config.toml").write_text(
        "[agent]\n"
        'default = "simple"\n'
        "\n"
        "[agent.simple]\n"
        'class = "simple"\n'
        "max_turns = 5\n"
    )
    return ApplyContext(openjarvis_home=tmp_path, session_id="s1")


class TestReplaceSystemPromptApplier:
    """Tests for ReplaceSystemPromptApplier."""

    def test_validate_ok(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            ReplaceSystemPromptApplier,
        )

        applier = ReplaceSystemPromptApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.REPLACE_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"new_content": "New prompt content.\n"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.REVIEW,
        )
        assert applier.validate(edit, ctx).ok

    def test_apply_overwrites_prompt(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            ReplaceSystemPromptApplier,
        )

        applier = ReplaceSystemPromptApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.REPLACE_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"new_content": "You are a math expert.\n"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.REVIEW,
        )
        applier.apply(edit, ctx)
        content = (tmp_path / "agents" / "simple" / "system_prompt.md").read_text()
        assert content == "You are a math expert.\n"


class TestPatchSystemPromptApplier:
    """Tests for PatchSystemPromptApplier."""

    def test_apply_applies_diff(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            PatchSystemPromptApplier,
        )

        applier = PatchSystemPromptApplier()
        ctx = _make_ctx(tmp_path)
        diff = (
            "--- a/prompt.md\n"
            "+++ b/prompt.md\n"
            "@@ -1,2 +1,2 @@\n"
            " You are a helpful assistant.\n"
            "-Be concise.\n"
            "+Be concise and use math tools.\n"
        )
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.PATCH_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"diff": diff},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.REVIEW,
        )
        applier.apply(edit, ctx)
        content = (tmp_path / "agents" / "simple" / "system_prompt.md").read_text()
        assert "math tools" in content

    def test_validate_fails_for_bad_diff(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            PatchSystemPromptApplier,
        )

        applier = PatchSystemPromptApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-002",
            pillar=EditPillar.AGENT,
            op=EditOp.PATCH_SYSTEM_PROMPT,
            target="agents.simple.system_prompt",
            payload={"diff": "not a valid diff"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.REVIEW,
        )
        result = applier.validate(edit, ctx)
        assert not result.ok


class TestSetAgentClassApplier:
    """Tests for SetAgentClassApplier."""

    def test_apply_updates_config(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            SetAgentClassApplier,
        )

        applier = SetAgentClassApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.SET_AGENT_CLASS,
            target="agent.simple.class",
            payload={"agent": "simple", "new_class": "react"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.REVIEW,
        )
        applier.apply(edit, ctx)
        content = ctx.config_path.read_text()
        assert "react" in content


class TestSetAgentParamApplier:
    """Tests for SetAgentParamApplier."""

    def test_apply_updates_param(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            SetAgentParamApplier,
        )

        applier = SetAgentParamApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.SET_AGENT_PARAM,
            target="agent.simple.max_turns",
            payload={"agent": "simple", "param": "max_turns", "value": 10},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.AUTO,
        )
        applier.apply(edit, ctx)
        content = ctx.config_path.read_text()
        assert "10" in content


class TestEditFewShotExemplarsApplier:
    """Tests for EditFewShotExemplarsApplier."""

    def test_apply_writes_exemplars(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.agent import (
            EditFewShotExemplarsApplier,
        )

        applier = EditFewShotExemplarsApplier()
        ctx = _make_ctx(tmp_path)
        exemplars = [
            {"input": "What is 2+2?", "output": "4"},
            {"input": "Capital of France?", "output": "Paris"},
        ]
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.AGENT,
            op=EditOp.EDIT_FEW_SHOT_EXEMPLARS,
            target="agents.simple.few_shot",
            payload={"agent": "simple", "exemplars": exemplars},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.REVIEW,
        )
        applier.apply(edit, ctx)
        fs_path = tmp_path / "agents" / "simple" / "few_shot.json"
        assert fs_path.exists()
        data = json.loads(fs_path.read_text())
        assert len(data) == 2
        assert data[0]["input"] == "What is 2+2?"
