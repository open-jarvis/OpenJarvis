"""Tests for openjarvis.learning.distillation.execute.base module."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestApplyContext:
    """Tests for ApplyContext dataclass."""

    def test_constructs(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.base import ApplyContext

        ctx = ApplyContext(openjarvis_home=tmp_path, session_id="s1")
        assert ctx.openjarvis_home == tmp_path
        assert ctx.session_id == "s1"

    def test_config_path(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.base import ApplyContext

        ctx = ApplyContext(openjarvis_home=tmp_path, session_id="s1")
        assert ctx.config_path == tmp_path / "config.toml"

    def test_agents_dir(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.base import ApplyContext

        ctx = ApplyContext(openjarvis_home=tmp_path, session_id="s1")
        assert ctx.agents_dir == tmp_path / "agents"

    def test_tools_dir(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.execute.base import ApplyContext

        ctx = ApplyContext(openjarvis_home=tmp_path, session_id="s1")
        assert ctx.tools_dir == tmp_path / "tools"


class TestValidationResult:
    """Tests for ValidationResult."""

    def test_ok_result(self) -> None:
        from openjarvis.learning.distillation.execute.base import ValidationResult

        r = ValidationResult(ok=True)
        assert r.ok is True
        assert r.reason == ""

    def test_error_result(self) -> None:
        from openjarvis.learning.distillation.execute.base import ValidationResult

        r = ValidationResult(ok=False, reason="target not found")
        assert r.ok is False
        assert r.reason == "target not found"


class TestEditApplierRegistry:
    """Tests for EditApplierRegistry."""

    def test_register_and_get(self) -> None:
        from openjarvis.learning.distillation.execute.base import (
            ApplyContext,
            ApplyResult,
            EditApplier,
            EditApplierRegistry,
            ValidationResult,
        )
        from openjarvis.learning.distillation.models import Edit, EditOp

        class FakeApplier(EditApplier):
            op = EditOp.SET_MODEL_PARAM

            def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
                return ValidationResult(ok=True)

            def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
                return ApplyResult()

            def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
                pass

        registry = EditApplierRegistry()
        registry.register(FakeApplier())
        assert registry.is_supported(EditOp.SET_MODEL_PARAM)
        applier = registry.get(EditOp.SET_MODEL_PARAM)
        assert isinstance(applier, FakeApplier)

    def test_is_supported_returns_false_for_unregistered(self) -> None:
        from openjarvis.learning.distillation.execute.base import (
            EditApplierRegistry,
        )
        from openjarvis.learning.distillation.models import EditOp

        registry = EditApplierRegistry()
        assert registry.is_supported(EditOp.LORA_FINETUNE) is False

    def test_get_raises_for_unregistered(self) -> None:
        from openjarvis.learning.distillation.execute.base import (
            EditApplierRegistry,
        )
        from openjarvis.learning.distillation.models import EditOp

        registry = EditApplierRegistry()
        with pytest.raises(KeyError):
            registry.get(EditOp.LORA_FINETUNE)
