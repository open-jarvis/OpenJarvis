"""AgentConfigEvolver — analyze traces to evolve agent TOML configs.

Reads interaction traces to determine which agent/tool/parameter
combinations perform best for different query classes, then writes
updated TOML config files with automatic versioning and rollback.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openjarvis.core.types import StepType, Trace
from openjarvis.learning.routing._utils import classify_query
from openjarvis.traces.store import TraceStore


def _format_toml_value(value: Any) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        # Escape backslashes and quotes for TOML basic strings
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        items = ", ".join(_format_toml_value(v) for v in value)
        return f"[{items}]"
    return repr(value)


def _write_toml(path: Path, data: Dict[str, Any]) -> None:
    """Write a dict as TOML to *path* using manual formatting."""
    lines: List[str] = []
    for section_name, section_data in data.items():
        if isinstance(section_data, dict):
            lines.append(f"[{section_name}]")
            for key, value in section_data.items():
                lines.append(f"{key} = {_format_toml_value(value)}")
            lines.append("")
        else:
            lines.append(f"{section_name} = {_format_toml_value(section_data)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class AgentConfigEvolver:
    """Analyze traces to evolve agent TOML configs with versioning.

    Parameters
    ----------
    trace_store:
        A :class:`TraceStore` used to fetch historical traces.
    config_dir:
        Directory where agent TOML configs are written.
    min_quality:
        Minimum average feedback score for a recommendation to be emitted.
    """

    def __init__(
        self,
        trace_store: TraceStore,
        *,
        config_dir: Union[str, Path],
        min_quality: float = 0.5,
    ) -> None:
        self._store = trace_store
        self._config_dir = Path(config_dir)
        self._history_dir = self._config_dir / ".history"
        self._min_quality = min_quality

        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._history_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # analyze
    # ------------------------------------------------------------------

    def analyze(self) -> List[Dict[str, Any]]:
        """Analyze traces, return recommendations per query class.

        Returns a list of dicts, each containing:
        - ``query_class``: the classified query category
        - ``recommended_tools``: list of tool names sorted by frequency
        - ``recommended_agent``: the best-performing agent for this class
        - ``recommended_max_turns``: suggested max_turns value
        - ``sample_count``: number of traces analyzed for this class
        """
        traces = self._store.list_traces(limit=10_000)
        if not traces:
            return []

        # Group traces by query class
        groups: Dict[str, List[Trace]] = defaultdict(list)
        for trace in traces:
            qclass = classify_query(trace.query)
            groups[qclass].append(trace)

        recommendations: List[Dict[str, Any]] = []
        for qclass, class_traces in sorted(groups.items()):
            rec = self._analyze_class(qclass, class_traces)
            if rec is not None:
                recommendations.append(rec)

        return recommendations

    def _analyze_class(
        self, qclass: str, traces: List[Trace]
    ) -> Optional[Dict[str, Any]]:
        """Build a recommendation for a single query class."""
        # Collect tool usage, agent performance, and turn counts
        tool_scores: Dict[str, _ToolScore] = defaultdict(lambda: _ToolScore())
        agent_scores: Dict[str, _AgentScore] = defaultdict(lambda: _AgentScore())
        turn_counts: List[int] = []

        for trace in traces:
            feedback = trace.feedback if trace.feedback is not None else 0.0
            is_success = trace.outcome == "success"

            # Count tools used in this trace
            trace_tools: List[str] = []
            tool_call_count = 0
            for step in trace.steps:
                step_type = (
                    step.step_type.value
                    if isinstance(step.step_type, StepType)
                    else str(step.step_type)
                )
                if step_type == "tool_call":
                    tool_call_count += 1
                    tool_name = step.input.get("tool", "")
                    if tool_name:
                        trace_tools.append(tool_name)
                        ts = tool_scores[tool_name]
                        ts.count += 1
                        ts.feedback_sum += feedback
                        if is_success:
                            ts.successes += 1

            turn_counts.append(tool_call_count)

            # Track agent performance
            if trace.agent:
                ag = agent_scores[trace.agent]
                ag.count += 1
                ag.feedback_sum += feedback
                if is_success:
                    ag.successes += 1

        if not agent_scores:
            return None

        # Pick best agent by composite score
        best_agent = max(agent_scores.items(), key=lambda kv: kv[1].composite_score())[
            0
        ]

        # Rank tools by composite score (frequency-weighted quality)
        ranked_tools = sorted(
            tool_scores.items(),
            key=lambda kv: kv[1].composite_score(),
            reverse=True,
        )
        recommended_tools = [name for name, _ in ranked_tools]

        # Recommended max_turns: use the 75th percentile of observed tool calls
        # plus a small buffer, minimum 5
        if turn_counts:
            sorted_turns = sorted(turn_counts)
            p75_idx = int(len(sorted_turns) * 0.75)
            p75 = sorted_turns[min(p75_idx, len(sorted_turns) - 1)]
            recommended_max_turns = max(p75 + 2, 5)
        else:
            recommended_max_turns = 10

        return {
            "query_class": qclass,
            "recommended_tools": recommended_tools,
            "recommended_agent": best_agent,
            "recommended_max_turns": recommended_max_turns,
            "sample_count": len(traces),
        }

    # ------------------------------------------------------------------
    # write_config
    # ------------------------------------------------------------------

    def write_config(
        self,
        agent_name: str,
        *,
        tools: List[str],
        max_turns: int = 10,
        temperature: float = 0.3,
        system_prompt: str = "",
    ) -> Path:
        """Write agent TOML config, archiving previous version first.

        Returns the :class:`Path` to the written config file.
        """
        config_path = self._config_dir / f"{agent_name}.toml"

        # Archive the existing config before overwriting
        if config_path.exists():
            self._archive(agent_name, config_path)

        # Build the TOML data
        data = {
            "agent": {
                "name": agent_name,
                "tools": tools,
                "max_turns": max_turns,
                "temperature": temperature,
                "system_prompt": system_prompt,
            }
        }

        _write_toml(config_path, data)
        return config_path

    # ------------------------------------------------------------------
    # list_versions
    # ------------------------------------------------------------------

    def list_versions(self, agent_name: str) -> List[Dict[str, Any]]:
        """List all versions (including current) for *agent_name*.

        Returns a list of dicts with ``version``, ``path``, and ``modified``.
        Versions are numbered starting from 1 (oldest archived) through to
        the current (highest version number).
        """
        versions: List[Dict[str, Any]] = []

        # Collect archived versions from .history/
        pattern = f"{agent_name}.v*.toml"
        archived = sorted(self._history_dir.glob(pattern))
        for idx, archived_path in enumerate(archived, start=1):
            versions.append(
                {
                    "version": idx,
                    "path": str(archived_path),
                    "modified": archived_path.stat().st_mtime,
                }
            )

        # Current version
        current = self._config_dir / f"{agent_name}.toml"
        if current.exists():
            versions.append(
                {
                    "version": len(versions) + 1,
                    "path": str(current),
                    "modified": current.stat().st_mtime,
                }
            )

        return versions

    # ------------------------------------------------------------------
    # rollback
    # ------------------------------------------------------------------

    def rollback(self, agent_name: str, version: int) -> None:
        """Rollback to a specific version.

        Raises :class:`ValueError` if the requested version does not exist.
        """
        versions = self.list_versions(agent_name)
        target = None
        for v in versions:
            if v["version"] == version:
                target = v
                break

        if target is None:
            raise ValueError(
                f"Version {version} not found for agent '{agent_name}'. "
                f"Available versions: {[v['version'] for v in versions]}"
            )

        target_path = Path(target["path"])
        config_path = self._config_dir / f"{agent_name}.toml"

        # If the target is already the current file, nothing to do
        if target_path == config_path:
            return

        # Archive current before rollback
        if config_path.exists():
            self._archive(agent_name, config_path)

        # Copy the target version to become the current config
        shutil.copy2(str(target_path), str(config_path))

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _archive(self, agent_name: str, config_path: Path) -> Path:
        """Copy *config_path* into ``.history/`` with a version suffix."""
        # Determine next version number in .history/
        pattern = f"{agent_name}.v*.toml"
        existing = list(self._history_dir.glob(pattern))
        version_nums = []
        for p in existing:
            # Extract version number from name like "my_agent.v3.toml"
            stem = p.stem  # "my_agent.v3"
            parts = stem.rsplit(".v", 1)
            if len(parts) == 2 and parts[1].isdigit():
                version_nums.append(int(parts[1]))
        next_ver = max(version_nums, default=0) + 1

        dest = self._history_dir / f"{agent_name}.v{next_ver}.toml"
        shutil.copy2(str(config_path), str(dest))
        return dest


class _ToolScore:
    """Accumulator for per-tool scoring."""

    __slots__ = ("count", "successes", "feedback_sum")

    def __init__(self) -> None:
        self.count = 0
        self.successes = 0
        self.feedback_sum = 0.0

    def composite_score(self) -> float:
        """Weighted score combining success rate, feedback, and frequency."""
        if self.count == 0:
            return 0.0
        sr = self.successes / self.count
        fb = self.feedback_sum / self.count
        # Weight: 40% success + 40% feedback + 20% log-frequency
        import math

        freq_bonus = math.log1p(self.count) / 10.0
        return 0.4 * sr + 0.4 * fb + 0.2 * min(freq_bonus, 1.0)


class _AgentScore:
    """Accumulator for per-agent scoring."""

    __slots__ = ("count", "successes", "feedback_sum")

    def __init__(self) -> None:
        self.count = 0
        self.successes = 0
        self.feedback_sum = 0.0

    def composite_score(self) -> float:
        """Weighted score combining success rate and feedback."""
        if self.count == 0:
            return 0.0
        sr = self.successes / self.count
        fb = self.feedback_sum / self.count
        return 0.6 * sr + 0.4 * fb


__all__ = ["AgentConfigEvolver"]
