"""Tests for GPU monitor -- mock pynvml (no real GPU required)."""

from __future__ import annotations

import sys
import time
import types
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a fake pynvml module
# ---------------------------------------------------------------------------


@dataclass
class _FakeUtilization:
    gpu: int = 80
    memory: int = 50


@dataclass
class _FakeMemInfo:
    total: int = 24 * 1024**3
    used: int = 12 * 1024**3
    free: int = 12 * 1024**3


def _make_fake_pynvml(device_count: int = 1, power_mw: int = 300_000):
    """Return a fake pynvml module object."""
    mod = types.ModuleType("pynvml")
    mod.nvmlInit = MagicMock()
    mod.nvmlShutdown = MagicMock()
    mod.nvmlDeviceGetCount = MagicMock(return_value=device_count)
    mod.nvmlDeviceGetHandleByIndex = MagicMock(side_effect=lambda i: f"handle-{i}")
    mod.nvmlDeviceGetPowerUsage = MagicMock(return_value=power_mw)
    mod.nvmlDeviceGetUtilizationRates = MagicMock(return_value=_FakeUtilization())
    mod.nvmlDeviceGetMemoryInfo = MagicMock(return_value=_FakeMemInfo())
    mod.nvmlDeviceGetTemperature = MagicMock(return_value=65)
    mod.NVML_TEMPERATURE_GPU = 0
    return mod


def _snap(power=300, util=80, mem=12, temp=65, dev=0):
    """Shorthand to build a GpuSnapshot."""
    from openjarvis.telemetry.gpu_monitor import GpuSnapshot

    return GpuSnapshot(
        power_watts=power,
        utilization_pct=util,
        memory_used_gb=mem,
        temperature_c=temp,
        device_id=dev,
    )


# ---------------------------------------------------------------------------
# Tests: GpuHardwareSpec lookup
# ---------------------------------------------------------------------------


class TestGpuHardwareSpec:
    def test_lookup_exact_key(self):
        from openjarvis.telemetry.gpu_monitor import lookup_gpu_spec

        spec = lookup_gpu_spec("A100-SXM")
        assert spec is not None
        assert spec.tflops_fp16 == 312
        assert spec.bandwidth_gb_s == 2039
        assert spec.tdp_watts == 400

    def test_lookup_substring_match(self):
        from openjarvis.telemetry.gpu_monitor import lookup_gpu_spec

        spec = lookup_gpu_spec("NVIDIA H100-SXM 80GB")
        assert spec is not None
        assert spec.tflops_fp16 == 990

    def test_lookup_case_insensitive(self):
        from openjarvis.telemetry.gpu_monitor import lookup_gpu_spec

        spec = lookup_gpu_spec("nvidia rtx 4090")
        assert spec is not None
        assert spec.tflops_fp16 == 165

    def test_lookup_unknown_returns_none(self):
        from openjarvis.telemetry.gpu_monitor import lookup_gpu_spec

        assert lookup_gpu_spec("SOME-UNKNOWN-GPU-9999") is None

    def test_all_specs_present(self):
        from openjarvis.telemetry.gpu_monitor import GPU_SPECS

        expected = {
            "B200-SXM",
            "A100-SXM",
            "A100-PCIE",
            "H100-SXM",
            "H100-PCIE",
            "L40S",
            "A10",
            "RTX 4090",
            "RTX 3090",
            "MI300X",
            "MI250X",
            "M4 Max",
            "M2 Ultra",
        }
        assert set(GPU_SPECS.keys()) == expected

    def test_spec_is_frozen(self):
        from openjarvis.telemetry.gpu_monitor import GPU_SPECS

        spec = GPU_SPECS["A100-SXM"]
        with pytest.raises(AttributeError):
            spec.tflops_fp16 = 999


# ---------------------------------------------------------------------------
# Tests: energy integration math (trapezoidal rule)
# ---------------------------------------------------------------------------


