"""Tests for intelligence-pillar appliers."""

from __future__ import annotations

from pathlib import Path

from openjarvis.learning.spec_search.execute.base import ApplyContext
from openjarvis.learning.spec_search.models import (
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_ctx(tmp_path: Path) -> ApplyContext:
    (tmp_path / "config.toml").write_text(
        "[learning.routing]\n"
        'policy = "learned"\n'
        "\n"
        "[learning.routing.policy_map]\n"
        'math = "qwen2.5-coder:3b"\n'
        'code = "qwen2.5-coder:7b"\n'
    )
    return ApplyContext(openjarvis_home=tmp_path, session_id="s1")


def _make_routing_edit(
    query_class: str = "math",
    model: str = "qwen2.5-coder:14b",
) -> Edit:
    return Edit(
        id="edit-001",
        pillar=EditPillar.INTELLIGENCE,
        op=EditOp.SET_MODEL_FOR_QUERY_CLASS,
        target="learning.routing.policy_map.math",
        payload={"query_class": query_class, "model": model},
        rationale="Route math to bigger model",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.AUTO,
    )


def _make_param_edit(
    model: str = "qwen2.5-coder:7b",
    param: str = "temperature",
    value: float = 0.3,
) -> Edit:
    return Edit(
        id="edit-002",
        pillar=EditPillar.INTELLIGENCE,
        op=EditOp.SET_MODEL_PARAM,
        target=f"models.{model}.{param}",
        payload={"model": model, "param": param, "value": value},
        rationale="Lower temperature for code",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.AUTO,
    )


class TestSetModelForQueryClassApplier:
    """Tests for SetModelForQueryClassApplier."""

    def test_validate_ok(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.intelligence import (
            SetModelForQueryClassApplier,
        )

        applier = SetModelForQueryClassApplier()
        ctx = _make_ctx(tmp_path)
        result = applier.validate(_make_routing_edit(), ctx)
        assert result.ok

    def test_apply_updates_config(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.intelligence import (
            SetModelForQueryClassApplier,
        )

        applier = SetModelForQueryClassApplier()
        ctx = _make_ctx(tmp_path)
        applier.apply(_make_routing_edit(), ctx)
        content = ctx.config_path.read_text()
        assert "qwen2.5-coder:14b" in content

    def test_apply_adds_new_query_class(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.intelligence import (
            SetModelForQueryClassApplier,
        )

        applier = SetModelForQueryClassApplier()
        ctx = _make_ctx(tmp_path)
        edit = _make_routing_edit(query_class="science", model="qwen2.5-coder:14b")
        applier.apply(edit, ctx)
        content = ctx.config_path.read_text()
        assert "science" in content
        assert "qwen2.5-coder:14b" in content


class TestSetModelParamApplier:
    """Tests for SetModelParamApplier."""

    def test_validate_ok(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.intelligence import (
            SetModelParamApplier,
        )

        applier = SetModelParamApplier()
        ctx = _make_ctx(tmp_path)
        result = applier.validate(_make_param_edit(), ctx)
        assert result.ok

    def test_apply_writes_param(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.execute.appliers.intelligence import (
            SetModelParamApplier,
        )

        applier = SetModelParamApplier()
        ctx = _make_ctx(tmp_path)
        applier.apply(_make_param_edit(), ctx)
        content = ctx.config_path.read_text()
        assert "temperature" in content
        assert "0.3" in content
