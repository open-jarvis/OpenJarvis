"""LearningPlanner: converts a diagnosis into a frozen LearningPlan.

Makes a single structured-output teacher call (no tools, no multi-turn)
to generate typed edits for each failure cluster. Post-processes the
edits with risk tier assignment and patch/replace downgrade.

See spec §6.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openjarvis.learning.spec_search.models import (
    Edit,
    FailureCluster,
    LearningPlan,
)
from openjarvis.learning.spec_search.plan.prompt_diff import (
    maybe_downgrade_to_replace,
)
from openjarvis.learning.spec_search.plan.risk_tier import assign_tiers

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM_PROMPT = """\
You are a meta-engineer planning improvements to a local AI assistant called \
OpenJarvis. You have been given a diagnosis of the student's failure patterns.

Your job: for each surviving failure cluster, propose 1-3 edits from the \
available operation set that would address the cluster's skill gap.

IMPORTANT: Each edit's payload must EXACTLY match the schema below. \
Edits with missing required payload keys will be rejected.

Available operations with their EXACT payload schemas:

INTELLIGENCE pillar:
- set_model_for_query_class: {{"query_class": "math", "model": "qwen3.5:27b"}}
- set_model_param: {{"model": "qwen3.5:9b", "param": "temperature", "value": 0.3}}

AGENT pillar:
- replace_system_prompt: {{"new_content": "You are a helpful assistant.\\n..."}}
- patch_system_prompt: {{"diff": "--- a/prompt.md\\n+++ b/prompt.md\\n@@ ...\\n"}}
- set_agent_class: {{"agent": "simple", "new_class": "react"}}
- set_agent_param: {{"agent": "native_react", "param": "max_turns", "value": 10}}
- edit_few_shot_exemplars: {{"agent": "native_react", \
"exemplars": [{{"input": "Q", "output": "A"}}]}}

TOOLS pillar:
- add_tool_to_agent: {{"agent": "native_react", "tool_name": "calculator"}}
- remove_tool_from_agent: {{"agent": "native_react", "tool_name": "shell_exec"}}
- edit_tool_description: {{"tool_name": "web_search", \
"new_description": "Search the web for..."}}

Each edit object must have ALL of these fields:
- id (string, e.g. "edit_001")
- pillar ("intelligence", "agent", or "tools")
- op (one of the operation names above)
- target (dotted path, e.g. "agents.native_react.system_prompt")
- payload (object matching the schema above for the chosen op)
- rationale (string explaining why)
- expected_improvement (cluster id this addresses)
- risk_tier ("auto" for safe changes, "review" for prompts)
- references (list of trace ids that justify this edit)