class TestEnergyIntegration:
    def test_constant_power(self):
        """Constant 300W for 10 seconds = 3000 J."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        snapshots = [[_snap(power=300)] for _ in range(11)]
        timestamps = [float(i) for i in range(11)]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=10.0)
        assert sample.energy_joules == pytest.approx(3000.0, rel=1e-6)
        assert sample.mean_power_watts == pytest.approx(300.0, rel=1e-6)
        assert sample.peak_power_watts == pytest.approx(300.0, rel=1e-6)
        assert sample.duration_seconds == 10.0
        assert sample.num_snapshots == 11

    def test_linear_ramp(self):
        """Linear ramp 0W..400W over 4s => 800 J (trapezoidal)."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        snapshots = [
            [_snap(power=100.0 * i, util=50, mem=8, temp=60)] for i in range(5)
        ]
        timestamps = [float(i) for i in range(5)]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=4.0)
        assert sample.energy_joules == pytest.approx(800.0, rel=1e-6)
        assert sample.mean_power_watts == pytest.approx(200.0, rel=1e-6)
        assert sample.peak_power_watts == pytest.approx(400.0)

    def test_empty_snapshots(self):
        """No snapshots yields zeroed sample."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        sample = GpuMonitor._aggregate([], [], wall_duration=5.0)
        assert sample.energy_joules == 0.0
        assert sample.num_snapshots == 0
        assert sample.duration_seconds == 5.0

    def test_single_snapshot(self):
        """One snapshot: energy is zero (no interval)."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        snapshots = [[_snap(power=250, util=90, mem=16, temp=70)]]
        timestamps = [0.0]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=0.05)
        assert sample.energy_joules == 0.0
        assert sample.num_snapshots == 1
        assert sample.mean_power_watts == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# Tests: GpuSample aggregation
# ---------------------------------------------------------------------------


class TestGpuSampleAggregation:
    def test_peak_values(self):
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        snapshots = [
            [_snap(power=200, util=60, mem=10, temp=55)],
            [_snap(power=400, util=95, mem=20, temp=80)],
            [_snap(power=300, util=70, mem=15, temp=65)],
        ]
        timestamps = [0.0, 1.0, 2.0]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=2.0)
        assert sample.peak_power_watts == pytest.approx(400.0)
        assert sample.peak_utilization_pct == pytest.approx(95.0)
        assert sample.peak_memory_used_gb == pytest.approx(20.0)
        assert sample.peak_temperature_c == pytest.approx(80.0)

    def test_mean_values(self):
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        snapshots = [
            [_snap(power=100, util=40, mem=8, temp=50)],
            [_snap(power=200, util=60, mem=12, temp=60)],
            [_snap(power=300, util=80, mem=16, temp=70)],
        ]
        timestamps = [0.0, 1.0, 2.0]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=2.0)
        assert sample.mean_power_watts == pytest.approx(200.0)
        assert sample.mean_utilization_pct == pytest.approx(60.0)
        assert sample.mean_memory_used_gb == pytest.approx(12.0)
        assert sample.mean_temperature_c == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Tests: Multi-GPU aggregation
# ---------------------------------------------------------------------------


