"""LoRA fine-tuning stub — deferred to v2.

The planner can emit LORA_FINETUNE edits so the diagnosis surfaces
"this should be a weight update" pressure to the user, but the executor
refuses them in v1.

See spec §4.1.
"""

from __future__ import annotations

from openjarvis.learning.distillation.execute.base import (
    ApplyContext,
    ApplyResult,
    EditApplier,
    ValidationResult,
)
from openjarvis.learning.distillation.models import Edit, EditOp


class LoraStubApplier(EditApplier):
    """Refuses LORA_FINETUNE with a clear v2 message."""

    op = EditOp.LORA_FINETUNE

    def validate(self, edit: Edit, ctx: ApplyContext) -> ValidationResult:
        return ValidationResult(
            ok=False,
            reason="LORA_FINETUNE is deferred to v2. "
            "The planner emitted this edit to signal that weight updates "
            "would help, but the executor cannot apply them yet.",
        )

    def apply(self, edit: Edit, ctx: ApplyContext) -> ApplyResult:
        raise NotImplementedError("LORA_FINETUNE deferred to v2")

    def rollback(self, edit: Edit, ctx: ApplyContext) -> None:
        pass
