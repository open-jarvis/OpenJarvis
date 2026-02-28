# Experience Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the eval output, CLI, installation, and dashboard experiences clean, complete, and publication-ready across three independently shippable phases.

**Architecture:** Vertical slices — Phase 23a delivers a "perfect eval run" (grouped tables, IPJ/IPW, trace breakdown), Phase 23b delivers a "perfect first experience" (quickstart, logging, hints), Phase 23c polishes the desktop/browser dashboards.

**Tech Stack:** Python 3.10+, Rich (tables/panels), Click (CLI), Tauri 2.0 (desktop), React/Vite (PWA), SQLite (telemetry/traces), pytest (testing)

---

## Phase 23a: Perfect Eval Run

### Task 1: Add `tokens_per_joule` to TelemetryRecord

**Files:**
- Modify: `src/openjarvis/core/types.py:125-165`
- Test: `tests/telemetry/test_telemetry_record.py` (new)

**Step 1: Write the failing test**

Create `tests/telemetry/test_telemetry_record.py`:

```python
"""Tests for TelemetryRecord fields."""

from __future__ import annotations

from openjarvis.core.types import TelemetryRecord


class TestTelemetryRecord:
    def test_tokens_per_joule_field_exists(self):
        rec = TelemetryRecord(timestamp=1.0, model_id="test")
        assert hasattr(rec, "tokens_per_joule")
        assert rec.tokens_per_joule == 0.0

    def test_tokens_per_joule_set(self):
        rec = TelemetryRecord(
            timestamp=1.0,
            model_id="test",
            tokens_per_joule=80.0,
        )
        assert rec.tokens_per_joule == 80.0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/telemetry/test_telemetry_record.py -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'tokens_per_joule'`

**Step 3: Write minimal implementation**

In `src/openjarvis/core/types.py`, add after `dram_energy_joules` field (around line 163):

```python
    tokens_per_joule: float = 0.0
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/telemetry/test_telemetry_record.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/openjarvis/core/types.py tests/telemetry/test_telemetry_record.py
git commit -m "feat(telemetry): add tokens_per_joule field to TelemetryRecord"
```

---

### Task 2: Compute `tokens_per_joule` in InstrumentedEngine

**Files:**
- Modify: `src/openjarvis/telemetry/instrumented_engine.py:154-174`
- Test: `tests/telemetry/test_instrumented_engine.py` (existing — add test)

**Step 1: Write the failing test**

Add to `tests/telemetry/test_instrumented_engine.py`:

```python
class TestTokensPerJoule:
    def test_tokens_per_joule_computed(self, mock_engine, bus):
        """tokens_per_joule = completion_tokens / energy_joules."""
        mock_engine.generate.return_value = {
            "content": "hello",
            "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
        }
        inst = InstrumentedEngine(mock_engine, bus=bus)
        # Mock energy monitor to return known energy
        from unittest.mock import MagicMock, patch
        monitor = MagicMock()
        sample = MagicMock()
        sample.energy_joules = 2.5
        sample.mean_power_watts = 100.0
        sample.peak_power_watts = 120.0
        sample.gpu_utilization_pct = 50.0
        sample.gpu_memory_used_gb = 4.0
        sample.gpu_temperature_c = 60.0
        sample.cpu_energy_joules = 0.0
        sample.gpu_energy_joules = 2.5
        sample.dram_energy_joules = 0.0
        sample.energy_method = "test"
        sample.vendor = "test"
        monitor.sample.return_value.__enter__ = lambda s: sample
        monitor.sample.return_value.__exit__ = lambda s, *a: None
        inst._energy_monitor = monitor

        inst.generate(messages=[{"role": "user", "content": "hi"}])
        records = [
            e.data for e in bus.history
            if hasattr(e, 'event_type')
            and e.event_type.value == "telemetry_record"
        ]
        assert len(records) >= 1
        rec = records[0]
        # 50 tokens / 2.5 J = 20.0 tokens/joule
        assert rec.tokens_per_joule == pytest.approx(20.0, rel=0.1)

    def test_tokens_per_joule_zero_energy(self, mock_engine, bus):
        """tokens_per_joule is 0.0 when energy is zero."""
        mock_engine.generate.return_value = {
            "content": "hello",
            "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
        }
        inst = InstrumentedEngine(mock_engine, bus=bus)
        inst.generate(messages=[{"role": "user", "content": "hi"}])
        records = [
            e.data for e in bus.history
            if hasattr(e, 'event_type')
            and e.event_type.value == "telemetry_record"
        ]
        rec = records[0]
        assert rec.tokens_per_joule == 0.0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/telemetry/test_instrumented_engine.py::TestTokensPerJoule -v`
Expected: FAIL — `AttributeError: ... has no attribute 'tokens_per_joule'` on the record

**Step 3: Write minimal implementation**

In `src/openjarvis/telemetry/instrumented_engine.py`, in the `generate()` method, after the existing derived metrics block (around line 159, after `throughput_per_watt`), add:

```python
        # Tokens per joule (inverse of energy-per-token, per-inference efficiency)
        tokens_per_joule = 0.0
        if energy_j > 0 and completion_tokens > 0:
            tokens_per_joule = completion_tokens / energy_j
```

