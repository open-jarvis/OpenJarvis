"""SFT-data generation for the orchestrator cold-start.

Execution-grounded rejection sampling: for each reasoning task (GeneralThought +
OpenThoughts, via :func:`~...sft_data.datasets.load_sft_tasks`), roll out a
teacher orchestrator over the unified tool catalog N times, verify each
trajectory, keep the cheapest passing one(s), and serialize them into the
``<tool_call>`` ``conversations`` JSONL that
:class:`~openjarvis.learning.intelligence.orchestrator.sft_trainer.OrchestratorSFTDataset`
loads directly.

Pipeline::

    reasoning task -> N teacher rollouts -> verify -> keep cheapest passing
        -> conversations JSONL
"""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.unified_serialize import (
    trajectory_to_record,
)

__all__ = [
    "generate_sft_dataset",
    "trajectory_to_record",
]
