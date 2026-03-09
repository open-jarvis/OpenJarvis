"""ICL example updater + skill discovery from traces."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import AgentLearningPolicy

logger = logging.getLogger(__name__)


@LearningRegistry.register("icl_updater")
class ICLUpdaterPolicy(AgentLearningPolicy):
    """Updates in-context examples and discovers skills from traces.

    Analyzes traces for successful tool call patterns, extracts
    in-context learning examples, and discovers reusable multi-tool
    sequences ("skills").  This updates *agent* logic (ICL examples
    and tool-use strategies), not tool implementations themselves.
    """

    def __init__(
        self,
        *,
        min_score: float = 0.7,
        max_examples: int = 20,
        min_skill_occurrences: int = 3,
        auto_apply: bool = False,
    ) -> None:
        self._min_score = min_score
        self._max_examples = max_examples
        self._min_skill_occurrences = min_skill_occurrences
        self._auto_apply = auto_apply
        self._examples: List[Dict[str, Any]] = []
        self._skills: List[Dict[str, Any]] = []
        # Versioned example database for add_example / rollback
        self._example_db: List[Dict[str, Any]] = []
        self._version: int = 0

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        """Analyze traces and extract ICL examples + skills."""
        try:
            traces = trace_store.list_traces()
        except Exception as exc:
            logger.warning("ICL updater failed: %s", exc)
            return {"examples": [], "skills": []}

        # Extract high-scoring traces with tool calls
        new_examples: List[Dict[str, Any]] = []
        tool_sequences: List[List[str]] = []

        for trace in traces:
            # Only consider successful traces
            if trace.outcome != "success":
                continue

            feedback = trace.feedback if trace.feedback is not None else 0.5
            if feedback < self._min_score:
                continue

            # Extract tool call steps
            tool_steps = [
                s
                for s in (trace.steps or [])
                if s.step_type.value == "tool_call"
            ]

            if tool_steps:
                # Build ICL example
                tool_names = [
                    s.metadata.get("tool_name", "")
                    for s in tool_steps
                ]
                example = {
                    "query": trace.query,
                    "tools_used": tool_names,
                    "outcome": trace.outcome,
                    "score": feedback,
                }
                new_examples.append(example)
                tool_sequences.append(tool_names)

        # Keep top examples by score
        new_examples.sort(key=lambda x: x["score"], reverse=True)
        self._examples = new_examples[: self._max_examples]

        # Discover skills: recurring multi-tool sequences
        self._skills = self._discover_skills(tool_sequences)

        return {
            "examples": list(self._examples),
            "skills": list(self._skills),
            "traces_analyzed": len(traces),
        }

    def _discover_skills(self, sequences: List[List[str]]) -> List[Dict[str, Any]]:
        """Find recurring tool call sequences."""
        # Count subsequences of length 2+
        seq_counts: Dict[str, int] = {}
        for seq in sequences:
            if len(seq) < 2:
                continue
            # Check all subsequences of length 2-4
            for length in range(2, min(len(seq) + 1, 5)):
                for start in range(len(seq) - length + 1):
                    sub = tuple(seq[start : start + length])
                    key = " -> ".join(sub)
                    seq_counts[key] = seq_counts.get(key, 0) + 1

        # Filter by minimum occurrences
        skills: List[Dict[str, Any]] = []
        for seq_key, count in seq_counts.items():
            if count >= self._min_skill_occurrences:
                skills.append(
                    {
                        "sequence": seq_key,
                        "occurrences": count,
                        "tools": seq_key.split(" -> "),
                    }
                )

        # Sort by frequency
        skills.sort(key=lambda x: x["occurrences"], reverse=True)
        return skills

    # -- Versioned example database methods ------------------------------------

    def add_example(
        self,
        query: str,
        response: str,
        outcome: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Add an ICL example if it meets the quality threshold.

        Parameters
        ----------
        query:
            The user query that produced this example.
        response:
            The agent/model response.
        outcome:
            Quality score in [0, 1].
        metadata:
            Optional metadata dict attached to the example.

        Returns
        -------
        True if the example was accepted, False if rejected (below threshold).
        """
        if outcome < self._min_score:
            return False

        self._version += 1
        entry: Dict[str, Any] = {
            "query": query,
            "response": response,
            "outcome": outcome,
            "metadata": metadata or {},
            "version": self._version,
        }
        self._example_db.append(entry)

        # Trim to max_examples (remove oldest first)
        if len(self._example_db) > self._max_examples:
            self._example_db = self._example_db[-self._max_examples:]

        return True

    def rollback(self, version: int) -> None:
        """Remove all examples added after the given version.

        Parameters
        ----------
        version:
            The version checkpoint to rollback to.  All examples with
            ``version > checkpoint`` are removed.
        """
        self._example_db = [
            ex for ex in self._example_db if ex["version"] <= version
        ]
        self._version = version

    def get_examples(
        self,
        query_class: str = "",
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Retrieve the best examples, optionally filtered by query class.

        Parameters
        ----------
        query_class:
            If non-empty, only return examples whose query contains this
            substring (case-insensitive).
        top_k:
            Maximum number of examples to return.

        Returns
        -------
        Up to *top_k* examples sorted by outcome (descending).
        """
        pool = self._example_db
        if query_class:
            lc = query_class.lower()
            pool = [ex for ex in pool if lc in ex["query"].lower()]

        # Sort by outcome descending, take top_k
        ranked = sorted(pool, key=lambda ex: ex["outcome"], reverse=True)
        return ranked[:top_k]

    @property
    def version(self) -> int:
        """Current version counter."""
        return self._version

    @property
    def example_db(self) -> List[Dict[str, Any]]:
        """Return a copy of the versioned example database."""
        return list(self._example_db)

    # -- Original property accessors ------------------------------------------

    @property
    def examples(self) -> List[Dict[str, Any]]:
        return list(self._examples)

    @property
    def skills(self) -> List[Dict[str, Any]]:
        return list(self._skills)


__all__ = ["ICLUpdaterPolicy"]
