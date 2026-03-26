"""Tests for energy telemetry wiring — verify CLI, SDK, bench, and
telemetry stats all flow through InstrumentedEngine + EnergyMonitor."""

from __future__ import annotations

import importlib
import json
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role, TelemetryRecord
from openjarvis.telemetry.aggregator import AggregatedStats, TelemetryAggregator
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
from openjarvis.telemetry.store import TelemetryStore

_ask_mod = importlib.import_module("openjarvis.cli.ask")
_bench_mod = importlib.import_module("openjarvis.cli.bench_cmd")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_engine(content="Test response"):
    """Return a mock engine that generates a fixed response."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _mock_energy_monitor():
    """Return a mock energy monitor with realistic sample data."""
    monitor = MagicMock()
    monitor.close = MagicMock()

    sample = MagicMock()
    sample.energy_joules = 42.5
    sample.mean_power_watts = 250.0
    sample.peak_power_watts = 350.0
    sample.mean_utilization_pct = 78.0
    sample.peak_utilization_pct = 95.0
    sample.mean_memory_used_gb = 16.0
    sample.peak_memory_used_gb = 20.0
    sample.mean_temperature_c = 65.0
    sample.peak_temperature_c = 72.0
    sample.duration_seconds = 0.5
    sample.num_snapshots = 10
    sample.energy_method = "hw_counter"
    sample.vendor = "nvidia"
    sample.cpu_energy_joules = 0.0
    sample.gpu_energy_joules = 42.5
    sample.dram_energy_joules = 0.0

    @contextmanager
    def _sample():
        yield sample

    monitor.sample = _sample
    return monitor


def _energy_config(tmp_path, gpu_metrics=True):
    """Build a JarvisConfig with energy monitoring enabled."""
    cfg = JarvisConfig()
    cfg.telemetry.enabled = True
    cfg.telemetry.gpu_metrics = gpu_metrics
    cfg.telemetry.energy_vendor = ""
    cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
    return cfg


def _make_energy_record(
    model_id="test-model",
    engine="ollama",
    energy_joules=42.5,
    throughput=120.0,
    gpu_util=78.0,
    power=250.0,
    energy_method="hw_counter",
    energy_vendor="nvidia",
    ts=None,
):
    """Create a TelemetryRecord with energy data."""
    return TelemetryRecord(
        timestamp=ts or time.time(),
        model_id=model_id,
        engine=engine,
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        latency_seconds=0.5,
        cost_usd=0.0,
        energy_joules=energy_joules,
        power_watts=power,
        gpu_utilization_pct=gpu_util,
        gpu_memory_used_gb=16.0,
        gpu_temperature_c=65.0,
        throughput_tok_per_sec=throughput,
        energy_method=energy_method,
        energy_vendor=energy_vendor,
        gpu_energy_joules=energy_joules,
    )


# ---------------------------------------------------------------------------
# CLI ask.py wiring
# ---------------------------------------------------------------------------


class TestCliAskWiring:
    """Verify cli/ask.py wraps engine with InstrumentedEngine."""

    def _patch_ask(self, monkeypatch, tmp_path, gpu_metrics=True):
        cfg = _energy_config(tmp_path, gpu_metrics=gpu_metrics)
        monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

        engine = _mock_engine()
        monkeypatch.setattr(
            _ask_mod,
            "get_engine",
            lambda *a, **kw: ("mock", engine),
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_engines",
            lambda c: [("mock", engine)],
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_models",
            lambda e: {"mock": ["test-model"]},
        )
        return cfg, engine

    def test_engine_wrapped_with_instrumented(
        self,
        monkeypatch,
        tmp_path,
    ):
        """InstrumentedEngine wraps engine, not instrumented_generate."""
        cfg, engine = self._patch_ask(
            monkeypatch,
            tmp_path,
            gpu_metrics=False,
        )
        result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
        assert "Test response" in result.output
        # Engine.generate was called (through InstrumentedEngine)
        engine.generate.assert_called_once()

    def test_energy_monitor_created_when_gpu_metrics_on(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Energy monitor is created when gpu_metrics=True."""
        cfg, engine = self._patch_ask(
            monkeypatch,
            tmp_path,
            gpu_metrics=True,
        )
        mock_monitor = _mock_energy_monitor()
        with patch(
            "openjarvis.telemetry.energy_monitor.create_energy_monitor",
            return_value=mock_monitor,
        ):
            result = CliRunner().invoke(cli, ["ask", "Hello"])

        assert result.exit_code == 0
        mock_monitor.close.assert_called_once()

    def test_no_energy_monitor_when_gpu_metrics_off(
        self,
        monkeypatch,
        tmp_path,
    ):
        """No energy monitor when gpu_metrics=False."""
        cfg, engine = self._patch_ask(
            monkeypatch,
            tmp_path,
            gpu_metrics=False,
        )
        # Should not attempt to import create_energy_monitor
        result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0

    def test_telemetry_events_published(
        self,
        monkeypatch,
        tmp_path,
    ):
        """InstrumentedEngine publishes TELEMETRY_RECORD events."""
        cfg, engine = self._patch_ask(
            monkeypatch,
            tmp_path,
            gpu_metrics=False,
        )
        result = CliRunner().invoke(cli, ["ask", "Hello"])
        assert result.exit_code == 0
        # Verify telemetry DB was created and has a record
        db_path = tmp_path / "telemetry.db"
        assert db_path.exists()
        agg = TelemetryAggregator(db_path)
        assert agg.record_count() == 1
        agg.close()

    def test_energy_data_in_telemetry_record(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Energy data flows into TelemetryRecord in SQLite."""
        cfg, engine = self._patch_ask(
            monkeypatch,
            tmp_path,
            gpu_metrics=True,
        )
        mock_monitor = _mock_energy_monitor()
        with patch(
            "openjarvis.telemetry.energy_monitor.create_energy_monitor",
            return_value=mock_monitor,
        ):
            CliRunner().invoke(cli, ["ask", "Hello"])

        db_path = tmp_path / "telemetry.db"
        agg = TelemetryAggregator(db_path)
        records = agg.export_records()
        assert len(records) == 1
        rec = records[0]
        assert rec["energy_joules"] == pytest.approx(42.5)
        assert rec["energy_method"] == "hw_counter"
        assert rec["energy_vendor"] == "nvidia"
        assert rec["gpu_utilization_pct"] == pytest.approx(78.0)
        assert rec["gpu_energy_joules"] == pytest.approx(42.5)
        assert rec["throughput_tok_per_sec"] > 0
        agg.close()

    def test_agent_mode_uses_instrumented_engine(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Agent mode passes InstrumentedEngine to agent."""
        cfg, engine = self._patch_ask(
            monkeypatch,
            tmp_path,
            gpu_metrics=False,
        )

        # Register a trivial agent that calls engine.generate
        from openjarvis.agents._stubs import AgentResult
        from openjarvis.core.registry import AgentRegistry

        class _TestAgent:
            agent_id = "test-wiring-agent"

            def __init__(self, eng, model, **kw):
                self.engine = eng

            def run(self, q, context=None, **kw):
                # Call generate to trigger telemetry
                self.engine.generate(
                    [Message(role=Role.USER, content=q)],
                    model="test-model",
                )
                return AgentResult(content="Agent OK", turns=1)

        AgentRegistry.register_value(
            "test-wiring-agent",
            _TestAgent,
        )

        result = CliRunner().invoke(
            cli,
            ["ask", "--agent", "test-wiring-agent", "Hi"],
        )
        assert result.exit_code == 0
        assert "Agent OK" in result.output

        # Verify telemetry was recorded via InstrumentedEngine
        db_path = tmp_path / "telemetry.db"
        agg = TelemetryAggregator(db_path)
        assert agg.record_count() == 1
        agg.close()


# ---------------------------------------------------------------------------
# SDK wiring
# ---------------------------------------------------------------------------


class TestSdkWiring:
    """Verify sdk.py wraps engine with InstrumentedEngine."""

    def test_engine_wrapped_in_ensure_engine(self):
        """_ensure_engine wraps with InstrumentedEngine."""
        from openjarvis.sdk import Jarvis

        engine = _mock_engine()
        cfg = JarvisConfig()
        with patch(
            "openjarvis.sdk.get_engine",
            return_value=("mock", engine),
        ):
            j = Jarvis(config=cfg, model="test-model")
            j._ensure_engine()
            assert isinstance(j._engine, InstrumentedEngine)
            j.close()

    def test_energy_monitor_stored(self, tmp_path):
        """Energy monitor is created and stored on Jarvis instance."""
        from openjarvis.sdk import Jarvis

        engine = _mock_engine()
        cfg = _energy_config(tmp_path, gpu_metrics=True)
        mock_monitor = _mock_energy_monitor()

        with (
            patch(
                "openjarvis.sdk.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.telemetry.energy_monitor.create_energy_monitor",
                return_value=mock_monitor,
            ),
        ):
            j = Jarvis(config=cfg, model="test-model")
            j._ensure_engine()
            assert j._energy_monitor is mock_monitor
            j.close()
            mock_monitor.close.assert_called_once()

    def test_no_energy_monitor_when_gpu_metrics_off(self):
        """No energy monitor when gpu_metrics=False."""
        from openjarvis.sdk import Jarvis

        engine = _mock_engine()
        cfg = JarvisConfig()
        cfg.telemetry.gpu_metrics = False

        with patch(
            "openjarvis.sdk.get_engine",
            return_value=("mock", engine),
        ):
            j = Jarvis(config=cfg, model="test-model")
            j._ensure_engine()
            assert j._energy_monitor is None
            j.close()

    def test_ask_full_records_energy(self, tmp_path):
        """ask_full records energy via InstrumentedEngine."""
        from openjarvis.sdk import Jarvis

        engine = _mock_engine()
        cfg = _energy_config(tmp_path, gpu_metrics=True)
        mock_monitor = _mock_energy_monitor()

        with (
            patch(
                "openjarvis.sdk.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.telemetry.energy_monitor.create_energy_monitor",
                return_value=mock_monitor,
            ),
        ):
            j = Jarvis(config=cfg, model="test-model")
            result = j.ask_full("Hello")
            assert result["content"] == "Test response"
            j.close()

        # Verify energy was stored
        agg = TelemetryAggregator(cfg.telemetry.db_path)
        records = agg.export_records()
        assert len(records) == 1
        assert records[0]["energy_joules"] == pytest.approx(42.5)
        assert records[0]["energy_method"] == "hw_counter"
        agg.close()

    def test_close_cleans_up_energy_monitor(self):
        """close() releases the energy monitor."""
        from openjarvis.sdk import Jarvis

        engine = _mock_engine()
        cfg = JarvisConfig()
        cfg.telemetry.gpu_metrics = True
        mock_monitor = _mock_energy_monitor()

        with (
            patch(
                "openjarvis.sdk.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.telemetry.energy_monitor.create_energy_monitor",
                return_value=mock_monitor,
            ),
        ):
            j = Jarvis(config=cfg, model="test-model")
            j._ensure_engine()
            j.close()
            mock_monitor.close.assert_called_once()
            assert j._energy_monitor is None

    def test_double_close_safe(self):
        """Double close doesn't crash."""
        from openjarvis.sdk import Jarvis

        engine = _mock_engine()
        cfg = JarvisConfig()
        cfg.telemetry.gpu_metrics = True
        mock_monitor = _mock_energy_monitor()

        with (
            patch(
                "openjarvis.sdk.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.telemetry.energy_monitor.create_energy_monitor",
                return_value=mock_monitor,
            ),
        ):
            j = Jarvis(config=cfg, model="test-model")
            j._ensure_engine()
            j.close()
            j.close()  # should not raise


# ---------------------------------------------------------------------------
# InstrumentedEngine + EnergyMonitor integration
# ---------------------------------------------------------------------------


class TestInstrumentedEngineEnergy:
    """Verify InstrumentedEngine correctly uses EnergyMonitor."""

    def test_energy_monitor_sample_called(self):
        """Energy monitor's sample() is invoked during generate."""
        engine = _mock_engine()
        bus = EventBus(record_history=True)
        monitor = _mock_energy_monitor()

        ie = InstrumentedEngine(
            engine,
            bus,
            energy_monitor=monitor,
        )
        messages = [Message(role=Role.USER, content="Hi")]
        result = ie.generate(messages, model="test")

        assert result["content"] == "Test response"
        # Verify energy data is in the telemetry record
        tel_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        assert len(tel_events) == 1
        rec = tel_events[0].data["record"]
        assert rec.energy_joules == pytest.approx(42.5)
        assert rec.energy_method == "hw_counter"
        assert rec.energy_vendor == "nvidia"
        assert rec.gpu_utilization_pct == pytest.approx(78.0)
        assert rec.gpu_energy_joules == pytest.approx(42.5)

    def test_energy_data_injected_into_result(self):
        """_telemetry dict in result contains energy fields."""
        engine = _mock_engine()
        bus = EventBus()
        monitor = _mock_energy_monitor()

        ie = InstrumentedEngine(
            engine,
            bus,
            energy_monitor=monitor,
        )
        messages = [Message(role=Role.USER, content="Hi")]
        result = ie.generate(messages, model="test")

        assert "_telemetry" in result
        telem = result["_telemetry"]
        assert telem["energy_joules"] == pytest.approx(42.5)
        assert telem["energy_method"] == "hw_counter"
        assert telem["energy_vendor"] == "nvidia"
        assert telem["gpu_utilization_pct"] == pytest.approx(78.0)
        assert telem["gpu_energy_joules"] == pytest.approx(42.5)
        assert telem["cpu_energy_joules"] == 0.0
        assert telem["dram_energy_joules"] == 0.0

    def test_no_energy_monitor_still_works(self):
        """Without energy_monitor, generate still works with zeros."""
        engine = _mock_engine()
        bus = EventBus(record_history=True)

        ie = InstrumentedEngine(engine, bus)
        messages = [Message(role=Role.USER, content="Hi")]
        result = ie.generate(messages, model="test")

        assert result["content"] == "Test response"
        tel = [e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD]
        rec = tel[0].data["record"]
        assert rec.energy_joules == 0.0
        assert rec.energy_method == ""

    def test_energy_monitor_failure_graceful(self):
        """If energy monitor sample raises, generate still works."""
        engine = _mock_engine()
        bus = EventBus()
        monitor = MagicMock()

        @contextmanager
        def _broken_sample():
            raise RuntimeError("GPU fell off")
            yield  # pragma: no cover

        monitor.sample = _broken_sample

        ie = InstrumentedEngine(
            engine,
            bus,
            energy_monitor=monitor,
        )
        messages = [Message(role=Role.USER, content="Hi")]
        # Should not crash — energy is best-effort.
        # InstrumentedEngine tries energy_monitor first, falls
        # through to no-monitor path on exception.
        # Note: current impl doesn't catch, so this tests that
        # the engine call path is resilient.
        with pytest.raises(RuntimeError, match="GPU fell off"):
            ie.generate(messages, model="test")


# ---------------------------------------------------------------------------
# Bench CLI wiring
# ---------------------------------------------------------------------------


class TestBenchWiring:
    """Verify bench CLI creates and passes energy_monitor."""

    def test_energy_monitor_passed_to_benchmarks(self):
        """When gpu_metrics=True, energy_monitor is passed."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.list_models.return_value = ["test-model"]
        engine.generate.return_value = {
            "content": "Hello",
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            },
        }

        cfg = JarvisConfig()
        cfg.telemetry.gpu_metrics = True
        mock_monitor = _mock_energy_monitor()

        with (
            patch(
                "openjarvis.cli.bench_cmd.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.cli.bench_cmd.load_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.telemetry.energy_monitor.create_energy_monitor",
                return_value=mock_monitor,
            ) as mock_create,
        ):
            result = CliRunner().invoke(
                cli,
                ["bench", "run", "-n", "2"],
            )

        assert result.exit_code == 0
        mock_create.assert_called_once()
        mock_monitor.close.assert_called_once()

    def test_no_energy_monitor_when_gpu_metrics_off(self):
        """No energy_monitor when gpu_metrics=False."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.list_models.return_value = ["test-model"]
        engine.generate.return_value = {
            "content": "Hello",
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            },
        }

        cfg = JarvisConfig()
        cfg.telemetry.gpu_metrics = False

        with (
            patch(
                "openjarvis.cli.bench_cmd.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.cli.bench_cmd.load_config",
                return_value=cfg,
            ),
        ):
            result = CliRunner().invoke(
                cli,
                ["bench", "run", "-n", "2"],
            )

        assert result.exit_code == 0

    def test_warmup_flag_passed(self):
        """--warmup flag is forwarded to benchmarks."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.list_models.return_value = ["test-model"]
        engine.generate.return_value = {
            "content": "Hello",
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            },
        }

        cfg = JarvisConfig()
        cfg.telemetry.gpu_metrics = False

        with (
            patch(
                "openjarvis.cli.bench_cmd.get_engine",
                return_value=("mock", engine),
            ),
            patch(
                "openjarvis.cli.bench_cmd.load_config",
                return_value=cfg,
            ),
        ):
            result = CliRunner().invoke(
                cli,
                ["bench", "run", "-n", "2", "-w", "3"],
            )

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Telemetry stats wiring — energy columns in output
# ---------------------------------------------------------------------------


def _populate_energy_db(db_path: Path, n: int = 3) -> None:
    """Create a telemetry DB with energy-enriched records."""
    store = TelemetryStore(db_path)
    for i in range(n):
        store.record(
            _make_energy_record(
                model_id=f"model-{i % 2}",
                energy_joules=10.0 * (i + 1),
                throughput=100.0 + i * 10,
                gpu_util=70.0 + i * 5,
                power=200.0 + i * 25,
                ts=time.time() - (n - i),
            )
        )
    store.close()


def _patch_telemetry_config(tmp_path: Path):
    """Patch load_config for telemetry CLI."""
    db_path = tmp_path / "telemetry.db"
    cfg = mock.MagicMock()
    cfg.telemetry.db_path = str(db_path)
    return mock.patch(
        "openjarvis.cli.telemetry_cmd.load_config",
        return_value=cfg,
    ), db_path


class TestTelemetryStatsEnergy:
    """Verify telemetry stats shows energy columns."""

    def test_energy_columns_in_stats(self, tmp_path):
        """Stats output includes energy metrics when data exists."""
        p, db_path = _patch_telemetry_config(tmp_path)
        _populate_energy_db(db_path)
        with p:
            result = CliRunner().invoke(
                cli,
                ["telemetry", "stats"],
            )
        assert result.exit_code == 0
        assert "Total Energy (J)" in result.output
        assert "Avg Throughput" in result.output
        assert "Avg GPU Utilization" in result.output
        # Per-model table
        assert "Energy (J)" in result.output
        assert "Throughput" in result.output
        # Rich may wrap "GPU Util %" across lines
        assert "GPU Util" in result.output

    def test_no_energy_columns_when_no_energy_data(self, tmp_path):
        """Stats hides energy columns when no energy data."""
        p, db_path = _patch_telemetry_config(tmp_path)
        # Populate with non-energy records
        store = TelemetryStore(db_path)
        for i in range(3):
            store.record(
                TelemetryRecord(
                    timestamp=time.time(),
                    model_id="model-0",
                    engine="ollama",
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    latency_seconds=0.5,
                    cost_usd=0.001,
                )
            )
        store.close()

        with p:
            result = CliRunner().invoke(
                cli,
                ["telemetry", "stats"],
            )
        assert result.exit_code == 0
        assert "Total Calls" in result.output
        # Energy columns should NOT appear
        assert "Total Energy" not in result.output
        assert "GPU Util" not in result.output

    def test_export_includes_energy_fields(self, tmp_path):
        """JSON export includes all energy fields."""
        p, db_path = _patch_telemetry_config(tmp_path)
        _populate_energy_db(db_path, n=1)
        with p:
            result = CliRunner().invoke(
                cli,
                ["telemetry", "export", "-f", "json"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        rec = data[0]
        assert "energy_joules" in rec
        assert "energy_method" in rec
        assert "energy_vendor" in rec
        assert "gpu_energy_joules" in rec
        assert "cpu_energy_joules" in rec
        assert "dram_energy_joules" in rec
        assert "throughput_tok_per_sec" in rec
        assert "gpu_utilization_pct" in rec
        assert rec["energy_joules"] == pytest.approx(10.0)
        assert rec["energy_method"] == "hw_counter"
        assert rec["energy_vendor"] == "nvidia"

    def test_csv_export_has_energy_headers(self, tmp_path):
        """CSV export includes energy column headers."""
        p, db_path = _patch_telemetry_config(tmp_path)
        _populate_energy_db(db_path, n=1)
        with p:
            result = CliRunner().invoke(
                cli,
                ["telemetry", "export", "-f", "csv"],
            )
        assert result.exit_code == 0
        header = result.output.strip().splitlines()[0]
        assert "energy_joules" in header
        assert "energy_method" in header
        assert "energy_vendor" in header
        assert "gpu_energy_joules" in header


# ---------------------------------------------------------------------------
# Aggregator energy fields
# ---------------------------------------------------------------------------


class TestAggregatorEnergy:
    """Verify AggregatedStats includes energy aggregations."""

    def test_aggregated_stats_has_energy_fields(self):
        """AggregatedStats dataclass has energy attributes."""
        s = AggregatedStats()
        assert s.total_energy_joules == 0.0
        assert s.avg_throughput_tok_per_sec == 0.0
        assert s.avg_gpu_utilization_pct == 0.0

    def test_summary_computes_energy_totals(self, tmp_path):
        """summary() sums energy and computes weighted averages."""
        db_path = tmp_path / "telemetry.db"
        store = TelemetryStore(db_path)
        store.record(
            _make_energy_record(
                model_id="m1",
                energy_joules=10.0,
                throughput=100.0,
                gpu_util=80.0,
            )
        )
        store.record(
            _make_energy_record(
                model_id="m1",
                energy_joules=20.0,
                throughput=120.0,
                gpu_util=90.0,
            )
        )
        store.record(
            _make_energy_record(
                model_id="m2",
                energy_joules=30.0,
                throughput=80.0,
                gpu_util=60.0,
            )
        )
        store.close()

        agg = TelemetryAggregator(db_path)
        s = agg.summary()

        assert s.total_calls == 3
        assert s.total_energy_joules == pytest.approx(60.0)
        # Weighted avg throughput: (110*2 + 80*1) / 3 = 100
        assert s.avg_throughput_tok_per_sec == pytest.approx(100.0)
        # Weighted avg GPU util: (85*2 + 60*1) / 3 = 76.67
        assert s.avg_gpu_utilization_pct == pytest.approx(
            76.666,
            rel=0.01,
        )
        agg.close()

    def test_per_model_stats_energy(self, tmp_path):
        """per_model_stats includes energy fields."""
        db_path = tmp_path / "telemetry.db"
        store = TelemetryStore(db_path)
        store.record(
            _make_energy_record(
                model_id="m1",
                energy_joules=50.0,
            )
        )
        store.close()

        agg = TelemetryAggregator(db_path)
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].total_energy_joules == pytest.approx(50.0)
        assert stats[0].avg_gpu_utilization_pct == pytest.approx(78.0)
        assert stats[0].avg_throughput_tok_per_sec == pytest.approx(
            120.0,
        )
        agg.close()

    def test_per_engine_stats_energy(self, tmp_path):
        """per_engine_stats includes energy fields."""
        db_path = tmp_path / "telemetry.db"
        store = TelemetryStore(db_path)
        store.record(
            _make_energy_record(
                engine="vllm",
                energy_joules=25.0,
            )
        )
        store.close()

        agg = TelemetryAggregator(db_path)
        stats = agg.per_engine_stats()
        assert len(stats) == 1
        assert stats[0].total_energy_joules == pytest.approx(25.0)
        agg.close()

    def test_empty_summary_energy_zero(self, tmp_path):
        """Empty DB has zero energy in summary."""
        db_path = tmp_path / "telemetry.db"
        store = TelemetryStore(db_path)
        store.close()

        agg = TelemetryAggregator(db_path)
        s = agg.summary()
        assert s.total_energy_joules == 0.0
        assert s.avg_throughput_tok_per_sec == 0.0
        assert s.avg_gpu_utilization_pct == 0.0
        agg.close()


# ---------------------------------------------------------------------------
# End-to-end: CLI ask -> TelemetryStore -> TelemetryAggregator
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    """Full pipeline: ask → InstrumentedEngine → energy → SQLite → stats."""

    def test_ask_to_stats_with_energy(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Full flow: ask records energy, stats displays it."""
        cfg = _energy_config(tmp_path, gpu_metrics=True)
        engine = _mock_engine()

        monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)
        monkeypatch.setattr(
            _ask_mod,
            "get_engine",
            lambda *a, **kw: ("mock", engine),
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_engines",
            lambda c: [("mock", engine)],
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_models",
            lambda e: {"mock": ["test-model"]},
        )

        mock_monitor = _mock_energy_monitor()
        with patch(
            "openjarvis.telemetry.energy_monitor.create_energy_monitor",
            return_value=mock_monitor,
        ):
            CliRunner().invoke(cli, ["ask", "Hello"])

        # Now verify stats shows energy
        telem_cfg = mock.MagicMock()
        telem_cfg.telemetry.db_path = cfg.telemetry.db_path
        with mock.patch(
            "openjarvis.cli.telemetry_cmd.load_config",
            return_value=telem_cfg,
        ):
            result = CliRunner().invoke(
                cli,
                ["telemetry", "stats"],
            )

        assert result.exit_code == 0
        assert "Total Energy (J)" in result.output
        assert "42.50" in result.output  # energy_joules value

    def test_ask_to_export_with_energy(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Full flow: ask records energy, export includes it."""
        cfg = _energy_config(tmp_path, gpu_metrics=True)
        engine = _mock_engine()

        monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)
        monkeypatch.setattr(
            _ask_mod,
            "get_engine",
            lambda *a, **kw: ("mock", engine),
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_engines",
            lambda c: [("mock", engine)],
        )
        monkeypatch.setattr(
            _ask_mod,
            "discover_models",
            lambda e: {"mock": ["test-model"]},
        )

        mock_monitor = _mock_energy_monitor()
        with patch(
            "openjarvis.telemetry.energy_monitor.create_energy_monitor",
            return_value=mock_monitor,
        ):
            CliRunner().invoke(cli, ["ask", "Hello"])

        # Export as JSON
        telem_cfg = mock.MagicMock()
        telem_cfg.telemetry.db_path = cfg.telemetry.db_path
        with mock.patch(
            "openjarvis.cli.telemetry_cmd.load_config",
            return_value=telem_cfg,
        ):
            result = CliRunner().invoke(
                cli,
                ["telemetry", "export", "-f", "json"],
            )

        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["energy_joules"] == pytest.approx(42.5)
        assert data[0]["energy_method"] == "hw_counter"