Then in the `TelemetryRecord(...)` constructor call (around line 178-204), add:

```python
            tokens_per_joule=tokens_per_joule,
```

Do the same in the `stream()` method (around line 369-400).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/telemetry/test_instrumented_engine.py::TestTokensPerJoule -v`
Expected: PASS (2 tests)

**Step 5: Run full telemetry tests**

Run: `uv run pytest tests/telemetry/ -v`
Expected: All pass (no regressions)

**Step 6: Commit**

```bash
git add src/openjarvis/telemetry/instrumented_engine.py tests/telemetry/test_instrumented_engine.py
git commit -m "feat(telemetry): compute tokens_per_joule in InstrumentedEngine"
```

---

### Task 3: Store and aggregate `tokens_per_joule`

**Files:**
- Modify: `src/openjarvis/telemetry/store.py:13-52` (schema)
- Modify: `src/openjarvis/telemetry/store.py:126-170` (record method)
- Modify: `src/openjarvis/telemetry/aggregator.py:11-33` (ModelStats)
- Modify: `src/openjarvis/telemetry/aggregator.py:36-56` (EngineStats)
- Modify: `src/openjarvis/telemetry/aggregator.py:115-198` (per_model_stats)
- Modify: `src/openjarvis/telemetry/aggregator.py:200-278` (per_engine_stats)
- Test: `tests/telemetry/test_store_tokens_per_joule.py` (new)

**Step 1: Write the failing test**

Create `tests/telemetry/test_store_tokens_per_joule.py`:

```python
"""Tests for tokens_per_joule storage and aggregation."""

from __future__ import annotations

import time

import pytest

from openjarvis.core.types import TelemetryRecord
from openjarvis.telemetry.store import TelemetryStore
from openjarvis.telemetry.aggregator import TelemetryAggregator


class TestTokensPerJouleStorage:
    def test_store_and_retrieve(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "tel.db")
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="test-model",
            completion_tokens=50,
            energy_joules=2.5,
            tokens_per_joule=20.0,
        )
        store.record(rec)
        agg = TelemetryAggregator(store)
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].avg_tokens_per_joule == pytest.approx(20.0, rel=0.1)
        store.close()

    def test_aggregate_multiple(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "tel.db")
        for tpj in [10.0, 20.0, 30.0]:
            rec = TelemetryRecord(
                timestamp=time.time(),
                model_id="m1",
                tokens_per_joule=tpj,
            )
            store.record(rec)
        agg = TelemetryAggregator(store)
        stats = agg.per_model_stats()
        assert stats[0].avg_tokens_per_joule == pytest.approx(20.0, rel=0.1)
        store.close()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/telemetry/test_store_tokens_per_joule.py -v`
Expected: FAIL — column or attribute not found

**Step 3: Write minimal implementation**

1. In `src/openjarvis/telemetry/store.py` schema list (lines 13-52), add `"tokens_per_joule"` to the columns list.

2. In `store.py` `record()` method, add `tokens_per_joule` to the INSERT statement and values tuple.

3. In `store.py` schema migration (`_maybe_add_columns` or equivalent), add migration for the new column.

4. In `src/openjarvis/telemetry/aggregator.py` `ModelStats`, add:
   ```python
   avg_tokens_per_joule: float = 0.0
   ```

5. In `EngineStats`, add the same field.

6. In `per_model_stats()` SQL query, add `AVG(tokens_per_joule)` using `_safe_col()`.

7. In `per_engine_stats()` SQL query, add same.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/telemetry/test_store_tokens_per_joule.py -v`
Expected: PASS (2 tests)

**Step 5: Run full telemetry test suite**

Run: `uv run pytest tests/telemetry/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add src/openjarvis/telemetry/store.py src/openjarvis/telemetry/aggregator.py tests/telemetry/test_store_tokens_per_joule.py
git commit -m "feat(telemetry): store and aggregate tokens_per_joule"
```

---

### Task 4: Add energy aggregation and step-type stats to TraceAnalyzer

**Files:**
- Modify: `src/openjarvis/traces/analyzer.py:39-49` (TraceSummary)
- Modify: `src/openjarvis/traces/analyzer.py:62-91` (summary method)
- Test: `tests/traces/test_analyzer_energy.py` (new)

**Step 1: Write the failing test**

Create `tests/traces/test_analyzer_energy.py`:

