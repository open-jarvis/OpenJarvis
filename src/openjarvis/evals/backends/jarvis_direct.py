"""Jarvis Direct backend — engine-level inference for local and cloud models."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from openjarvis.evals.backends._commit_util import openjarvis_commit
from openjarvis.evals.core.backend import InferenceBackend


class JarvisDirectBackend(InferenceBackend):
    """Direct engine inference via SystemBuilder.

    Works for both local models (Ollama, vLLM, etc.) and cloud models
    (OpenAI, Anthropic, Google) via the CloudEngine.
    """

    backend_id = "jarvis-direct"
    framework_name = "openjarvis"

    def __init__(
        self,
        engine_key: Optional[str] = None,
        telemetry: bool = False,
        gpu_metrics: bool = False,
    ) -> None:
        from openjarvis.system import SystemBuilder

        self._telemetry = telemetry
        self._gpu_metrics = gpu_metrics

        builder = SystemBuilder()
        if engine_key:
            builder.engine(engine_key)
        # Propagate gpu_metrics to the runtime config so SystemBuilder
        # creates an EnergyMonitor / GpuMonitor for the InstrumentedEngine.
        if gpu_metrics:
            builder._config.telemetry.gpu_metrics = True
        self._system = builder.telemetry(telemetry).traces(telemetry).build()

    @property
    def framework_commit_value(self) -> str:
        """OpenJarvis repo HEAD commit (for telemetry tagging)."""
        from openjarvis.evals.backends._commit_util import openjarvis_commit

        return openjarvis_commit()

    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        result = self.generate_full(
            prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return result["content"]

    def generate_full(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        from openjarvis.core.types import Message, Role

        messages = []
        if system:
            messages.append(Message(role=Role.SYSTEM, content=system))
        messages.append(Message(role=Role.USER, content=prompt))

        t0 = time.monotonic()
        result = self._system.engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        elapsed = time.monotonic() - t0

        usage = result.get("usage", {})
        telemetry_data = result.get("_telemetry", {})

        # Spec §6.2 extended fields for cross-framework comparison.
        # Route real telemetry into the spec field names where present;
        # ``None`` signals "not measured" to downstream consumers.
        energy_joules = telemetry_data.get("energy_joules")
        peak_power_w = telemetry_data.get("peak_power_w")
        if peak_power_w is None:
            # Older telemetry payloads expose only the running power; treat
            # it as a coarse peak proxy when no explicit max is recorded.
            peak_power_w = telemetry_data.get("power_watts")

        return {
            "content": result.get("content", ""),
            "usage": usage,
            "model": result.get("model", model),
            "latency_seconds": elapsed,
            "cost_usd": result.get("cost_usd", 0.0),
            "ttft": result.get("ttft", telemetry_data.get("ttft", 0.0)),
            "energy_joules": energy_joules,
            "peak_power_w": peak_power_w,
            "power_watts": telemetry_data.get("power_watts", 0.0),
            "gpu_utilization_pct": telemetry_data.get("gpu_utilization_pct", 0.0),
            "throughput_tok_per_sec": telemetry_data.get("throughput_tok_per_sec", 0.0),
            "tool_calls": 0,
            "turn_count": 1,
            "framework": "openjarvis",
            "framework_commit": openjarvis_commit(),
            "error": None,
        }

    def close(self) -> None:
        self._system.close()


__all__ = ["JarvisDirectBackend"]
