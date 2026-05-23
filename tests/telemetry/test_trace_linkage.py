"""Tests that trace_id flows from TraceCollector → InstrumentedEngine → telemetry.

This is the linkage that makes Return on Cognitive Spend (RoCS) computable:
every telemetry row emitted while a trace is active carries the trace_id, so
later joins between feedback (TraceStore.feedback) and cost (TelemetryStore
energy/dollars) are exact rather than fuzzy.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role, TelemetryRecord
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
from openjarvis.telemetry.store import TelemetryStore
from openjarvis.traces.collector import TraceCollector
from openjarvis.traces.context import (
    get_current_trace_id,
    set_current_trace_id,
    reset_current_trace_id,
    trace_scope,
)


# ---------------------------------------------------------------------------
# trace_scope basics
# ---------------------------------------------------------------------------


class TestTraceContext:
    def test_default_is_empty_string(self):
        assert get_current_trace_id() == ""

    def test_set_and_reset(self):
        token = set_current_trace_id("abc123")
        assert get_current_trace_id() == "abc123"
        reset_current_trace_id(token)
        assert get_current_trace_id() == ""

    def test_scope_contextmanager(self):
        with trace_scope("xyz789"):
            assert get_current_trace_id() == "xyz789"
        assert get_current_trace_id() == ""

    def test_scope_resets_on_exception(self):
        with pytest.raises(RuntimeError):
            with trace_scope("err-trace"):
                assert get_current_trace_id() == "err-trace"
                raise RuntimeError("boom")
        assert get_current_trace_id() == ""

    def test_nested_scopes(self):
        with trace_scope("outer"):
            assert get_current_trace_id() == "outer"
            with trace_scope("inner"):
                assert get_current_trace_id() == "inner"
            assert get_current_trace_id() == "outer"
        assert get_current_trace_id() == ""


# ---------------------------------------------------------------------------
# InstrumentedEngine reads the ContextVar
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": "Hi back",
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    engine.list_models.return_value = ["test-model"]
    engine.health.return_value = True
    return engine


@pytest.fixture
def bus():
    return EventBus(record_history=True)


def _last_telemetry(bus: EventBus) -> TelemetryRecord:
    tel_events = [e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD]
    assert tel_events, "no TELEMETRY_RECORD events were published"
    return tel_events[-1].data["record"]


class TestInstrumentedEnginePropagation:
    def test_generate_without_scope_has_empty_trace_id(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        ie.generate([Message(role=Role.USER, content="Hi")], model="m")
        assert _last_telemetry(bus).trace_id == ""

    def test_generate_inside_scope_carries_trace_id(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        with trace_scope("scope-1"):
            ie.generate([Message(role=Role.USER, content="Hi")], model="m")
        assert _last_telemetry(bus).trace_id == "scope-1"

    def test_each_call_picks_up_current_scope(self, mock_engine, bus):
        ie = InstrumentedEngine(mock_engine, bus)
        msgs = [Message(role=Role.USER, content="Hi")]

        ie.generate(msgs, model="m")  # no scope
        with trace_scope("t-A"):
            ie.generate(msgs, model="m")
        with trace_scope("t-B"):
            ie.generate(msgs, model="m")
        ie.generate(msgs, model="m")  # back to no scope after exit

        tel_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        assert [e.data["record"].trace_id for e in tel_events] == [
            "",
            "t-A",
            "t-B",
            "",
        ]


# ---------------------------------------------------------------------------
# TelemetryStore round-trips trace_id
# ---------------------------------------------------------------------------


class TestTelemetryStoreTraceId:
    def test_store_persists_explicit_trace_id(self, tmp_path: Path):
        store = TelemetryStore(tmp_path / "tel.db")
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="m1",
            engine="e1",
            trace_id="trace-xyz",
        )
        store.record(rec)
        rows = store.list_recent(limit=1)
        assert rows[0]["trace_id"] == "trace-xyz"
        store.close()

    def test_store_persists_empty_trace_id_by_default(self, tmp_path: Path):
        store = TelemetryStore(tmp_path / "tel.db")
        rec = TelemetryRecord(timestamp=time.time(), model_id="m1", engine="e1")
        store.record(rec)
        rows = store.list_recent(limit=1)
        assert rows[0]["trace_id"] == ""
        store.close()

    def test_store_join_by_trace_id_returns_only_matching_rows(self, tmp_path: Path):
        store = TelemetryStore(tmp_path / "tel.db")
        for tid in ["t-A", "t-A", "t-B", ""]:
            store.record(
                TelemetryRecord(
                    timestamp=time.time(),
                    model_id="m",
                    engine="e",
                    completion_tokens=10,
                    energy_joules=1.0,
                    trace_id=tid,
                )
            )
        # Query for trace t-A — should see exactly 2 rows
        rows = store._select_dicts(
            "SELECT * FROM telemetry WHERE trace_id = ?", ("t-A",)
        )
        assert len(rows) == 2
        # Query for traces with any trace_id set — should see 3 (t-A x2, t-B)
        rows = store._select_dicts(
            "SELECT * FROM telemetry WHERE trace_id != ?", ("",)
        )
        assert len(rows) == 3
        store.close()


# ---------------------------------------------------------------------------
# End-to-end: TraceCollector wraps an agent; resulting telemetry carries
# the same trace_id as the persisted Trace.
# ---------------------------------------------------------------------------


class _PassthroughAgent(BaseAgent):
    """Tiny test agent that makes one engine.generate() call per run."""

    agent_id = "passthrough"
    accepts_tools = False

    def run(
        self,
        input: str,
        context: AgentContext | None = None,
        **kwargs,
    ) -> AgentResult:
        result = self._engine.generate(
            [Message(role=Role.USER, content=input)],
            model=self._model,
        )
        return AgentResult(content=result["content"], turns=1)


class TestEndToEndLinkage:
    def test_trace_id_in_telemetry_matches_trace_id_in_trace(
        self, mock_engine, bus, tmp_path: Path
    ):
        ie = InstrumentedEngine(mock_engine, bus)
        store = TelemetryStore(tmp_path / "tel.db")
        store.subscribe_to_bus(bus)

        agent = _PassthroughAgent(ie, "m", bus=bus)
        collector = TraceCollector(agent, store=None, bus=bus)
        collector.run("hello")

        # The trace that was just built
        trace = collector.last_trace
        assert trace is not None and trace.trace_id

        # The telemetry row persisted via the bus
        rows = store.list_recent(limit=1)
        assert rows[0]["trace_id"] == trace.trace_id, (
            f"trace_id mismatch: telemetry={rows[0]['trace_id']!r} "
            f"trace={trace.trace_id!r}"
        )
        store.close()

    def test_two_sequential_traces_get_distinct_ids(
        self, mock_engine, bus, tmp_path: Path
    ):
        ie = InstrumentedEngine(mock_engine, bus)
        store = TelemetryStore(tmp_path / "tel.db")
        store.subscribe_to_bus(bus)

        agent = _PassthroughAgent(ie, "m", bus=bus)
        collector = TraceCollector(agent, store=None, bus=bus)

        collector.run("first")
        trace_a = collector.last_trace.trace_id
        collector.run("second")
        trace_b = collector.last_trace.trace_id

        assert trace_a != trace_b

        rows = sorted(
            store._select_dicts("SELECT * FROM telemetry", ()),
            key=lambda r: r["timestamp"],
        )
        assert len(rows) == 2
        assert rows[0]["trace_id"] == trace_a
        assert rows[1]["trace_id"] == trace_b
        store.close()
