"""Tests for tools-pillar appliers."""

from __future__ import annotations

from pathlib import Path

from openjarvis.learning.distillation.execute.base import ApplyContext
from openjarvis.learning.distillation.models import (
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_ctx(tmp_path: Path) -> ApplyContext:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "descriptions.toml").write_text(
        '[web_search]\ndescription = "Search the web"\n'
    )
    (tmp_path / "config.toml").write_text('[agent.simple]\ntools = ["web_search"]\n')
    return ApplyContext(openjarvis_home=tmp_path, session_id="s1")


class TestAddToolToAgentApplier:
    """Tests for AddToolToAgentApplier."""

    def test_apply_adds_tool(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.tools import (
            AddToolToAgentApplier,
        )

        applier = AddToolToAgentApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.TOOLS,
            op=EditOp.ADD_TOOL_TO_AGENT,
            target="agent.simple.tools",
            payload={"agent": "simple", "tool_name": "calculator"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.AUTO,
        )
        applier.apply(edit, ctx)
        content = ctx.config_path.read_text()
        assert "calculator" in content

    def test_validate_ok(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.tools import (
            AddToolToAgentApplier,
        )

        applier = AddToolToAgentApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.TOOLS,
            op=EditOp.ADD_TOOL_TO_AGENT,
            target="agent.simple.tools",
            payload={"agent": "simple", "tool_name": "calculator"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.AUTO,
        )
        assert applier.validate(edit, ctx).ok


class TestRemoveToolFromAgentApplier:
    """Tests for RemoveToolFromAgentApplier."""

    def test_apply_removes_tool(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.tools import (
            RemoveToolFromAgentApplier,
        )

        applier = RemoveToolFromAgentApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.TOOLS,
            op=EditOp.REMOVE_TOOL_FROM_AGENT,
            target="agent.simple.tools",
            payload={"agent": "simple", "tool_name": "web_search"},
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.AUTO,
        )
        applier.apply(edit, ctx)
        content = ctx.config_path.read_text()
        assert "web_search" not in content


class TestEditToolDescriptionApplier:
    """Tests for EditToolDescriptionApplier."""

    def test_apply_updates_description(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.tools import (
            EditToolDescriptionApplier,
        )

        applier = EditToolDescriptionApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-001",
            pillar=EditPillar.TOOLS,
            op=EditOp.EDIT_TOOL_DESCRIPTION,
            target="tools.web_search.description",
            payload={
                "tool_name": "web_search",
                "new_description": "Search the internet for current information",
            },
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.AUTO,
        )
        applier.apply(edit, ctx)
        content = (ctx.tools_dir / "descriptions.toml").read_text()
        assert "Search the internet" in content

    def test_apply_adds_new_tool_section(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.tools import (
            EditToolDescriptionApplier,
        )

        applier = EditToolDescriptionApplier()
        ctx = _make_ctx(tmp_path)
        edit = Edit(
            id="edit-002",
            pillar=EditPillar.TOOLS,
            op=EditOp.EDIT_TOOL_DESCRIPTION,
            target="tools.calculator.description",
            payload={
                "tool_name": "calculator",
                "new_description": "Evaluate mathematical expressions",
            },
            rationale="test",
            expected_improvement="c1",
            risk_tier=EditRiskTier.AUTO,
        )
        applier.apply(edit, ctx)
        content = (ctx.tools_dir / "descriptions.toml").read_text()
        assert "[calculator]" in content
        assert "Evaluate mathematical" in content
