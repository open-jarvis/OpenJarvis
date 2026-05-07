"""Tests for LoRA stub applier."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.learning.distillation.execute.base import ApplyContext
from openjarvis.learning.distillation.models import (
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_lora_edit() -> Edit:
    return Edit(
        id="edit-lora",
        pillar=EditPillar.INTELLIGENCE,
        op=EditOp.LORA_FINETUNE,
        target="models.qwen2.5-coder:7b",
        payload={"target_model": "qwen2.5-coder:7b", "data_source": "trace_filter:*"},
        rationale="Fine-tune for math",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.MANUAL,
    )


class TestLoraStubApplier:
    """Tests for LoraStubApplier."""

    def test_validate_returns_not_ok(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.lora_stub import (
            LoraStubApplier,
        )

        applier = LoraStubApplier()
        ctx = ApplyContext(openjarvis_home=tmp_path, session_id="s1")
        result = applier.validate(_make_lora_edit(), ctx)
        assert not result.ok
        assert "v2" in result.reason.lower() or "deferred" in result.reason.lower()

    def test_apply_raises_not_implemented(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.appliers.lora_stub import (
            LoraStubApplier,
        )

        applier = LoraStubApplier()
        ctx = ApplyContext(openjarvis_home=tmp_path, session_id="s1")
        with pytest.raises(NotImplementedError, match="deferred to v2"):
            applier.apply(_make_lora_edit(), ctx)
