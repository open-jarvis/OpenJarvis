"""Trace system — full interaction-level recording and analysis.

The trace system captures the complete sequence of steps an agent takes to
handle a query.  Unlike telemetry (which records per-inference metrics), traces
record the *decision-making process*: which model was selected, what memory was
retrieved, which tools were called, and the final response.

Traces are the primary input to the learning system.
"""

from friday_ai.traces.analyzer import TraceAnalyzer
from friday_ai.traces.collector import TraceCollector
from friday_ai.traces.store import TraceStore

__all__ = ["TraceAnalyzer", "TraceCollector", "TraceStore"]
