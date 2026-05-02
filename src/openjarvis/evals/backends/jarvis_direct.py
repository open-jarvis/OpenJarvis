"""Jarvis Direct backend — engine-level inference for local and cloud models."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from openjarvis.evals.core.backend import InferenceBackend


class JarvisDirectBackend(InferenceBackend):
    """Direct engine inference via SystemBuilder.

    Works for both local models (Ollama, vLLM, etc.) and cloud models
    (OpenAI, Anthropic, Google) via the CloudEngine.
    """

    backend_id = "jarvis-direct"

    def __init__(
        self,
        engine_key: Optional[str] = None,
        engine_config: Optional[Dict[str, Any]] = None,
        telemetry: bool = False,
        gpu_metrics: bool = False,
    ) -> None:
        from openjarvis.system import SystemBuilder

        self._telemetry = telemetry
        self._gpu_metrics = gpu_metrics

        builder = SystemBuilder()
        if engine_key:
            builder.engine(engine_key)

        # Apply engine-specific config overrides from eval TOML
        if engine_config and engine_key:
            # Apply engine config to the builder's config
            # For vllm: config.engine.vllm_host
            # For ollama: config.engine.ollama_host, etc.
            host_attr = f"{engine_key}_host"
            if "host" in engine_config:
                setattr(builder._config.engine, host_attr, engine_config["host"])

        # Propagate gpu_metrics to the runtime config so SystemBuilder
        # creates an EnergyMonitor / GpuMonitor for the InstrumentedEngine.
        if gpu_metrics:
            builder._config.telemetry.gpu_metrics = True
        # Always enable traces to collect trace_data for eval analysis
        self._system = builder.telemetry(telemetry).traces(True).build()

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

        # Extract trace data from the TraceCollector if available
        trace_data = None
        collector = getattr(self._system, "trace_collector", None)
        if collector is not None:
            trace = getattr(collector, "last_trace", None)
            if trace is not None:
                trace_data = {
                    "trace_id": trace.trace_id,
                    "steps": [
                        {
                            "step_type": (
                                step.step_type.value
                                if hasattr(step.step_type, "value")
                                else step.step_type
                            ),
                            "timestamp": step.timestamp,
                            "duration_seconds": step.duration_seconds,
                            "input": step.input,
                            "output": step.output,
                            "metadata": step.metadata,
                        }
                        for step in trace.steps
                    ],
                    "messages": trace.messages,
                    "total_tokens": trace.total_tokens,
                    "total_latency_seconds": trace.total_latency_seconds,
                }

        usage = result.get("usage", {})
        telemetry_data = result.get("_telemetry", {})
        return {
            "content": result.get("content", ""),
            "usage": usage,
            "model": result.get("model", model),
            "latency_seconds": elapsed,
            "cost_usd": result.get("cost_usd", 0.0),
            "ttft": result.get("ttft", telemetry_data.get("ttft", 0.0)),
            "energy_joules": telemetry_data.get("energy_joules", 0.0),
            "power_watts": telemetry_data.get("power_watts", 0.0),
            "gpu_utilization_pct": telemetry_data.get("gpu_utilization_pct", 0.0),
            "throughput_tok_per_sec": telemetry_data.get("throughput_tok_per_sec", 0.0),
            "trace_data": trace_data,
        }

    def close(self) -> None:
        self._system.close()


__all__ = ["JarvisDirectBackend"]
