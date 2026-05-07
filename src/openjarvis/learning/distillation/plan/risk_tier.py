"""Deterministic risk tier assignment for edits.

The teacher cannot pick its own tier. After the teacher emits edits, the
planner overwrites each edit's ``risk_tier`` from the lookup table below.
If the teacher attempted a different tier, it is silently overwritten and
the discrepancy is logged but not surfaced as an error.

See spec §4.1 (tier table) and §6.2.
"""

from __future__ import annotations

import logging
from typing import Sequence

from openjarvis.learning.distillation.models import Edit, EditOp, EditRiskTier

logger = logging.getLogger(__name__)

# The canonical (op) → tier mapping. Every EditOp must appear here.
TIER_TABLE: dict[EditOp, EditRiskTier] = {
    # Intelligence — safe, reversible
    EditOp.SET_MODEL_FOR_QUERY_CLASS: EditRiskTier.AUTO,
    EditOp.SET_MODEL_PARAM: EditRiskTier.AUTO,
    # Agent — params are safe, prompts and class need review
    EditOp.PATCH_SYSTEM_PROMPT: EditRiskTier.REVIEW,
    EditOp.REPLACE_SYSTEM_PROMPT: EditRiskTier.REVIEW,
    EditOp.SET_AGENT_CLASS: EditRiskTier.REVIEW,
    EditOp.SET_AGENT_PARAM: EditRiskTier.AUTO,
    EditOp.EDIT_FEW_SHOT_EXEMPLARS: EditRiskTier.REVIEW,
    # Tools — all safe, reversible
    EditOp.ADD_TOOL_TO_AGENT: EditRiskTier.AUTO,
    EditOp.REMOVE_TOOL_FROM_AGENT: EditRiskTier.AUTO,
    EditOp.EDIT_TOOL_DESCRIPTION: EditRiskTier.AUTO,
    # v2 — always manual
    EditOp.LORA_FINETUNE: EditRiskTier.MANUAL,
}


def assign_tier(op: EditOp) -> EditRiskTier:
    """Return the deterministic risk tier for a given edit op."""
    return TIER_TABLE[op]


def assign_tiers(edits: Sequence[Edit]) -> list[Edit]:
    """Overwrite each edit's risk_tier from the canonical lookup table.

    Returns a new list of Edit objects (pydantic copies). If the teacher
    had a different tier, it is silently overwritten and logged.
    """
    result = []
    for edit in edits:
        correct_tier = assign_tier(edit.op)
        if edit.risk_tier != correct_tier:
            logger.info(
                "Edit %s: overwriting teacher tier %s → %s (op=%s)",
                edit.id,
                edit.risk_tier.value,
                correct_tier.value,
                edit.op.value,
            )
        result.append(edit.model_copy(update={"risk_tier": correct_tier}))
    return result
