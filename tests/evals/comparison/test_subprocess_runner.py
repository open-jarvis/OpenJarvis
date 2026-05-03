"""Tests for openjarvis.evals.backends.external._subprocess_runner."""

from __future__ import annotations

from openjarvis.evals.backends.external._subprocess_runner import (
    EnergySample,
    SubprocessResult,
)


class TestSubprocessResult:
    def test_dataclass_fields(self) -> None:
        result = SubprocessResult(
            stdout="hello",
            stderr="",
            exit_code=0,
            latency_seconds=1.5,
            energy_joules=100.0,
            peak_power_w=20.0,
            sampler_method="nvml",
            parsed_json={"content": "x"},
        )
        assert result.stdout == "hello"
        assert result.exit_code == 0
        assert result.energy_joules == 100.0
        assert result.parsed_json == {"content": "x"}


class TestEnergySample:
    def test_dataclass_fields(self) -> None:
        s = EnergySample(timestamp=1.0, watts=15.5)
        assert s.timestamp == 1.0
        assert s.watts == 15.5
