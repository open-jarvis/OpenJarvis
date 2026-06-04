"""Synthetic SFT-data generation for the orchestrator cold-start.

Turns NeuLab ADP (``neulab/agent-data-collection``) agent trajectories into
THOUGHT/TOOL/INPUT ``conversations`` JSONL that
:class:`~openjarvis.learning.intelligence.orchestrator.sft_trainer.OrchestratorSFTDataset`
loads directly.

Pipeline::

    ADP trajectory -> canonical Episode -> per-paradigm tiered renderings
        -> reward-ranked best-correct rendering -> conversations JSONL

Everything here runs with **no GPU and no API keys** (the cold-start does not
re-execute models; it re-tiers the demonstrated ADP traces).
"""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.sft_data.adp_loader import (
    CanonicalStep,
    iter_trajectories,
    trajectory_rows_to_episode,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.build import (
    build_sft_dataset,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.paradigms import (
    PARADIGMS,
    RenderedEpisode,
    render_all,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.select import select_best
from openjarvis.learning.intelligence.orchestrator.sft_data.serialize import to_record
from openjarvis.learning.intelligence.orchestrator.sft_data.tiers import (
    Difficulty,
    Tier,
    step_difficulty,
    tier_telemetry,
)

__all__ = [
    "CanonicalStep",
    "Difficulty",
    "PARADIGMS",
    "RenderedEpisode",
    "Tier",
    "build_sft_dataset",
    "iter_trajectories",
    "render_all",
    "select_best",
    "step_difficulty",
    "tier_telemetry",
    "to_record",
    "trajectory_rows_to_episode",
]