```python
"""Tests for energy aggregation in TraceAnalyzer."""

from __future__ import annotations

import time

import pytest

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.traces.analyzer import StepTypeStats, TraceAnalyzer, TraceSummary
from openjarvis.traces.store import TraceStore


def _make_trace(steps: list[TraceStep]) -> Trace:
    return Trace(
        query="test",
        agent="test_agent",
        model="test_model",
        engine="test_engine",
        steps=steps,
        started_at=time.time(),
        ended_at=time.time() + 10,
        total_tokens=100,
        total_latency_seconds=10.0,
    )


def _gen_step(energy: float = 0.0, duration: float = 1.0,
              prompt_tokens: int = 50, completion_tokens: int = 25) -> TraceStep:
    return TraceStep(
        step_type=StepType.GENERATE,
        timestamp=time.time(),
        duration_seconds=duration,
        output={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        metadata={
            "energy_joules": energy,
            "power_watts": energy / duration if duration > 0 else 0.0,
        },
    )


def _tool_step(duration: float = 0.5) -> TraceStep:
    return TraceStep(
        step_type=StepType.TOOL_CALL,
        timestamp=time.time(),
        duration_seconds=duration,
        input={"tool": "calculator"},
        output={"success": True},
    )


class TestTraceSummaryEnergyFields:
    def test_total_energy_joules(self, tmp_path):
        store = TraceStore(db_path=tmp_path / "traces.db")
        trace = _make_trace([
            _gen_step(energy=10.0, duration=2.0),
            _tool_step(duration=0.5),
            _gen_step(energy=15.0, duration=3.0),
        ])
        store.save(trace)
        analyzer = TraceAnalyzer(store)
        summary = analyzer.summary()
        assert summary.total_energy_joules == pytest.approx(25.0, rel=0.01)
        assert summary.total_generate_energy_joules == pytest.approx(25.0, rel=0.01)
        store.close()

    def test_step_type_stats(self, tmp_path):
        store = TraceStore(db_path=tmp_path / "traces.db")
        trace = _make_trace([
            _gen_step(energy=10.0, duration=2.0, prompt_tokens=100, completion_tokens=50),
            _gen_step(energy=20.0, duration=4.0, prompt_tokens=80, completion_tokens=40),
            _tool_step(duration=0.5),
            _tool_step(duration=1.5),
        ])
        store.save(trace)
        analyzer = TraceAnalyzer(store)
        summary = analyzer.summary()

        assert "generate" in summary.step_type_stats
        gen = summary.step_type_stats["generate"]
        assert gen.count == 2
        assert gen.avg_duration == pytest.approx(3.0, rel=0.01)
        assert gen.total_energy == pytest.approx(30.0, rel=0.01)
        assert gen.avg_input_tokens == pytest.approx(90.0, rel=0.01)
        assert gen.avg_output_tokens == pytest.approx(45.0, rel=0.01)
        assert gen.min_duration == pytest.approx(2.0, rel=0.01)
        assert gen.max_duration == pytest.approx(4.0, rel=0.01)

        assert "tool_call" in summary.step_type_stats
        tc = summary.step_type_stats["tool_call"]
        assert tc.count == 2
        assert tc.avg_duration == pytest.approx(1.0, rel=0.01)
        store.close()


class TestStepTypeStats:
    def test_dataclass_fields(self):
        s = StepTypeStats(count=5, avg_duration=2.0, total_energy=10.0)
        assert s.count == 5
        assert s.std_duration == 0.0  # default
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/traces/test_analyzer_energy.py -v`
Expected: FAIL — `ImportError: cannot import name 'StepTypeStats'`

**Step 3: Write minimal implementation**

In `src/openjarvis/traces/analyzer.py`:

1. Add new dataclass before `TraceSummary` (after line 37):

```python
@dataclass(slots=True)
class StepTypeStats:
    """Aggregated statistics for a specific step type across traces."""

    count: int = 0
    avg_duration: float = 0.0
    median_duration: float = 0.0
    min_duration: float = 0.0
    max_duration: float = 0.0
    std_duration: float = 0.0
    total_energy: float = 0.0
    avg_input_tokens: float = 0.0
    median_input_tokens: float = 0.0
    min_input_tokens: float = 0.0
    max_input_tokens: float = 0.0
    std_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    median_output_tokens: float = 0.0
    min_output_tokens: float = 0.0
    max_output_tokens: float = 0.0
    std_output_tokens: float = 0.0
```

2. Add fields to `TraceSummary`:

```python
    total_energy_joules: float = 0.0
    total_generate_energy_joules: float = 0.0
    step_type_stats: Dict[str, StepTypeStats] = field(default_factory=dict)
```

3. In the `summary()` method, after computing `step_dist`, add energy and step-type stats computation:

```python
        import statistics as stats_mod

        # Compute energy totals and step-type stats
        total_energy = 0.0
        generate_energy = 0.0
        step_data: Dict[str, Dict[str, list]] = {}

        for t in traces:
            for s in t.steps:
                key = _step_type_str(s)
                energy = s.metadata.get("energy_joules", 0.0)
                total_energy += energy
                if key == "generate":
                    generate_energy += energy

                if key not in step_data:
                    step_data[key] = {
                        "durations": [], "energies": [],
                        "input_tokens": [], "output_tokens": [],
                    }
                step_data[key]["durations"].append(s.duration_seconds)
                step_data[key]["energies"].append(energy)
                step_data[key]["input_tokens"].append(
                    s.output.get("prompt_tokens", 0)
                )
                step_data[key]["output_tokens"].append(
                    s.output.get("completion_tokens", 0)
                )

        sts_map: Dict[str, StepTypeStats] = {}
        for key, data in step_data.items():
            durations = data["durations"]
            in_tok = [float(x) for x in data["input_tokens"]]
            out_tok = [float(x) for x in data["output_tokens"]]
            sts_map[key] = StepTypeStats(
                count=len(durations),
                avg_duration=_avg(durations),
                median_duration=stats_mod.median(durations) if durations else 0.0,
                min_duration=min(durations) if durations else 0.0,
                max_duration=max(durations) if durations else 0.0,
                std_duration=stats_mod.stdev(durations) if len(durations) > 1 else 0.0,
                total_energy=sum(data["energies"]),
                avg_input_tokens=_avg(in_tok),
                median_input_tokens=stats_mod.median(in_tok) if in_tok else 0.0,
                min_input_tokens=min(in_tok) if in_tok else 0.0,
                max_input_tokens=max(in_tok) if in_tok else 0.0,
                std_input_tokens=stats_mod.stdev(in_tok) if len(in_tok) > 1 else 0.0,
                avg_output_tokens=_avg(out_tok),
                median_output_tokens=stats_mod.median(out_tok) if out_tok else 0.0,
                min_output_tokens=min(out_tok) if out_tok else 0.0,
                max_output_tokens=max(out_tok) if out_tok else 0.0,
                std_output_tokens=stats_mod.stdev(out_tok) if len(out_tok) > 1 else 0.0,
            )
```

