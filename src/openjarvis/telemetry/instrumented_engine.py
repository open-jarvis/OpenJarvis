"""Transparent telemetry wrapper for inference engines."""

from __future__ import annotations

import statistics
import time
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Sequence

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, TelemetryRecord
from openjarvis.engine._stubs import InferenceEngine, StreamChunk
from openjarvis.telemetry.gpu_monitor import GpuSample

# ---------------------------------------------------------------------------
# ITL helpers
# ---------------------------------------------------------------------------


def _percentile(data: list[float], p: float) -> float:
    """Compute the p-th percentile using linear interpolation."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def _compute_itl_stats(itl_values_ms: list[float]) -> dict:
    """Compute ITL summary statistics from a list of inter-token latencies in ms."""
    if not itl_values_ms:
        return {
            "mean": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "std": 0.0,
        }
    return {
        "mean": statistics.mean(itl_values_ms),
        "median": statistics.median(itl_values_ms),
        "p90": _percentile(itl_values_ms, 0.90),
        "p95": _percentile(itl_values_ms, 0.95),
        "p99": _percentile(itl_values_ms, 0.99),
        "std": statistics.stdev(itl_values_ms) if len(itl_values_ms) > 1 else 0.0,
    }


class InstrumentedEngine(InferenceEngine):
    """Transparent wrapper that records telemetry around engine calls.

    Agents call ``engine.generate()`` normally -- they don't know
    about telemetry.  The wrapper publishes ``INFERENCE_START``,
    ``INFERENCE_END``, and ``TELEMETRY_RECORD`` events on the bus.

    If an ``energy_monitor`` is provided (new multi-vendor
    :class:`~openjarvis.telemetry.energy_monitor.EnergyMonitor`), it is
    preferred over the legacy ``gpu_monitor`` for energy measurement.
    """

    engine_id = "instrumented"

    def __init__(
        self,
        engine: InferenceEngine,
        bus: EventBus,
        gpu_monitor: Optional[Any] = None,
        energy_monitor: Optional[Any] = None,
    ) -> None:
        self._inner = engine
        self._bus = bus
        self._gpu_monitor = gpu_monitor
        self._energy_monitor = energy_monitor
        self._publishes_events = True

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate with telemetry recording."""
        self._bus.publish(
            EventType.INFERENCE_START,
            {
                "model": model,
                "message_count": len(messages),
            },
        )

        gpu_sample: Optional[GpuSample] = None
        energy_sample: Optional[Any] = None
        t0 = time.time()

        # Prefer EnergyMonitor over legacy GpuMonitor
        if self._energy_monitor is not None:
            with self._energy_monitor.sample() as energy_sample:
                result = self._inner.generate(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
        elif self._gpu_monitor is not None:
            with self._gpu_monitor.sample() as gpu_sample:
                result = self._inner.generate(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
        else:
            result = self._inner.generate(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        latency = time.time() - t0

        usage = result.get("usage", {})
        completion_tokens = usage.get("completion_tokens", 0)
        prompt_tokens_evaluated = usage.get("prompt_tokens_evaluated", 0)
        ttft = result.get("ttft", 0.0)
        throughput = completion_tokens / latency if latency > 0 else 0.0

        # Energy / GPU metrics from sample
        energy_joules = 0.0
        power_watts = 0.0
        gpu_utilization_pct = 0.0
        gpu_memory_used_gb = 0.0
        gpu_temperature_c = 0.0
        prefill_latency = 0.0
        energy_method = ""
        energy_vendor = ""
        cpu_energy_joules = 0.0
        gpu_energy_joules = 0.0
        dram_energy_joules = 0.0

        if energy_sample is not None:
            # New multi-vendor EnergyMonitor path
            energy_joules = energy_sample.energy_joules
            power_watts = energy_sample.mean_power_watts
            gpu_utilization_pct = energy_sample.mean_utilization_pct
            gpu_memory_used_gb = energy_sample.peak_memory_used_gb
            gpu_temperature_c = energy_sample.mean_temperature_c
            energy_method = energy_sample.energy_method
            energy_vendor = energy_sample.vendor
            cpu_energy_joules = energy_sample.cpu_energy_joules
            gpu_energy_joules = energy_sample.gpu_energy_joules
            dram_energy_joules = energy_sample.dram_energy_joules
        elif gpu_sample is not None:
            # Legacy GpuMonitor path
            energy_joules = gpu_sample.energy_joules
            power_watts = gpu_sample.mean_power_watts
            gpu_utilization_pct = gpu_sample.mean_utilization_pct
            gpu_memory_used_gb = gpu_sample.peak_memory_used_gb
            gpu_temperature_c = gpu_sample.mean_temperature_c
            energy_method = "polling"
            energy_vendor = "nvidia"

        if ttft > 0:
            prefill_latency = ttft

        # --- Tier 1: Derived metrics ---
        energy_per_output_token = (
            energy_joules / completion_tokens if completion_tokens > 0 else 0.0
        )
        throughput_per_watt = throughput / power_watts if power_watts > 0 else 0.0

        # --- Tier 2.1: Phase energy split ---
        decode_latency = latency - prefill_latency if prefill_latency > 0 else 0.0
        prefill_energy = 0.0
        decode_energy = 0.0
        if energy_joules > 0 and prefill_latency > 0 and latency > 0:
            prefill_frac = prefill_latency / latency
            prefill_energy = energy_joules * prefill_frac
            decode_energy = energy_joules * (1.0 - prefill_frac)

        # --- Tier 3: Non-streaming mean ITL approximation ---
        mean_itl_ms = (
            (decode_latency / completion_tokens) * 1000
            if completion_tokens > 0 and decode_latency > 0
            else 0.0
        )

        # --- Tier 4: Per-inference efficiency ---
        tokens_per_joule = (
            completion_tokens / energy_joules
            if energy_joules > 0 and completion_tokens > 0
            else 0.0
        )

        engine_id = getattr(self._inner, "engine_id", "unknown")

        prompt_tok = usage.get("prompt_tokens", 0)
        record = TelemetryRecord(
            timestamp=t0,
            model_id=model,
            prompt_tokens=prompt_tok,
            prompt_tokens_evaluated=prompt_tokens_evaluated or prompt_tok,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tok + completion_tokens,
            latency_seconds=latency,
            ttft=ttft,
            throughput_tok_per_sec=throughput,
            energy_per_output_token_joules=energy_per_output_token,
            throughput_per_watt=throughput_per_watt,
            energy_joules=energy_joules,
            power_watts=power_watts,
            gpu_utilization_pct=gpu_utilization_pct,
            gpu_memory_used_gb=gpu_memory_used_gb,
            gpu_temperature_c=gpu_temperature_c,
            prefill_latency_seconds=prefill_latency,
            decode_latency_seconds=decode_latency,
            prefill_energy_joules=prefill_energy,
            decode_energy_joules=decode_energy,
            mean_itl_ms=mean_itl_ms,
            engine=engine_id,
            energy_method=energy_method,
            energy_vendor=energy_vendor,
            cpu_energy_joules=cpu_energy_joules,
            gpu_energy_joules=gpu_energy_joules,
            dram_energy_joules=dram_energy_joules,
            tokens_per_joule=tokens_per_joule,
        )

        event_data = {
            "model": model,
            "latency": latency,
            "usage": usage,
            "ttft": ttft,
            "throughput_tok_per_sec": throughput,
            "energy_per_output_token_joules": energy_per_output_token,
            "throughput_per_watt": throughput_per_watt,
            "energy_joules": energy_joules,
            "power_watts": power_watts,
            "gpu_utilization_pct": gpu_utilization_pct,
            "gpu_memory_used_gb": gpu_memory_used_gb,
            "gpu_temperature_c": gpu_temperature_c,
            "prefill_latency_seconds": prefill_latency,
            "decode_latency_seconds": decode_latency,
            "prefill_energy_joules": prefill_energy,
            "decode_energy_joules": decode_energy,
            "mean_itl_ms": mean_itl_ms,
            "energy_method": energy_method,
            "energy_vendor": energy_vendor,
            # Rich trace data: model response content + structured blocks
            "content": result.get("content", ""),
            "tool_calls": result.get("tool_calls", []),
            "tool_results": result.get("tool_results", []),
            "content_blocks": result.get("content_blocks", []),
            "finish_reason": result.get("finish_reason", ""),
        }

        self._bus.publish(EventType.INFERENCE_END, event_data)
        self._bus.publish(EventType.TELEMETRY_RECORD, {"record": record})

        # Inject telemetry dict into result for downstream consumers (eval backend)
        result["_telemetry"] = {
            "latency": latency,
            "ttft": ttft,
            "throughput_tok_per_sec": throughput,
            "energy_per_output_token_joules": energy_per_output_token,
            "throughput_per_watt": throughput_per_watt,
            "energy_joules": energy_joules,
            "power_watts": power_watts,
            "gpu_utilization_pct": gpu_utilization_pct,
            "gpu_memory_used_gb": gpu_memory_used_gb,
            "gpu_temperature_c": gpu_temperature_c,
            "prefill_latency_seconds": prefill_latency,
            "decode_latency_seconds": decode_latency,
            "prefill_energy_joules": prefill_energy,
            "decode_energy_joules": decode_energy,
            "mean_itl_ms": mean_itl_ms,
            "energy_method": energy_method,
            "energy_vendor": energy_vendor,
            "cpu_energy_joules": cpu_energy_joules,
            "gpu_energy_joules": gpu_energy_joules,
            "dram_energy_joules": dram_energy_joules,
        }

        return result

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Any:
        """Stream with per-token timing and full telemetry recording."""
        self._bus.publish(
            EventType.INFERENCE_START,
            {
                "model": model,
                "message_count": len(messages),
            },
        )

        t0 = time.time()
        token_timestamps: list[float] = []
        token_count = 0

        energy_sample: Optional[Any] = None
        gpu_sample: Optional[GpuSample] = None

        if self._energy_monitor is not None:
            with self._energy_monitor.sample() as energy_sample:
                async for token in self._inner.stream(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ):
                    token_timestamps.append(time.time())
                    token_count += 1
                    yield token
        elif self._gpu_monitor is not None:
            with self._gpu_monitor.sample() as gpu_sample:
                async for token in self._inner.stream(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ):
                    token_timestamps.append(time.time())
                    token_count += 1
                    yield token
        else:
            async for token in self._inner.stream(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                token_timestamps.append(time.time())
                token_count += 1
                yield token

        latency = time.time() - t0
        ttft = token_timestamps[0] - t0 if token_timestamps else 0.0
        throughput = token_count / latency if latency > 0 else 0.0

        # Compute ITL from consecutive timestamps
        itl_values_ms = [
            (token_timestamps[i] - token_timestamps[i - 1]) * 1000
            for i in range(1, len(token_timestamps))
        ]
        itl_stats = _compute_itl_stats(itl_values_ms)

        # Energy / GPU metrics from sample
        energy_joules = 0.0
        power_watts = 0.0
        gpu_utilization_pct = 0.0
        gpu_memory_used_gb = 0.0
        gpu_temperature_c = 0.0
        energy_method = ""
        energy_vendor = ""
        cpu_energy_joules = 0.0
        gpu_energy_joules = 0.0
        dram_energy_joules = 0.0

        if energy_sample is not None:
            energy_joules = energy_sample.energy_joules
            power_watts = energy_sample.mean_power_watts
            gpu_utilization_pct = energy_sample.mean_utilization_pct
            gpu_memory_used_gb = energy_sample.peak_memory_used_gb
            gpu_temperature_c = energy_sample.mean_temperature_c
            energy_method = energy_sample.energy_method
            energy_vendor = energy_sample.vendor
            cpu_energy_joules = energy_sample.cpu_energy_joules
            gpu_energy_joules = energy_sample.gpu_energy_joules
            dram_energy_joules = energy_sample.dram_energy_joules
        elif gpu_sample is not None:
            energy_joules = gpu_sample.energy_joules
            power_watts = gpu_sample.mean_power_watts
            gpu_utilization_pct = gpu_sample.mean_utilization_pct
            gpu_memory_used_gb = gpu_sample.peak_memory_used_gb
            gpu_temperature_c = gpu_sample.mean_temperature_c
            energy_method = "polling"
            energy_vendor = "nvidia"

        prefill_latency = ttft if ttft > 0 else 0.0

        # Derived metrics
        energy_per_output_token = (
            energy_joules / token_count if token_count > 0 else 0.0
        )
        throughput_per_watt = throughput / power_watts if power_watts > 0 else 0.0

        # Phase energy split
        decode_latency = latency - prefill_latency if prefill_latency > 0 else 0.0
        prefill_energy = 0.0
        decode_energy = 0.0
        if energy_joules > 0 and prefill_latency > 0 and latency > 0:
            prefill_frac = prefill_latency / latency
            prefill_energy = energy_joules * prefill_frac
            decode_energy = energy_joules * (1.0 - prefill_frac)

        # Per-inference efficiency
        tokens_per_joule = (
            token_count / energy_joules
            if energy_joules > 0 and token_count > 0
            else 0.0
        )

        engine_id = getattr(self._inner, "engine_id", "unknown")

        record = TelemetryRecord(
            timestamp=t0,
            model_id=model,
            completion_tokens=token_count,
            latency_seconds=latency,
            ttft=ttft,
            throughput_tok_per_sec=throughput,
            energy_per_output_token_joules=energy_per_output_token,
            throughput_per_watt=throughput_per_watt,
            energy_joules=energy_joules,
            power_watts=power_watts,
            gpu_utilization_pct=gpu_utilization_pct,
            gpu_memory_used_gb=gpu_memory_used_gb,
            gpu_temperature_c=gpu_temperature_c,
            prefill_latency_seconds=prefill_latency,
            decode_latency_seconds=decode_latency,
            prefill_energy_joules=prefill_energy,
            decode_energy_joules=decode_energy,
            mean_itl_ms=itl_stats["mean"],
            median_itl_ms=itl_stats["median"],
            p90_itl_ms=itl_stats["p90"],
            p95_itl_ms=itl_stats["p95"],
            p99_itl_ms=itl_stats["p99"],
            std_itl_ms=itl_stats["std"],
            is_streaming=True,
            engine=engine_id,
            energy_method=energy_method,
            energy_vendor=energy_vendor,
            cpu_energy_joules=cpu_energy_joules,
            gpu_energy_joules=gpu_energy_joules,
            dram_energy_joules=dram_energy_joules,
            tokens_per_joule=tokens_per_joule,
        )

        event_data = {
            "model": model,
            "latency": latency,
            "ttft": ttft,
            "throughput_tok_per_sec": throughput,
            "completion_tokens": token_count,
            "is_streaming": True,
            "mean_itl_ms": itl_stats["mean"],
            "median_itl_ms": itl_stats["median"],
            "p95_itl_ms": itl_stats["p95"],
            "energy_joules": energy_joules,
            "power_watts": power_watts,
            "energy_method": energy_method,
            "energy_vendor": energy_vendor,
        }

        self._bus.publish(EventType.INFERENCE_END, event_data)
        self._bus.publish(EventType.TELEMETRY_RECORD, {"record": record})

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Delegate to inner engine's stream_full for tool-call support."""
        async for chunk in self._inner.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            yield chunk

    def list_models(self) -> List[str]:
        return self._inner.list_models()

    def health(self) -> bool:
        return self._inner.health()

    def close(self) -> None:
        self._inner.close()


__all__ = ["InstrumentedEngine", "_compute_itl_stats", "_percentile"]
