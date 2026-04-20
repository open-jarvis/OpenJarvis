"""Skill discovery -- mine recurring tool sequences from traces."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(slots=True)
class DiscoveredSkill:
    """A skill discovered from trace analysis."""

    name: str
    description: str
    tool_sequence: List[str]  # ordered tool names
    frequency: int  # how often this sequence appeared
    avg_outcome: float  # average outcome score
    example_inputs: List[str] = field(default_factory=list)


class SkillDiscovery:
    """Mine recurring tool sequences from trace data to auto-generate skills.

    Analyzes TraceStore data for patterns like:
    - "web_search -> file_write" (research-then-save)
    - "file_read -> calculator -> file_write" (read-compute-save)

    When a sequence appears >= min_frequency times with positive outcomes,
    it's surfaced as a DiscoveredSkill that can be registered.
    """

    def __init__(
        self,
        *,
        min_frequency: int = 3,
        min_sequence_length: int = 2,
        max_sequence_length: int = 4,
        min_outcome: float = 0.5,
    ) -> None:
        self._min_freq = min_frequency
        self._min_len = min_sequence_length
        self._max_len = max_sequence_length
        self._min_outcome = min_outcome
        self._discovered: List[DiscoveredSkill] = []

    def analyze_traces(self, traces: List[Any]) -> List[DiscoveredSkill]:
        """Analyze a list of traces for recurring tool sequences.

        Parameters
        ----------
        traces:
            List of Trace objects (or dicts with 'steps' and 'outcome' keys).
            Each trace should have steps with 'step_type' and 'tool_name'.

        Returns
        -------
        List of DiscoveredSkill objects meeting frequency and outcome thresholds.
        """
        # Extract tool sequences from traces
        sequence_data: Dict[Tuple[str, ...], List[float]] = defaultdict(list)
        sequence_inputs: Dict[Tuple[str, ...], List[str]] = defaultdict(list)

        for trace in traces:
            tool_calls = self._extract_tool_sequence(trace)
            outcome = self._extract_outcome(trace)
            query = self._extract_query(trace)

            if len(tool_calls) < self._min_len:
                continue

            # Generate all subsequences of valid length
            upper = min(self._max_len + 1, len(tool_calls) + 1)
            for length in range(self._min_len, upper):
                for start in range(len(tool_calls) - length + 1):
                    seq = tuple(tool_calls[start : start + length])
                    sequence_data[seq].append(outcome)
                    if query and len(sequence_inputs[seq]) < 3:
                        sequence_inputs[seq].append(query)

        # Filter by frequency and outcome
        discovered = []
        for seq, outcomes in sequence_data.items():
            freq = len(outcomes)
            avg_outcome = sum(outcomes) / len(outcomes) if outcomes else 0.0

            if freq >= self._min_freq and avg_outcome >= self._min_outcome:
                name = "_".join(seq)
                desc = f"Auto-discovered skill: {' -> '.join(seq)} (seen {freq} times)"
                discovered.append(
                    DiscoveredSkill(
                        name=name,
                        description=desc,
                        tool_sequence=list(seq),
                        frequency=freq,
                        avg_outcome=avg_outcome,
                        example_inputs=sequence_inputs.get(seq, []),
                    )
                )

        # Sort by frequency * outcome (quality score)
        discovered.sort(key=lambda s: s.frequency * s.avg_outcome, reverse=True)
        self._discovered = discovered
        return discovered

    def _extract_tool_sequence(self, trace: Any) -> List[str]:
        """Extract ordered list of tool names from a trace."""
        if isinstance(trace, dict):
            steps = trace.get("steps", [])
        elif hasattr(trace, "steps"):
            steps = trace.steps
        else:
            return []

        tools = []
        for step in steps:
            if isinstance(step, dict):
                if step.get("step_type") == "tool_call":
                    name = step.get("tool_name", step.get("name", ""))
                    if name:
                        tools.append(name)
            elif hasattr(step, "step_type"):
                st = step.step_type
                is_tool = str(st) == "tool_call" or (
                    hasattr(st, "value") and st.value == "tool_call"
                )
                if is_tool:
                    name = getattr(
                        step,
                        "tool_name",
                        getattr(step, "name", ""),
                    )
                    # Also check step.input dict for tool name (TraceStep format)
                    if not name:
                        step_input = getattr(step, "input", {}) or {}
                        if isinstance(step_input, dict):
                            name = step_input.get("tool", "") or ""
                    if name:
                        tools.append(name)
        return tools

    def _extract_outcome(self, trace: Any) -> float:
        """Extract outcome score from a trace.

        Handles both numeric outcome scores and string labels
        ("success" / "failure").  Falls back to the ``feedback`` field when
        present, then defaults to 0.0.
        """
        if isinstance(trace, dict):
            raw = trace.get("outcome")
            if raw is None:
                return float(trace.get("feedback", 0.0) or 0.0)
        else:
            raw = getattr(trace, "outcome", None)
            if raw is None:
                return float(getattr(trace, "feedback", 0.0) or 0.0)

        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            lraw = raw.lower()
            if lraw == "success":
                return 1.0
            if lraw == "failure":
                return 0.0
            try:
                return float(raw)
            except ValueError:
                return 0.0
        return 0.0

    def _extract_query(self, trace: Any) -> str:
        """Extract the original query from a trace."""
        if isinstance(trace, dict):
            return trace.get("query", "")
        return getattr(trace, "query", "")

    @property
    def discovered_skills(self) -> List[DiscoveredSkill]:
        """Return the most recently discovered skills."""
        return list(self._discovered)

    def to_skill_manifests(self) -> List[Dict[str, Any]]:
        """Convert discovered skills to TOML-compatible manifest dicts."""
        manifests = []
        for skill in self._discovered:
            manifests.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "steps": [
                        {"tool": tool, "params": {}} for tool in skill.tool_sequence
                    ],
                    "metadata": {
                        "auto_discovered": True,
                        "frequency": skill.frequency,
                        "avg_outcome": skill.avg_outcome,
                    },
                }
            )
        return manifests


__all__ = ["DiscoveredSkill", "SkillDiscovery"]