Then add the new fields to the returned `TraceSummary`:

```python
            total_energy_joules=total_energy,
            total_generate_energy_joules=generate_energy,
            step_type_stats=sts_map,
```

4. Update `__all__` to include `StepTypeStats`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/traces/test_analyzer_energy.py -v`
Expected: PASS (3 tests)

**Step 5: Run full trace tests**

Run: `uv run pytest tests/traces/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add src/openjarvis/traces/analyzer.py tests/traces/test_analyzer_energy.py
git commit -m "feat(traces): add energy aggregation and step-type stats to TraceAnalyzer"
```

---

### Task 5: Add trace fields to eval types

**Files:**
- Modify: `evals/core/types.py:21-47` (EvalResult)
- Modify: `evals/core/types.py:87-125` (RunSummary)
- Test: `evals/tests/test_types.py` (existing — add tests)

**Step 1: Write the failing test**

Add to `evals/tests/test_types.py`:

```python
class TestEvalResultTraceFields:
    def test_trace_fields_exist(self):
        r = EvalResult(record_id="test", model_answer="hi")
        assert r.trace_steps == 0
        assert r.trace_energy_joules == 0.0

class TestRunSummaryTraceFields:
    def test_trace_aggregate_fields(self):
        s = RunSummary(
            benchmark="test", category="test", backend="test",
            model="test", total_samples=1, scored_samples=1,
            correct=1, accuracy=1.0, errors=0,
            mean_latency_seconds=1.0, total_cost_usd=0.0,
        )
        assert s.avg_power_watts == 0.0
        assert s.trace_step_type_stats == {}
        assert s.total_input_tokens == 0
        assert s.total_output_tokens == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest evals/tests/test_types.py::TestEvalResultTraceFields -v`
Expected: FAIL — `AttributeError`

**Step 3: Write minimal implementation**

In `evals/core/types.py`:

1. Add to `EvalResult` (after line 46, before the class ends):
```python
    trace_steps: int = 0
    trace_energy_joules: float = 0.0
```

2. Add to `RunSummary` (after line 124):
```python
    avg_power_watts: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    trace_step_type_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
```

**Step 4: Run tests**

Run: `uv run pytest evals/tests/test_types.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add evals/core/types.py evals/tests/test_types.py
git commit -m "feat(evals): add trace and power fields to EvalResult and RunSummary"
```

---

### Task 6: Wire trace data and strengthen token stats in eval runner

**Files:**
- Modify: `evals/core/runner.py:134-223` (_process_one)
- Modify: `evals/core/runner.py:267-380` (_compute_summary)
- Test: `evals/tests/test_runner.py` (existing — add tests)

**Step 1: Write the failing test**

Add to `evals/tests/test_runner.py`:

```python
class TestRunnerTokenStats:
    def test_summary_has_total_input_output_tokens(self, tmp_path):
        """RunSummary should include total token counts."""
        records = [
            EvalRecord(record_id=f"r{i}", problem=f"q{i}", reference="a", category="test")
            for i in range(3)
        ]
        backend = MockBackend()
        scorer = MockScorer()
        dataset = MockDataset(records=records)
        config = RunConfig(benchmark="test", backend="jarvis-direct", model="m")
        runner = EvalRunner(config=config, backend=backend, scorer=scorer, dataset=dataset)

        results, summary = runner.run(output_dir=tmp_path)
        # MockBackend returns usage with tokens — they should be tallied
        assert summary.total_input_tokens >= 0
        assert summary.total_output_tokens >= 0
        # input_token_stats and output_token_stats should be populated
        if summary.input_token_stats is not None:
            assert summary.input_token_stats.mean >= 0

    def test_summary_has_avg_power(self, tmp_path):
        """RunSummary should include avg_power_watts."""
        records = [
            EvalRecord(record_id="r1", problem="q", reference="a", category="test")
        ]
        config = RunConfig(benchmark="test", backend="jarvis-direct", model="m")
        runner = EvalRunner(
            config=config, backend=MockBackend(), scorer=MockScorer(),
            dataset=MockDataset(records=records),
        )
        results, summary = runner.run(output_dir=tmp_path)
        assert hasattr(summary, "avg_power_watts")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest evals/tests/test_runner.py::TestRunnerTokenStats -v`
Expected: FAIL — `total_input_tokens` not populated or missing

**Step 3: Write minimal implementation**

In `evals/core/runner.py` `_compute_summary()` method:

1. After collecting value lists (around line 343), add:
```python
        total_input_tokens = sum(r.prompt_tokens for r in scored)
        total_output_tokens = sum(r.completion_tokens for r in scored)
        power_values = [r.power_watts for r in scored if r.power_watts > 0]
        avg_power = _avg(power_values) if power_values else 0.0
