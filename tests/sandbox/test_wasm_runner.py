"""Tests for WASM sandbox (Phase 16.4)."""

from __future__ import annotations

import pytest

from friday_ai.sandbox.wasm_runner import WasmResult, WasmRunner, create_sandbox_runner


class TestWasmRunner:
    def test_runner_creation(self):
        runner = WasmRunner(fuel_limit=500_000, memory_limit_mb=128, timeout=10)
        assert runner._fuel_limit == 500_000

    def test_available_check(self):
        result = WasmRunner.available()
        assert isinstance(result, bool)

    @pytest.mark.skipif(
        not WasmRunner.available(),
        reason="wasmtime not installed",
    )
    def test_validate_invalid_bytes(self):
        runner = WasmRunner()
        assert not runner.validate(b"not wasm")

    def test_run_without_wasmtime(self):
        runner = WasmRunner()
        if not runner.available():
            result = runner.run(b"fake wasm")
            assert not result.success
            assert "wasmtime" in result.output.lower()

    def test_wasm_result_dataclass(self):
        result = WasmResult(success=True, output="done", duration_seconds=0.1)
        assert result.success
        assert result.output == "done"
        assert result.duration_seconds == 0.1


class TestCreateSandboxRunner:
    def test_factory_returns_something(self):
        # Should return either a WasmRunner or ContainerRunner or None
        create_sandbox_runner()
        # May be None if neither Docker nor wasmtime is available
        # Just verify it doesn't crash

    def test_factory_with_wasm_config(self):
        class FakeConfig:
            runtime = "wasm"
            wasm_fuel_limit = 100_000
            wasm_memory_limit_mb = 64
            timeout = 10
            image = "test"

        runner = create_sandbox_runner(FakeConfig())
        if WasmRunner.available():
            assert isinstance(runner, WasmRunner)