class TestMultiGpu:
    def test_multi_device_power_sum(self):
        """Power summed across devices; util/temp averaged."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        tick = [
            _snap(power=200, util=80, mem=10, temp=60, dev=0),
            _snap(power=300, util=90, mem=12, temp=70, dev=1),
        ]
        snapshots = [tick, tick]
        timestamps = [0.0, 1.0]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=1.0)
        assert sample.energy_joules == pytest.approx(500.0)
        assert sample.mean_power_watts == pytest.approx(500.0)
        assert sample.mean_utilization_pct == pytest.approx(85.0)
        assert sample.mean_memory_used_gb == pytest.approx(22.0)
        assert sample.mean_temperature_c == pytest.approx(65.0)

    def test_multi_device_varying_power(self):
        """Multi-GPU with varying power over time."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        snapshots = [
            [
                _snap(power=100, util=50, mem=8, temp=55, dev=0),
                _snap(power=100, util=50, mem=8, temp=55, dev=1),
            ],
            [
                _snap(power=300, util=90, mem=16, temp=75, dev=0),
                _snap(power=300, util=90, mem=16, temp=75, dev=1),
            ],
        ]
        timestamps = [0.0, 2.0]

        sample = GpuMonitor._aggregate(snapshots, timestamps, wall_duration=2.0)
        # Tick powers: 200, 600 => 0.5*(200+600)*2 = 800
        assert sample.energy_joules == pytest.approx(800.0)
        assert sample.peak_power_watts == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# Tests: context manager flow (with mocked pynvml)
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_sample_context_manager(self):
        """sample() starts/stops polling and populates result."""
        fake_pynvml = _make_fake_pynvml(device_count=1, power_mw=300_000)

        import openjarvis.telemetry.gpu_monitor as mod

        orig_avail = mod._PYNVML_AVAILABLE
        orig_pynvml = getattr(mod, "pynvml", None)
        mod._PYNVML_AVAILABLE = True
        mod.pynvml = fake_pynvml
        try:
            monitor = mod.GpuMonitor(poll_interval_ms=10)
            monitor._initialized = True
            monitor._device_count = 1
            monitor._handles = ["handle-0"]

            with monitor.sample() as result:
                time.sleep(0.1)

            assert result.duration_seconds > 0
            assert result.num_snapshots > 0
            assert result.mean_power_watts > 0
        finally:
            mod._PYNVML_AVAILABLE = orig_avail
            if orig_pynvml is not None:
                mod.pynvml = orig_pynvml

    def test_sample_no_gpu(self):
        """sample() yields empty GpuSample when no GPU."""
        from openjarvis.telemetry.gpu_monitor import GpuMonitor

        monitor = GpuMonitor.__new__(GpuMonitor)
        monitor._poll_interval_s = 0.05
        monitor._handles = []
        monitor._device_count = 0
        monitor._initialized = False

        with monitor.sample() as result:
            pass

        assert result.num_snapshots == 0
        assert result.energy_joules == 0.0
        assert result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# Tests: available()
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_available_false_when_pynvml_missing(self):
        """available() returns False when pynvml not importable."""
        import openjarvis.telemetry.gpu_monitor as mod

        orig = mod._PYNVML_AVAILABLE
        mod._PYNVML_AVAILABLE = False
        try:
            assert mod.GpuMonitor.available() is False
        finally:
            mod._PYNVML_AVAILABLE = orig

    def test_available_true_with_fake_pynvml(self):
        """available() returns True when pynvml can init."""
        fake_pynvml = _make_fake_pynvml()

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.gpu_monitor as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                assert mod.GpuMonitor.available() is True
                fake_pynvml.nvmlInit.assert_called()
                fake_pynvml.nvmlShutdown.assert_called()
            finally:
                mod._PYNVML_AVAILABLE = orig

    def test_available_false_when_init_fails(self):
        """available() returns False when nvmlInit raises."""
        fake_pynvml = _make_fake_pynvml()
        fake_pynvml.nvmlInit.side_effect = RuntimeError("no driver")

        with patch.dict(sys.modules, {"pynvml": fake_pynvml}):
            import openjarvis.telemetry.gpu_monitor as mod

            orig = mod._PYNVML_AVAILABLE
            mod._PYNVML_AVAILABLE = True
            mod.pynvml = fake_pynvml
            try:
                assert mod.GpuMonitor.available() is False
            finally:
                mod._PYNVML_AVAILABLE = orig


# ---------------------------------------------------------------------------
# Tests: dataclass defaults
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_gpu_snapshot_defaults(self):
        from openjarvis.telemetry.gpu_monitor import GpuSnapshot

        s = GpuSnapshot(
            power_watts=300,
            utilization_pct=80,
            memory_used_gb=12,
            temperature_c=65,
        )
        assert s.device_id == 0

    def test_gpu_sample_defaults(self):
        from openjarvis.telemetry.gpu_monitor import GpuSample

        s = GpuSample()
        assert s.energy_joules == 0.0
        assert s.num_snapshots == 0
        assert s.duration_seconds == 0.0
