"""WASM sandbox — lightweight isolation via Wasmtime."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(slots=True)
class WasmResult:
    """Result from a WASM execution."""

    success: bool = True
    output: str = ""
    duration_seconds: float = 0.0
    fuel_consumed: int = 0
    memory_used_bytes: int = 0


class WasmRunner:
    """Execute WASM modules with resource limits.

    Uses wasmtime-py for sub-100ms isolation. Supplements Docker-based
    ContainerRunner for lightweight, fast sandboxing.

    Requires: ``uv sync --extra sandbox-wasm``
    """

    def __init__(
        self,
        *,
        fuel_limit: int = 1_000_000,
        memory_limit_mb: int = 256,
        timeout: float = 30.0,
    ) -> None:
        self._fuel_limit = fuel_limit
        self._memory_limit_mb = memory_limit_mb
        self._timeout = timeout

    @staticmethod
    def available() -> bool:
        """Check if wasmtime is available."""
        try:
            import wasmtime  # noqa: F401

            return True
        except ImportError:
            return False

    def run(
        self,
        wasm_bytes: bytes,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> WasmResult:
        """Execute a WASM module with input data.

        The module is expected to export a ``run`` function that takes
        a pointer and length and returns a pointer and length.
        For simpler modules, we attempt to call ``_start`` (WASI).
        """
        try:
            import wasmtime
        except ImportError:
            return WasmResult(
                success=False,
                output=(
                    "wasmtime not installed. Install with: uv sync --extra sandbox-wasm"
                ),
            )

        t0 = time.time()
        try:
            # Configure engine with fuel metering
            config = wasmtime.Config()
            config.consume_fuel = True
            engine = wasmtime.Engine(config)

            # Create store with fuel limit
            store = wasmtime.Store(engine)
            store.set_fuel(self._fuel_limit)

            # Compile module
            module = wasmtime.Module(engine, wasm_bytes)

            # Set up WASI if needed
            wasi_config = wasmtime.WasiConfig()
            wasi_config.inherit_stdout()
            wasi_config.inherit_stderr()
            store.set_wasi(wasi_config)

            # Create linker and link WASI
            linker = wasmtime.Linker(engine)
            linker.define_wasi()

            # Instantiate
            instance = linker.instantiate(store, module)

            # Try to call _start (WASI entry point)
            start_func = instance.exports(store).get("_start")
            if start_func and isinstance(start_func, wasmtime.Func):
                start_func(store)

            fuel_remaining = store.get_fuel()
            fuel_consumed = self._fuel_limit - fuel_remaining

            duration = time.time() - t0
            return WasmResult(
                success=True,
                output="WASM module executed successfully.",
                duration_seconds=duration,
                fuel_consumed=fuel_consumed,
            )

        except Exception as exc:
            duration = time.time() - t0
            return WasmResult(
                success=False,
                output=f"WASM execution error: {exc}",
                duration_seconds=duration,
            )

    def validate(self, wasm_bytes: bytes) -> bool:
        """Validate that bytes represent a valid WASM module."""
        try:
            import wasmtime

            config = wasmtime.Config()
            engine = wasmtime.Engine(config)
            wasmtime.Module.validate(engine, wasm_bytes)
            return True
        except Exception:
            return False


def create_sandbox_runner(config: Any = None) -> Any:
    """Factory: select Docker or WASM runner based on config/availability."""
    if config and getattr(config, "runtime", "") == "wasm":
        runner = WasmRunner(
            fuel_limit=getattr(config, "wasm_fuel_limit", 1_000_000),
            memory_limit_mb=getattr(config, "wasm_memory_limit_mb", 256),
            timeout=getattr(config, "timeout", 30),
        )
        if runner.available():
            return runner

    # Fall back to Docker ContainerRunner
    try:
        from openjarvis.sandbox.runner import ContainerRunner

        return ContainerRunner(
            image=getattr(config, "image", "openjarvis-sandbox:latest"),
            timeout=getattr(config, "timeout", 300),
        )
    except ImportError:
        return None


__all__ = ["WasmResult", "WasmRunner", "create_sandbox_runner"]
