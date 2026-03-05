"""Synthesize personal benchmarks from interaction traces."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List

from openjarvis.traces.store import TraceStore


@dataclass(slots=True)
class PersonalBenchmarkSample:
    """A single sample in a personal benchmark."""

    trace_id: str
    query: str
    reference_answer: str  # best known answer from traces
    agent: str = ""
    category: str = "chat"
    feedback_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PersonalBenchmark:
    """A synthesized benchmark from user interaction traces."""

    workflow_id: str
    samples: List[PersonalBenchmarkSample] = field(default_factory=list)
    created_at: float = 0.0


def _query_class_key(agent: str, query: str) -> str:
    """Compute a grouping key from agent name and query prefix."""
    prefix = query[:50].strip().lower()
    return f"{agent}::{prefix}"


def _infer_category(agent: str) -> str:
    """Heuristic to map an agent name to an eval category."""
    agent_lower = agent.lower()
    if any(tok in agent_lower for tok in ("react", "openhands", "orchestrator")):
        return "agentic"
    if any(tok in agent_lower for tok in ("rag", "memory", "retriev")):
        return "rag"
    if any(tok in agent_lower for tok in ("reason", "math", "code")):
        return "reasoning"
    return "chat"


class PersonalBenchmarkSynthesizer:
    """Mines interaction traces into a reusable personal benchmark."""

    def __init__(self, trace_store: TraceStore) -> None:
        self._store = trace_store

    def synthesize(
        self,
        workflow_id: str = "default",
        min_feedback: float = 0.7,
        max_samples: int = 100,
    ) -> PersonalBenchmark:
        """Build a personal benchmark from high-quality traces.

        1. Query traces that have feedback >= *min_feedback*.
        2. Group by query class (agent + first 50 chars of query).
        3. For each class, pick the trace with the highest feedback as reference.
        4. Return a :class:`PersonalBenchmark` capped at *max_samples*.
        """
        # Fetch a large pool of traces (limit high enough to cover most stores)
        all_traces = self._store.list_traces(limit=10_000)

        # Filter to traces with sufficient feedback
        qualified = [
            t
            for t in all_traces
            if t.feedback is not None and t.feedback >= min_feedback
        ]

        # Group by query class
        groups: Dict[str, list] = defaultdict(list)
        for trace in qualified:
            key = _query_class_key(trace.agent, trace.query)
            groups[key].append(trace)

        # Pick best trace per class
        samples: List[PersonalBenchmarkSample] = []
        for _key, traces in groups.items():
            best = max(traces, key=lambda t: t.feedback or 0.0)
            samples.append(
                PersonalBenchmarkSample(
                    trace_id=best.trace_id,
                    query=best.query,
                    reference_answer=best.result,
                    agent=best.agent,
                    category=_infer_category(best.agent),
                    feedback_score=best.feedback or 0.0,
                    metadata=best.metadata,
                ),
            )

        # Sort deterministically (highest feedback first) and cap
        samples.sort(key=lambda s: (-s.feedback_score, s.trace_id))
        samples = samples[:max_samples]

        return PersonalBenchmark(
            workflow_id=workflow_id,
            samples=samples,
            created_at=time.time(),
        )


__all__ = [
    "PersonalBenchmark",
    "PersonalBenchmarkSample",
    "PersonalBenchmarkSynthesizer",
]
