"""SFT-data generation for the orchestrator cold-start.

Execution-grounded rejection sampling in the faithful ToolOrchestra action
space (arXiv:2511.21689): for each ``nvidia/ToolScale`` task, roll out a teacher
orchestrator over the unified tool catalog N times, verify each trajectory, keep
the cheapest passing one(s), and serialize them into the ``<tool_call>``
``conversations`` JSONL that
:class:`~openjarvis.learning.intelligence.orchestrator.sft_trainer.OrchestratorSFTDataset`
loads directly.

Pipeline::

    ToolScale task -> N teacher rollouts -> verify -> keep cheapest passing
        -> conversations JSONL

(The earlier ADP-relabel cold-start was a heuristic re-tiering of demonstrated
traces; it was removed in favour of this grounded pipeline.)
"""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
    gold_coverage_verify,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.toolscale import (
    GoldAction,
    ToolScaleTask,
    load_toolscale,
    normalize_row,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.unified_serialize import (
    trajectory_to_record,
)

__all__ = [
    "GoldAction",
    "ToolScaleTask",
    "generate_sft_dataset",
    "gold_coverage_verify",
    "load_toolscale",
    "normalize_row",
    "trajectory_to_record",
]