Respond with ONLY a JSON object: {{"edits": [...]}}
"""


def _validate_clusters(
    clusters: list[FailureCluster],
) -> tuple[list[FailureCluster], list[FailureCluster]]:
    """Split clusters into surviving and dropped.

    Drops clusters where both student_failure_rate and teacher_success_rate
    are 0 (no evidence). Dropped clusters get a marker in skill_gap.
    """
    surviving = []
    dropped = []
    for cluster in clusters:
        if cluster.student_failure_rate == 0.0 and cluster.teacher_success_rate == 0.0:
            marked = cluster.model_copy(
                update={
                    "skill_gap": (
                        "dropped: insufficient evidence"
                        f" (original: {cluster.skill_gap})"
                    ),
                    "addressed_by_edit_ids": [],
                }
            )
            dropped.append(marked)
        else:
            surviving.append(cluster)
    return surviving, dropped


class LearningPlanner:
    """Converts a diagnosis into a frozen LearningPlan.

    Parameters
    ----------
    teacher_engine :
        CloudEngine (or mock) for the planner call.
    teacher_model :
        Frontier model id.
    session_id :
        Current session id.
    session_dir :
        Path for persisting plan.json and teacher_traces/plan.jsonl.
    prompt_reader :
        Callable that takes a target string and returns the current prompt
        content. Used by the patch/replace downgrade logic.
    """

    def __init__(
        self,
        *,
        teacher_engine: Any,
        teacher_model: str,
        session_id: str,
        session_dir: Path,
        prompt_reader: Callable[[str], str],
    ) -> None:
        self._engine = teacher_engine
        self._model = teacher_model
        self._session_id = session_id
        self._session_dir = Path(session_dir)
        self._prompt_reader = prompt_reader

    def run(
        self,
        *,
        diagnosis_md: str,
        clusters: list[FailureCluster],
    ) -> LearningPlan:
        """Execute the plan phase.

        Parameters
        ----------
        diagnosis_md :
            The teacher's diagnosis markdown from phase 1.
        clusters :
            Failure clusters from phase 1.

        Returns
        -------
        LearningPlan
            The frozen plan, also persisted to ``plan.json``.
        """
        self._session_dir.mkdir(parents=True, exist_ok=True)

        # Validate clusters — drop those without evidence
        surviving, dropped = _validate_clusters(clusters)

        # Build the user prompt with diagnosis and cluster info
        cluster_json = json.dumps(
            [c.model_dump() for c in surviving],
            indent=2,
            default=str,
        )
        user_prompt = (
            f"## Diagnosis\n\n{diagnosis_md}\n\n"
            f"## Surviving Failure Clusters\n\n```json\n{cluster_json}\n```\n\n"
            "Propose edits for these clusters. Respond with ONLY JSON: "
            '{"edits": [...]}'
        )

        # Make the teacher call
        from openjarvis.core.types import Message, Role

        messages = [
            Message(role=Role.SYSTEM, content=_PLANNER_SYSTEM_PROMPT),
            Message(role=Role.USER, content=user_prompt),
        ]
        result = self._engine.generate(
            messages=messages,
            model=self._model,
            max_tokens=4096,
        )

        cost_usd = result.get("cost_usd", 0.0)
        content = result.get("content", "")

        # Persist teacher trace
        self._persist_trace(content, cost_usd, result)

        # Parse edits from response
        edits = self._parse_edits(content)

        # Post-process: assign tiers deterministically
        edits = assign_tiers(edits)

        # Post-process: downgrade large patches to replacements
        edits = [
            maybe_downgrade_to_replace(e, prompt_reader=self._prompt_reader)
            for e in edits
        ]

        # Wire clusters ↔ edits
        surviving = self._wire_cluster_edit_ids(surviving, edits)

        # Build the plan
        all_clusters = surviving + dropped
        plan = LearningPlan(
            session_id=self._session_id,
            diagnosis_summary=diagnosis_md,
            failure_clusters=all_clusters,
            edits=edits,
            teacher_model=self._model,
            estimated_cost_usd=cost_usd,
            created_at=datetime.now(timezone.utc),
        )

        # Persist plan.json
        plan_path = self._session_dir / "plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        return plan

    def _parse_edits(self, content: str) -> list[Edit]:
        """Parse edits from the teacher's JSON response."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON in the content
            import re

            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    logger.warning("Could not parse edits from teacher response")
                    return []
            else:
                logger.warning("No JSON found in teacher response")
                return []

        raw_edits = data.get("edits", [])
        edits = []
        for raw in raw_edits:
            try:
                edits.append(Edit.model_validate(raw))
            except Exception as e:
                logger.warning("Skipping invalid edit: %s — %s", raw.get("id", "?"), e)
        return edits

    def _wire_cluster_edit_ids(
        self,
        clusters: list[FailureCluster],
        edits: list[Edit],
    ) -> list[FailureCluster]:
        """Populate addressed_by_edit_ids on each cluster."""
        cluster_map: dict[str, list[str]] = {c.id: [] for c in clusters}
        for edit in edits:
            if edit.expected_improvement in cluster_map:
                cluster_map[edit.expected_improvement].append(edit.id)
        return [
            c.model_copy(update={"addressed_by_edit_ids": cluster_map.get(c.id, [])})
            for c in clusters
        ]

    def _persist_trace(self, content: str, cost_usd: float, result: dict) -> None:
        """Write the planner call to teacher_traces/plan.jsonl."""
        traces_dir = self._session_dir / "teacher_traces"
        traces_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call": "planner",
            "content_length": len(content),
            "cost_usd": cost_usd,
            "tokens": result.get("usage", {}).get("total_tokens", 0),
        }
        jsonl_path = traces_dir / "plan.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
