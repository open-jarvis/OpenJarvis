"""Jarvis Agent backend — agent-level inference with tool calling."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.evals.backends._commit_util import openjarvis_commit
from openjarvis.evals.core.backend import InferenceBackend


class JarvisAgentBackend(InferenceBackend):
    """Agent-level inference via SystemBuilder + JarvisSystem.ask().

    Supports tool calling via the agent harness. Works for both local
    and cloud models.
    """

    backend_id = "jarvis-agent"
    framework_name = "openjarvis"

    def __init__(
        self,
        engine_key: Optional[str] = None,
        agent_name: str = "orchestrator",
        tools: Optional[List[str]] = None,
        telemetry: bool = False,
        gpu_metrics: bool = False,
        model: Optional[str] = None,
        max_turns: Optional[int] = None,
        skills_enabled: bool = True,
        overlay_dir: Optional[Path] = None,
    ) -> None:
        from openjarvis.system import SystemBuilder

        self._agent_name = agent_name
        self._tools = tools or []
        self._telemetry = telemetry
        self._gpu_metrics = gpu_metrics

        builder = SystemBuilder()
        if engine_key:
            builder.engine(engine_key)
        if model:
            builder.model(model)
        builder.agent(agent_name)
        if tools:
            builder.tools(tools)
        # Propagate gpu_metrics to the runtime config so SystemBuilder
        # creates a GpuMonitor when building the InstrumentedEngine.
        if gpu_metrics:
            builder._config.telemetry.gpu_metrics = True
        # Override the agent's per-run turn budget. JarvisConfig.agent.max_turns
        # defaults to 10, which is too low for thinking/reasoning models on
        # multi-step agentic benchmarks (Trinity-Large hit the cap on 25/50
        # GAIA tasks before this was configurable per-eval).
        if max_turns is not None:
            builder._config.agent.max_turns = max_turns
        # Plan 2B: per-condition skill switches.  Mutate the builder's
        # config directly so SystemBuilder picks them up at build time.
        builder._config.skills.enabled = skills_enabled
        if overlay_dir is not None:
            builder._config.learning.skills.overlay_dir = str(overlay_dir)
        self._system = builder.telemetry(telemetry).traces(True).build()

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
        t0 = time.monotonic()
        ask_kwargs: dict = dict(
            agent=self._agent_name,
            tools=self._tools if self._tools else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if system:
            ask_kwargs["system_prompt"] = system
        result = self._system.ask(prompt, **ask_kwargs)
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

        # Spec §6.2 extended fields for cross-framework comparison.
        tool_calls_count = 0
        turn_count = 0
        if trace_data is not None:
            steps = trace_data.get("steps", [])
            tool_calls_count = sum(
                1 for s in steps if s.get("step_type") == "tool_call"
            )
            turn_count = sum(
                1 for s in steps if s.get("step_type") in ("model_call", "agent_turn")
            )
        # Fall back to result-reported counts when no trace is available so
        # the comparison harness still gets meaningful turn data.
        if turn_count == 0:
            turn_count = int(result.get("turns", 1) or 1)
        if tool_calls_count == 0:
            tool_results = result.get("tool_results", []) or []
            tool_calls_count = len(tool_results)

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
            "turns": result.get("turns", 1),
            "tool_results": result.get("tool_results", []),
            "ttft": result.get("ttft", telemetry_data.get("ttft", 0.0)),
            "energy_joules": energy_joules,
            "peak_power_w": peak_power_w,
            "power_watts": telemetry_data.get("power_watts", 0.0),
            "gpu_utilization_pct": telemetry_data.get("gpu_utilization_pct", 0.0),
            "throughput_tok_per_sec": telemetry_data.get("throughput_tok_per_sec", 0.0),
            "trace_data": trace_data,
            "tool_calls": tool_calls_count,
            "turn_count": turn_count,
            "framework": "openjarvis",
            "framework_commit": openjarvis_commit(),
            "error": None,
        }

    def set_task_metadata(self, metadata: dict) -> None:
        """Forward task environment metadata to the underlying agent."""
        agent = getattr(self._system, "_agent", None)
        if agent and hasattr(agent, "set_task_metadata"):
            agent.set_task_metadata(metadata)

    def close(self) -> None:
        self._system.close()


__all__ = ["JarvisAgentBackend"]
