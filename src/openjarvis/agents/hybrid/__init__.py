"""Hybrid local+cloud paradigms — ported from `hybrid-local-cloud-compute`.

Each module here registers one agent under ``@AgentRegistry.register("<name>")``:

    advisors          — executor (cloud) ↔ advisor (local) ↔ executor (cloud)
    conductor         — zero-shot planner emits a DAG of up to 5 worker calls
    minions           — supervisor (cloud) ↔ worker (local) reactive loop
    archon            — layered (generator → ranker → fuser) inference-time search
    skillorchestra    — skill-aware router picks one agent from a pool
    toolorchestra     — prompted multi-turn dispatcher over a mixed tool/model pool

All agents share :class:`LocalCloudAgent` as the base. They are bench-agnostic:
the caller formats the prompt (using ``hybrid_prompts.format_prompt(task, bench)``
or the bench's native formatter) and hands it in via ``run(input=...)``. Task
metadata that the paradigm needs (a problem statement vs. a question, hints,
etc.) goes through ``context.metadata``.

The hybrid harness at ``/matx/u/aspark/hybrid-local-cloud-compute`` is the
reference implementation and stays untouched — these ports are the
OpenJarvis-native versions of the same paradigms.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Import each paradigm to trigger its @AgentRegistry.register() decorator.
for _modname in (
    "advisors",
    "conductor",
    "minions",
    "archon",
    "skillorchestra",
    "toolorchestra",
    "mini_swe_agent",
):
    try:
        __import__(f"openjarvis.agents.hybrid.{_modname}")
    except Exception as exc:  # pragma: no cover — optional deps may be missing
        logger.debug("hybrid agent %s skipped: %s", _modname, exc)