```

2. In the `RunSummary(...)` constructor, add:
```python
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            avg_power_watts=avg_power,
```

3. For trace data wiring in `_process_one()`: After the agent/backend returns, check if trace data is available in `full.get("_trace")` and extract step count and energy. Add to the returned `EvalResult`:
```python
            trace_steps=trace_step_count,
            trace_energy_joules=trace_energy,
```

**Step 4: Run tests**

Run: `uv run pytest evals/tests/test_runner.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add evals/core/runner.py evals/tests/test_runner.py
git commit -m "feat(evals): wire trace data and token totals into RunSummary"
```

---

### Task 7: Rewrite eval display with grouped tables

This is the largest task in Phase 23a. The current `display.py` has one monolithic `print_metrics_table()`. We replace it with grouped panels.

**Files:**
- Modify: `evals/core/display.py` (major rewrite)
- Test: `evals/tests/test_display.py` (new)

**Step 1: Write the failing test**

Create `evals/tests/test_display.py`:

```python
"""Tests for eval display functions."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from evals.core.display import (
    print_accuracy_panel,
    print_energy_table,
    print_latency_table,
    print_trace_summary,
    print_compact_table,
    print_full_results,
)
from evals.core.types import MetricStats, RunSummary


def _make_summary(**overrides) -> RunSummary:
    defaults = dict(
        benchmark="gaia", category="agentic", backend="jarvis-agent",
        model="qwen3:8b", total_samples=100, scored_samples=100,
        correct=42, accuracy=0.42, errors=0,
        mean_latency_seconds=15.0, total_cost_usd=0.0,
        total_energy_joules=9300.0, avg_power_watts=880.0,
        total_input_tokens=50000, total_output_tokens=12000,
        per_subject={"level_1": {"accuracy": 0.58, "correct": 40, "scored": 68}},
    )
    defaults.update(overrides)
    return RunSummary(**defaults)


def _make_stats(mean=10.0) -> MetricStats:
    return MetricStats(
        mean=mean, median=mean * 0.9, min=mean * 0.2,
        max=mean * 3.0, std=mean * 0.5, p90=mean * 1.5,
        p95=mean * 2.0, p99=mean * 2.5,
    )


class TestAccuracyPanel:
    def test_renders_without_error(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary()
        print_accuracy_panel(console, summary)
        output = console.file.getvalue()
        assert "42.0%" in output or "0.42" in output

    def test_shows_per_subject(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary()
        print_accuracy_panel(console, summary)
        output = console.file.getvalue()
        assert "level_1" in output


class TestLatencyTable:
    def test_renders_with_stats(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            latency_stats=_make_stats(15.0),
            throughput_stats=_make_stats(40.0),
            input_token_stats=_make_stats(1024.0),
            output_token_stats=_make_stats(256.0),
        )
        print_latency_table(console, summary)
        output = console.file.getvalue()
        assert "Latency" in output
        assert "Avg" in output


class TestEnergyTable:
    def test_renders_ipj_ipw(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            energy_stats=_make_stats(46000.0),
            power_stats=_make_stats(880.0),
            ipw_stats=_make_stats(0.00048),
            ipj_stats=_make_stats(9.0e-6),
        )
        print_energy_table(console, summary)
        output = console.file.getvalue()
        assert "IPW" in output
        assert "IPJ" in output


class TestTraceSummary:
    def test_renders_step_type_breakdown(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            trace_step_type_stats={
                "generate": {
                    "count": 580, "avg_duration": 8.2,
                    "total_energy": 22000.0,
                    "avg_input_tokens": 890.0, "avg_output_tokens": 256.0,
                },
                "tool_call": {
                    "count": 420, "avg_duration": 3.1,
                    "total_energy": 0.0,
                    "avg_input_tokens": 0.0, "avg_output_tokens": 0.0,
                },
            },
        )
        print_trace_summary(console, summary)
        output = console.file.getvalue()
        assert "generate" in output
        assert "tool_call" in output


class TestCompactTable:
    def test_renders_all_metrics(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            latency_stats=_make_stats(15.0),
            energy_stats=_make_stats(46000.0),
        )
        print_compact_table(console, summary)
        output = console.file.getvalue()
        assert "Latency" in output
        assert "Energy" in output


class TestFullResults:
    def test_renders_all_sections(self):
        console = Console(file=StringIO(), force_terminal=True)
        summary = _make_summary(
            latency_stats=_make_stats(15.0),
            energy_stats=_make_stats(46000.0),
            power_stats=_make_stats(880.0),
        )
        print_full_results(console, summary)
        output = console.file.getvalue()
        assert "Accuracy" in output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest evals/tests/test_display.py -v`
Expected: FAIL — `ImportError: cannot import name 'print_accuracy_panel'`

**Step 3: Write the implementation**

Rewrite `evals/core/display.py`. Keep existing `print_banner`, `print_section`, `print_run_header`, `print_suite_summary`, `print_completion`. Replace `print_metrics_table` and add new functions:

```python
def print_accuracy_panel(console: Console, summary: RunSummary) -> None:
    """Print accuracy panel with per-subject breakdown."""
    lines = [
        f"[bold]Overall Accuracy    {summary.accuracy:.1%}[/bold]"
        f"  ({summary.correct}/{summary.scored_samples})",
    ]
    for subj, stats in sorted(summary.per_subject.items()):
        acc = stats.get("accuracy", 0.0)
        correct = int(stats.get("correct", 0))
        scored = int(stats.get("scored", 0))
        lines.append(f"  {subj:<20s} {acc:.1%}  ({correct}/{scored})")
    body = "\n".join(lines)
    panel = Panel(body, title="[bold]Accuracy[/bold]", border_style="green", expand=False)
    console.print(panel)


def _stats_table(title: str, rows: list[tuple[str, Optional[MetricStats], int]]) -> Table:
    """Build a stats table with Avg/Median/Min/Max/Std columns."""
    table = Table(
        title=f"[bold]{title}[/bold]",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Avg", justify="right")
    table.add_column("Median", justify="right")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Std", justify="right")
    for label, stats, decimals in rows:
        if stats is not None:
            _add_metric_row(table, label, stats, decimals)
    return table


def print_latency_table(console: Console, summary: RunSummary) -> None:
    """Print latency, throughput, and token stats table."""
    table = _stats_table("Latency & Throughput", [
        ("Latency (s)", summary.latency_stats, 2),
        ("TTFT (s)", summary.ttft_stats, 3),
        ("Throughput (tok/s)", summary.throughput_stats, 1),
        ("Avg Input Tokens", summary.input_token_stats, 1),
        ("Avg Output Tokens", summary.output_token_stats, 1),
    ])
    if table.row_count > 0:
        console.print(table)


def print_energy_table(console: Console, summary: RunSummary) -> None:
    """Print energy, efficiency, and IPJ/IPW table."""
    table = _stats_table("Energy & Efficiency", [
        ("Energy (J)", summary.energy_stats, 1),
        ("Power (W)", summary.power_stats, 1),
        ("GPU Util (%)", summary.gpu_utilization_stats, 1),
        ("Energy/OutTok (J)", summary.energy_per_output_token_stats, 6),
        ("Tokens/Joule", None, 1),  # placeholder — see note below
        ("MFU (%)", summary.mfu_stats, 3),
        ("MBU (%)", summary.mbu_stats, 3),
    ])
    if table.row_count > 0:
        console.print(table)
    # Headline: IPW, IPJ, Total Energy
    parts = []
    if summary.ipw_stats:
        parts.append(f"[bold]IPW (acc/W):[/bold] {summary.ipw_stats.mean:.6f}")
    if summary.ipj_stats:
        parts.append(f"[bold]IPJ (acc/J):[/bold] {summary.ipj_stats.mean:.2e}")
    if summary.total_energy_joules > 0:
        val = summary.total_energy_joules
        unit = "kJ" if val > 1000 else "J"
        display = val / 1000 if val > 1000 else val
        parts.append(f"[bold]Total Energy:[/bold] {display:.1f} {unit}")
    if summary.avg_power_watts > 0:
        parts.append(f"[bold]Avg Power:[/bold] {summary.avg_power_watts:.1f} W")
    if parts:
        console.print("  ".join(parts))


def print_trace_summary(console: Console, summary: RunSummary) -> None:
    """Print agentic trace step-type breakdown."""
    sts = summary.trace_step_type_stats
    if not sts:
        return
    total_steps = sum(s.get("count", 0) for s in sts.values())
    avg_per_sample = total_steps / summary.scored_samples if summary.scored_samples > 0 else 0

    table = Table(
        title="[bold]Agentic Trace Summary[/bold]",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        title_style="bold cyan",
        caption=f"Total Steps: {total_steps}  |  Avg Steps/Sample: {avg_per_sample:.1f}",
    )
    table.add_column("Step Type", style="cyan", no_wrap=True)
    table.add_column("Count", justify="right")
    table.add_column("Avg Duration", justify="right")
    table.add_column("Avg Energy (J)", justify="right")
    table.add_column("Avg In Tokens", justify="right")
    table.add_column("Avg Out Tokens", justify="right")

    for stype, data in sorted(sts.items()):
        count = data.get("count", 0)
        avg_dur = data.get("avg_duration", 0.0)
        total_e = data.get("total_energy", 0.0)
        avg_e = total_e / count if count > 0 else 0.0
        avg_in = data.get("avg_input_tokens", 0.0)
        avg_out = data.get("avg_output_tokens", 0.0)
        table.add_row(
            stype,
            str(count),
            f"{avg_dur:.2f}s",
            f"{avg_e:.1f}" if avg_e > 0 else "—",
            f"{avg_in:.0f}" if avg_in > 0 else "—",
            f"{avg_out:.0f}" if avg_out > 0 else "—",
        )
    console.print(table)


def print_compact_table(console: Console, summary: RunSummary) -> None:
    """Print a single dense metrics table (legacy behavior, enhanced)."""
    # This is the existing print_metrics_table with updated column headers
    print_metrics_table(console, summary)


def print_full_results(
    console: Console,
    summary: RunSummary,
    *,
    compact: bool = False,
    trace_detail: bool = False,
) -> None:
    """Orchestrate all result panels."""
    if compact:
        print_compact_table(console, summary)
        return
    print_accuracy_panel(console, summary)
    print_latency_table(console, summary)
    print_energy_table(console, summary)
    print_trace_summary(console, summary)
```

Update `__all__` to include all new functions.

**Step 4: Run tests**

Run: `uv run pytest evals/tests/test_display.py -v`
Expected: All pass

**Step 5: Run full eval test suite**

Run: `uv run pytest evals/tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add evals/core/display.py evals/tests/test_display.py
git commit -m "feat(evals): grouped display tables (accuracy, latency, energy, trace)"
```

---

### Task 8: Add `--compact` and `--trace-detail` flags to eval CLI

**Files:**
- Modify: `evals/cli.py:117-131` (_print_summary)
- Modify: `evals/cli.py:235-344` (run command flags)
- Test: `evals/tests/test_cli_flags.py` (new)

**Step 1: Write the failing test**

Create `evals/tests/test_cli_flags.py`:

```python
"""Tests for eval CLI display flags."""

from __future__ import annotations

from click.testing import CliRunner

from evals.cli import cli


class TestCompactFlag:
    def test_compact_flag_accepted(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert "--compact" in result.output

    def test_trace_detail_flag_accepted(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert "--trace-detail" in result.output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest evals/tests/test_cli_flags.py -v`
Expected: FAIL — `--compact` not in help output

**Step 3: Write minimal implementation**

In `evals/cli.py`:

1. Add flags to `run` command (around line 270):
```python
@click.option("--compact", is_flag=True, default=False, help="Dense single-table output")
@click.option("--trace-detail", is_flag=True, default=False, help="Full per-step trace listing")
```

2. Pass flags through to `_print_summary()`:
```python
def _print_summary(console, summary, per_subject, output_path, traces_dir,
                   *, compact=False, trace_detail=False):
```

3. In `_print_summary`, replace the `print_metrics_table` call with:
```python
    print_full_results(console, summary, compact=compact, trace_detail=trace_detail)
```

4. Update imports to include new display functions.

**Step 4: Run tests**

Run: `uv run pytest evals/tests/test_cli_flags.py -v`
Expected: PASS

**Step 5: Run full eval test suite**

Run: `uv run pytest evals/tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add evals/cli.py evals/tests/test_cli_flags.py
git commit -m "feat(evals): add --compact and --trace-detail CLI flags"
```

---

## Phase 23b: Perfect First Experience

### Task 9: `jarvis quickstart` command

**Files:**
- Create: `src/openjarvis/cli/quickstart_cmd.py`
- Modify: `src/openjarvis/cli/__init__.py:34-54` (register command)
- Test: `tests/cli/test_quickstart.py` (new)

**Implementation outline:**
- 5-step flow: detect hardware → write config → check engine → verify model → test query
- Each step prints `[N/5] Description...` with Rich status
- Reuse `detect_hardware()` from `init_cmd.py`
- Reuse `_run_all_checks()` logic from `doctor_cmd.py`
- Skip steps already done (config exists → skip step 2)
- `--force` flag to redo everything
- On failure: print helpful suggestion and exit with code 1

**Test approach:**
- Use `CliRunner` with monkeypatched `detect_hardware`, `load_config`, engine checks
- Verify exit code 0 on happy path
- Verify helpful message when engine not found
- Verify `--force` regenerates config

**Step 1:** Write failing tests for happy path + error paths
**Step 2:** Run tests to verify they fail
**Step 3:** Implement `quickstart_cmd.py` and register in `__init__.py`
**Step 4:** Run tests to verify they pass
**Step 5:** Commit: `"feat(cli): add jarvis quickstart command"`

---

### Task 10: Error message auto-suggestions

**Files:**
- Create: `src/openjarvis/cli/hints.py`
- Modify: `src/openjarvis/cli/ask.py:215-224,258-259,269-271`
- Modify: `src/openjarvis/cli/serve.py` (startup errors)
- Modify: `src/openjarvis/cli/bench_cmd.py` (engine errors)
- Modify: `src/openjarvis/cli/chat_cmd.py` (startup errors)
- Test: `tests/cli/test_hints.py` (new)

**Implementation outline:**
- `hints.py` provides `hint_no_config()`, `hint_no_engine()`, `hint_no_model()` functions
- Each returns a Rich-formatted suggestion string
- Wire into existing error handlers in ask, serve, bench, chat commands
- Pattern: catch error → print original message → print hint → exit

**Test approach:**
- Unit test each hint function returns non-empty string
- CLI integration tests verify hints appear in error output

**Step 1:** Write failing tests
**Step 2:** Implement `hints.py` and wire into CLI commands
**Step 3:** Run tests, commit: `"feat(cli): add error hints system"`

---

### Task 11: Global logging and verbose/quiet flags

**Files:**
- Create: `src/openjarvis/cli/log_config.py`
- Modify: `src/openjarvis/cli/__init__.py:28-31` (add flags to root group)
- Test: `tests/cli/test_log_config.py` (new)

**Implementation outline:**
- Add `--verbose` / `--quiet` flags to root `cli` group via `click.pass_context`
- `log_config.py`: `setup_logging(verbose, quiet)` configures:
  - `RichHandler` for console (WARNING default, DEBUG on verbose, ERROR on quiet)
  - `RotatingFileHandler` for `~/.openjarvis/cli.log` (5 MB, 3 backups)
- Call `setup_logging()` in root `cli` group callback

**Test approach:**
- Verify `--verbose` sets DEBUG level
- Verify `--quiet` sets ERROR level
- Verify log file created on verbose mode

**Step 1-5:** TDD cycle, commit: `"feat(cli): add global verbose/quiet logging flags"`

---

### Task 12: Progress indicators for slow operations

**Files:**
- Modify: `src/openjarvis/cli/ask.py:320-330` (generation)
- Modify: `src/openjarvis/cli/memory_cmd.py:77-96` (indexing)
- Test: Visual verification only (progress spinners are UI-only)

**Implementation outline:**
- Wrap generation call in `ask.py` with `console.status("[bold green]Generating..."):` context
- Wrap indexing loop in `memory_cmd.py` with `rich.progress.Progress` bar
- Use `track()` for known-length operations, `status()` for unknown-length

**Commit:** `"feat(cli): add progress indicators for generation and indexing"`

---

### Task 13: Bench CLI full stats tables

**Files:**
- Modify: `src/openjarvis/cli/bench_cmd.py:175-209`
- Modify: `src/openjarvis/bench/latency.py:60-87` (return full stats)
- Modify: `src/openjarvis/bench/throughput.py:50-74` (add stats)
- Modify: `src/openjarvis/bench/energy.py:85-123` (add stats)
- Test: `tests/bench/test_bench_stats.py` (new)

**Implementation outline:**
- Each benchmark returns a `metrics` dict. Currently flat key-value pairs.
- Change to include `_stats` suffixed keys for metrics that have multiple samples:
  - latency: `latency_avg`, `latency_median`, `latency_min`, `latency_max`, `latency_std`, `latency_p95`
  - throughput: same pattern
  - energy: same pattern
- `bench_cmd.py` detects stats keys and renders a Rich stats table (Avg/Median/Min/Max/Std columns)
- Non-stats metrics (single values like `total_energy`, `errors`) shown as before

**Test approach:**
- Verify benchmark `run()` returns stats-suffixed keys
- Verify CLI renders table with correct columns

**Step 1-5:** TDD cycle, commit: `"feat(bench): full stats tables in bench CLI"`

---

## Phase 23c: Perfect Dashboard

### Task 14: Desktop settings panel

**Files:**
- Create: `desktop/src/components/SettingsPanel.tsx`
- Modify: `desktop/src/App.tsx` (add settings tab)

**Implementation:** React component with API URL input, auto-update interval selector, dark/light theme toggle. Persists to `localStorage`. Clean minimalist UI matching ChatGPT/Claude aesthetic.

---

### Task 15: Desktop Windows icon

**Files:**
- Replace: `desktop/src-tauri/icons/icon.ico`

**Implementation:** Generate proper multi-resolution `.ico` from existing `icon.png` (16, 32, 48, 256px).

---

### Task 16: Desktop system tray

**Files:**
- Modify: `desktop/src-tauri/src/lib.rs:189-191`

**Implementation:** Add tray menu items: Show/Hide, Health Status, Quit. Use Tauri's `SystemTray` API.

---

### Task 17: PWA CI/CD and error boundary

**Files:**
- Create: `.github/workflows/frontend.yml`
- Modify: `frontend/src/App.tsx` (error boundary wrapper)
- Modify: `frontend/vite.config.ts` (VITE_API_URL env var)

**Implementation:** GitHub Actions workflow triggers on `frontend/` changes, builds with `npm run build`, commits to `src/openjarvis/server/static/`. Error boundary wraps `<App />`.

---

### Task 18: PWA style refresh

**Files:**
- Modify: `frontend/src/App.css` (modularize)
- Create: `frontend/src/components/Chat/Chat.css` (component-scoped)
- Create: `frontend/src/components/Sidebar/Sidebar.css` (component-scoped)

**Implementation:** Break 12,971-line `App.css` into component-scoped CSS modules. Clean minimalist aesthetic inspired by ChatGPT/Claude web interfaces. Keep Catppuccin dark theme as default, add light theme option. Generous whitespace, muted color palette, smooth transitions. Side panels (energy, traces, learning, memory) remain the differentiator — collapsible with clean data density.

---

## Summary

| Phase | Tasks | Commits | Priority |
|-------|-------|---------|----------|
| 23a: Perfect Eval Run | 1-8 | 8 | Highest — enables GAIA research |
| 23b: Perfect First Experience | 9-13 | 5 | High — onboarding & CLI |
| 23c: Perfect Dashboard | 14-18 | 5 | Lower — demo polish |

**Total: 18 tasks, ~18 commits**

Start with Phase 23a Task 1. Each task is independently testable and committable.
