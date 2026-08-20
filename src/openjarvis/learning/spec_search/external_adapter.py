"""Adapt external agent-dataset records into TraceStore rows.

LLM-guided spec search reads student traces from a SQLite TraceStore via
its search/get tools. This adapter reuses that pipeline for external
agent corpora (e.g. ADP, ToolOrchestra, GeneralThoughts): each EvalRecord
from a provider becomes a synthetic Trace so the teacher proposer can
reason over it without a live student run on the corpus task.

These synthetic traces carry feedback=0.5 by default (no ground truth).
Tool calls are empty. The `source_name` tag in each trace's metadata is
how multi-source corpora are filtered downstream.
"""

from __future__ import annotations

from collections.abc import Iterable

from openjarvis.core.types import Trace
from openjarvis.evals.core.types import EvalRecord
from openjarvis.traces.store import TraceStore


def write_external_records_as_traces(
    store: TraceStore,
    records: Iterable[EvalRecord],
    *,
    source_name: str,
    feedback_score: float = 0.5,
) -> int:
    """Write each EvalRecord to `store` as a synthetic Trace.

    The LLM-guided spec search proposer reads from the TraceStore via
    its search/get tools; this lets the diagnose phase substitute live
    student traces with records from pre-existing agent-task corpora
    (ADP / ToolOrchestra / GeneralThoughts).

    Args:
        store: Destination TraceStore.
        records: Iterable of EvalRecord (e.g. from a dataset provider).
        source_name: Label recorded in each trace's metadata["source"]
            so multi-source setups can filter later.
        feedback_score: Value for Trace.feedback (0..1). Defaults to 0.5
            because external records carry no ground-truth outcome.

    Returns:
        Number of traces written.
    """
    written = 0
    for rec in records:
        meta = {"source": source_name, "record_id": rec.record_id}
        if rec.metadata:
            meta.update(rec.metadata)
        trace = Trace(
            trace_id=f"ext-{source_name}-{rec.record_id}",
            query=rec.problem,
            agent="external",
            model="external",
            engine="external",
            steps=[],
            result=rec.reference or "",
            outcome=None,
            feedback=feedback_score,
            metadata=meta,
        )
        store.save(trace)
        written += 1
    return written


__all__ = ["write_external_records_as_traces"]
