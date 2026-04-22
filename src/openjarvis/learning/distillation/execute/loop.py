"""Per-edit execution loop for the distillation execute phase.

Iterates over a plan's edits, handles tier routing, validates, and applies.
Does NOT include the benchmark gate — that's wired in M5.

See spec §7.2.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from openjarvis.learning.distillation.execute.appliers.agent import (
    EditFewShotExemplarsApplier,
    PatchSystemPromptApplier,
    ReplaceSystemPromptApplier,
    SetAgentClassApplier,
    SetAgentParamApplier,
)
from openjarvis.learning.distillation.execute.appliers.intelligence import (
    SetModelForQueryClassApplier,
    SetModelParamApplier,
)
from openjarvis.learning.distillation.execute.appliers.lora_stub import (
    LoraStubApplier,
)
from openjarvis.learning.distillation.execute.appliers.tools import (
    AddToolToAgentApplier,
    EditToolDescriptionApplier,
    RemoveToolFromAgentApplier,
)
from openjarvis.learning.distillation.execute.base import (
    ApplyContext,
    EditApplierRegistry,
)
from openjarvis.learning.distillation.models import (
    AutonomyMode,
    Edit,
    EditOutcome,
    EditRiskTier,
)

logger = logging.getLogger(__name__)


def _build_registry() -> EditApplierRegistry:
    """Build and populate the default applier registry."""
    registry = EditApplierRegistry()
    registry.register(SetModelForQueryClassApplier())
    registry.register(SetModelParamApplier())
    registry.register(PatchSystemPromptApplier())
    registry.register(ReplaceSystemPromptApplier())
    registry.register(SetAgentClassApplier())
    registry.register(SetAgentParamApplier())
    registry.register(EditFewShotExemplarsApplier())
    registry.register(AddToolToAgentApplier())
    registry.register(RemoveToolFromAgentApplier())
    registry.register(EditToolDescriptionApplier())
    registry.register(LoraStubApplier())
    return registry


def execute_edits(
    *,
    edits: list[Edit],
    ctx: ApplyContext,
    autonomy_mode: AutonomyMode,
    registry: EditApplierRegistry | None = None,
) -> list[EditOutcome]:
    """Execute a list of edits, returning outcomes for each.

    This loop handles tier routing and validation but does NOT include
    the benchmark gate (wired in M5).

    Parameters
    ----------
    edits :
        The edits to process.
    ctx :
        Shared context with config paths.
    autonomy_mode :
        How aggressively to apply edits.
    registry :
        Optional pre-built registry. If None, builds the default.
    """
    if registry is None:
        registry = _build_registry()

    outcomes: list[EditOutcome] = []

    for edit in edits:
        # Manual mode: everything goes to review
        if autonomy_mode == AutonomyMode.MANUAL:
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="pending_review",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error=None,
                    applied_at=None,
                )
            )
            continue

        # Manual tier: always skip
        if edit.risk_tier == EditRiskTier.MANUAL:
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="skipped",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error="manual tier, requires explicit approval",
                    applied_at=None,
                )
            )
            continue

        # Review tier in tiered mode: route to pending
        if (
            edit.risk_tier == EditRiskTier.REVIEW
            and autonomy_mode == AutonomyMode.TIERED
        ):
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="pending_review",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error=None,
                    applied_at=None,
                )
            )
            continue

        # Check if the op is supported
        if not registry.is_supported(edit.op):
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="skipped",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error=f"op {edit.op.value} not implemented in v1",
                    applied_at=None,
                )
            )
            continue

        # Validate
        applier = registry.get(edit.op)
        validation = applier.validate(edit, ctx)
        if not validation.ok:
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="rejected_by_gate",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error=validation.reason,
                    applied_at=None,
                )
            )
            continue

        # Apply
        try:
            applier.apply(edit, ctx)
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="applied",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error=None,
                    applied_at=datetime.now(timezone.utc),
                )
            )
        except Exception as e:
            logger.warning("Edit %s failed: %s", edit.id, e)
            outcomes.append(
                EditOutcome(
                    edit_id=edit.id,
                    status="rejected_by_gate",
                    benchmark_delta=None,
                    cluster_deltas={},
                    error=str(e),
                    applied_at=None,
                )
            )

    return outcomes
