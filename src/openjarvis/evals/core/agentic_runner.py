"""AgenticRunner — multi-turn agent execution with energy telemetry correlation.

Orchestrates agentic workloads where a single query may involve multiple
LLM turns and tool calls, capturing per-turn traces with energy attribution.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Optional

from openjarvis.evals.core.event_recorder import AgentEvent, EventRecorder, EventType
from openjarvis.evals.core.trace import QueryTrace, TurnTrace

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Energy computation helpers
# ---------------------------------------------------------------------------


def _compute_energy_delta(
    readings: list[Any],
    gpu_field: str = "gpu_energy_j",
) -> Optional[float]:
    """Compute energy delta from first to last reading for a field."""
    values = [
        getattr(s, gpu_field, None)
        for s in readings
    ]
    values = [v for v in values if v is not None and math.isfinite(v)]
    if len(values) >= 2:
        delta = values[-1] - values[0]
        return delta if delta >= 0 else None
    return None


def _compute_power_avg(
    readings: list[Any],
    power_field: str = "gpu_power_w",
) -> Optional[float]:
    """Compute average power across readings for a field."""
    values = [
        getattr(s, power_field, None)
        for s in readings
    ]
    values = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.mean(values) if values else None


# ---------------------------------------------------------------------------
# Patch extraction helpers
# ---------------------------------------------------------------------------

_FENCED_DIFF_RE = re.compile(
    r"```(?:diff|patch)\s*\n(.*?)```", re.DOTALL
)
_UNIFIED_DIFF_MARKERS = ("diff --git", "--- a/", "+++ b/", "@@ ")


def _extract_patch(text: str) -> Optional[str]:
    """Extract a unified-diff patch from agent response text."""
    fenced = _FENCED_DIFF_RE.findall(text)
    if fenced:
        return "\n\n".join(block.strip() for block in fenced)

    lines = text.splitlines()
    patch_lines: list[str] = []
    in_diff = False
    for line in lines:
        if any(line.startswith(m) for m in _UNIFIED_DIFF_MARKERS):
            in_diff = True
        if in_diff:
            patch_lines.append(line)

    if patch_lines:
        return "\n".join(patch_lines)
    return None


class AgenticRunner:
    """Orchestrate multi-turn agent runs with energy telemetry correlation.

    Designed for agentic workloads where a single query may involve multiple
    LLM turns and tool calls.  Captures per-turn ``TurnTrace`` objects with
    energy attribution and builds ``QueryTrace`` aggregates.
    """

    _FLUSH_INTERVAL = 50

    def __init__(
        self,
        agent: Any,
        dataset: Any,
        telemetry_session: Any = None,
        config: Optional[dict[str, Any]] = None,
        event_recorder: Optional[EventRecorder] = None,
        run_dir: Optional[Path] = None,
        concurrency: int = 1,
        agent_factory: Optional[Callable[[], Any]] = None,
        query_timeout: Optional[float] = None,
    ) -> None:
        self._agent = agent
        self._dataset = dataset
        self._telemetry = telemetry_session
        self._config = config or {}
        self._event_recorder = (
            event_recorder if event_recorder is not None else EventRecorder()
        )
        self._run_dir = run_dir
        self._traces: list[QueryTrace] = []
        self._concurrency = max(1, concurrency)
        self._agent_factory = agent_factory
        self._query_timeout = query_timeout
        self._results_lock = threading.Lock()

    async def run(self, max_queries: Optional[int] = None) -> list[QueryTrace]:
        """Run the agent over the dataset, collecting traces and telemetry.

        Args:
            max_queries: Maximum number of queries to process. None means all.

        Returns:
            List of ``QueryTrace`` objects with energy-correlated telemetry.
        """
        records = list(self._dataset.iter_records())
        total = max_queries if max_queries is not None else len(records)
        records = records[:total]
        model = self._config.get("model", "unknown")

        work_items = list(enumerate(records))

        if self._concurrency <= 1:
            return await self._run_sequential(work_items, model)
        return await self._run_concurrent(work_items, model)

    async def _run_sequential(
        self,
        work_items: list[tuple[int, Any]],
        model: str,
    ) -> list[QueryTrace]:
        """Sequential execution path."""
        for index, record in work_items:
            query_id = f"q{index:04d}"
            start_time = time.time()
            try:
                fut = self._run_single_query(
                    index, record, model, self._agent, self._event_recorder
                )
                if self._query_timeout:
                    trace = await asyncio.wait_for(
                        fut, timeout=self._query_timeout
                    )
                else:
                    trace = await fut
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                LOGGER.warning(
                    "Query %s timed out after %.0fs (limit=%ss)",
                    query_id, elapsed, self._query_timeout,
                )
                workload_type = getattr(record, "category", "agentic")
                trace = QueryTrace(
                    query_id=query_id,
                    workload_type=str(workload_type),
                    query_text=record.problem,
                    response_text=f"Query timed out after {elapsed:.0f}s",
                    total_wall_clock_s=elapsed,
                    completed=False,
                    timed_out=True,
                    is_resolved=record.metadata.get("is_resolved"),
                )
            self._traces.append(trace)

            status = (
                "TIMEOUT" if trace.timed_out
                else ("OK" if trace.completed else "FAIL")
            )
            LOGGER.info(
                "Task %s: %s in %.1fs",
                query_id, status, trace.total_wall_clock_s,
            )

            if self._run_dir:
                self._save_query_artifacts(index, record, trace)

            if len(self._traces) % self._FLUSH_INTERVAL == 0:
                LOGGER.debug(
                    "Processed %d/%d queries",
                    len(self._traces), len(work_items),
                )

        return self._traces

    async def _run_concurrent(
        self,
        work_items: list[tuple[int, Any]],
        model: str,
    ) -> list[QueryTrace]:
        """Concurrent execution via asyncio.Semaphore + thread pool."""
        total = len(work_items)
        LOGGER.info(
            "Running %d queries with concurrency=%d",
            total, self._concurrency,
        )

        result_slots: list[Optional[QueryTrace]] = [None] * total
        semaphore = asyncio.Semaphore(self._concurrency)
        loop = asyncio.get_event_loop()

        async def _process(slot: int, index: int, record: Any) -> None:
            async with semaphore:
                if self._agent_factory is not None:
                    agent = self._agent_factory()
                else:
                    agent = copy.deepcopy(self._agent)
                recorder = EventRecorder()

                query_id = f"q{index:04d}"
                start_time = time.time()

                try:
                    fut = loop.run_in_executor(
                        None,
                        self._run_single_query_sync,
                        index, record, model, agent, recorder,
                    )
                    if self._query_timeout:
                        trace = await asyncio.wait_for(
                            fut, timeout=self._query_timeout
                        )
                    else:
                        trace = await fut
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    LOGGER.warning(
                        "Query %s timed out after %.0fs (limit=%ss)",
                        query_id, elapsed, self._query_timeout,
                    )
                    workload_type = getattr(record, "category", "agentic")
                    trace = QueryTrace(
                        query_id=query_id,
                        workload_type=str(workload_type),
                        query_text=record.problem,
                        response_text=f"Query timed out after {elapsed:.0f}s",
                        total_wall_clock_s=elapsed,
                        completed=False,
                        timed_out=True,
                        is_resolved=record.metadata.get("is_resolved"),
                    )

                status = (
                    "TIMEOUT" if trace.timed_out
                    else ("OK" if trace.completed else "FAIL")
                )
                LOGGER.info(
                    "Task %s: %s in %.1fs",
                    query_id, status, trace.total_wall_clock_s,
                )

                if self._run_dir:
                    self._save_query_artifacts(index, record, trace)

                with self._results_lock:
                    result_slots[slot] = trace

        tasks = [
            _process(slot, index, record)
            for slot, (index, record) in enumerate(work_items)
        ]
        await asyncio.gather(*tasks)

        for slot_result in result_slots:
            if slot_result is not None:
                self._traces.append(slot_result)

        return self._traces

    def _run_single_query_sync(
        self,
        index: int,
        record: Any,
        model: str,
        agent: Any,
        event_recorder: EventRecorder,
    ) -> QueryTrace:
        """Synchronous wrapper for ``_run_single_query``."""
        return asyncio.run(
            self._run_single_query(index, record, model, agent, event_recorder)
        )

    async def _run_single_query(
        self,
        index: int,
        record: Any,
        model: str,
        agent: Optional[Any] = None,
        event_recorder: Optional[EventRecorder] = None,
    ) -> QueryTrace:
        """Run a single query through the agent with telemetry capture."""
        agent = agent or self._agent
        event_recorder = event_recorder or self._event_recorder

        query_id = f"q{index:04d}"
        workload_type = getattr(record, "category", "agentic")

        start_time = time.time()
        start_ns = time.monotonic_ns()

        event_recorder.clear()

        # Bridge EventBus → EventRecorder so tool events are captured.
        # ToolExecutor publishes to JarvisSystem.bus; we relay those into
        # the EventRecorder for transcript building and trace enrichment.
        _bus_unsubs: list[tuple] = []
        agent_bus = getattr(agent, "bus", None)
        if agent_bus is not None:
            for etype in (EventType.TOOL_CALL_START, EventType.TOOL_CALL_END):
                def _relay(event, _etype=etype):
                    data = event.data if hasattr(event, "data") else {}
                    event_recorder.record(_etype, **data)
                agent_bus.subscribe(etype, _relay)
                _bus_unsubs.append((etype, _relay))

        # Set up per-query workspace
        if self._run_dir and hasattr(agent, "set_workspace"):
            instance_id = record.metadata.get("instance_id", record.record_id)
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", str(instance_id))[:80]
            workspace = (
                self._run_dir / "artifacts" / f"q{index:04d}_{slug}" / "workspace"
            )
            workspace.mkdir(parents=True, exist_ok=True)
            agent.set_workspace(str(workspace))
            record.metadata["workspace_path"] = str(workspace)

        # Create per-task execution environment (e.g. Docker for TerminalBench)
        task_env = None
        if hasattr(self._dataset, "create_task_env"):
            task_env = self._dataset.create_task_env(record)
        ctx = task_env if task_env is not None else nullcontext()

        response_text = ""
        result_tokens: dict[str, int] = {}

        def _run_body() -> None:
            nonlocal response_text, result_tokens
            with ctx:
                # Forward task metadata to agent
                if task_env is not None and hasattr(agent, "set_task_metadata"):
                    agent.set_task_metadata(record.metadata)

                # Envs with reset/step/evaluate use run_agent_loop
                # for multi-turn interaction with conversation history.
                if task_env is not None and hasattr(task_env, "run_agent_loop"):
                    def _generate(prompt: str) -> str:
                        if hasattr(agent, "ask"):
                            r = agent.ask(prompt)
                            if isinstance(r, dict):
                                return r.get("content", str(r))
                            return str(r)
                        elif hasattr(agent, "run"):
                            r = agent.run(prompt)
                            return getattr(r, "content", str(r))
                        return str(agent(prompt))

                    task_env.run_agent_loop(_generate)

                    # Collect full interaction from run_agent_loop
                    if hasattr(task_env, "all_responses") and task_env.all_responses:
                        response_text = "\n---\n".join(task_env.all_responses)
                    else:
                        response_text = ""
                else:
                    # Standard one-shot agent execution
                    if hasattr(agent, "ask"):
                        # SystemBuilder-based agent (JarvisSystem)
                        result = agent.ask(record.problem)
                        if isinstance(result, dict):
                            response_text = result.get("content", "")
                            usage = result.get("usage", {})
                            result_tokens = {
                                "input_tokens": usage.get("prompt_tokens", 0),
                                "output_tokens": usage.get("completion_tokens", 0),
                                "cost_usd": result.get("cost_usd", 0.0),
                            }
                        else:
                            response_text = str(result)
                    elif hasattr(agent, "run"):
                        # BaseAgent-style
                        result = agent.run(record.problem)
                        response_text = getattr(result, "content", str(result))
                        result_tokens = {
                            "input_tokens": getattr(result, "input_tokens", 0)
                            or 0,
                            "output_tokens": getattr(result, "output_tokens", 0)
                            or 0,
                            "cost_usd": getattr(result, "cost_usd", 0.0) or 0.0,
                        }
                    else:
                        response_text = str(agent(record.problem))

                # Wire event recorder to task env if supported
                if task_env is not None and hasattr(task_env, "set_event_recorder"):
                    task_env.set_event_recorder(event_recorder)

                # Run tests if task env supports it
                if task_env is not None and hasattr(task_env, "run_tests"):
                    task_env.run_tests()

                # Read back evaluate() result from reset/step/evaluate envs
                if task_env is not None and hasattr(task_env, "last_eval_result"):
                    eval_result = task_env.last_eval_result
                    if eval_result is not None:
                        is_correct, eval_meta = eval_result
                        record.metadata["is_resolved"] = is_correct
                        record.metadata["eval_meta"] = eval_meta

        try:
            if task_env is not None:
                # Playwright's sync API refuses to run when an asyncio loop
                # is active on the current thread, AND it leaves process-level
                # singleton state (Selectors, Transport) that breaks when a
                # pooled thread is reused. Use a one-shot ThreadPoolExecutor
                # so every task gets a guaranteed-fresh thread.
                loop = asyncio.get_running_loop()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    await loop.run_in_executor(executor, _run_body)
            else:
                _run_body()

        except Exception as exc:
            LOGGER.warning("Agent failed on query %s: %s", query_id, exc)
            end_time = time.time()
            # Unsubscribe EventBus relays
            if agent_bus is not None:
                for etype, cb in _bus_unsubs:
                    try:
                        agent_bus.unsubscribe(etype, cb)
                    except Exception:
                        pass
            return QueryTrace(
                query_id=query_id,
                workload_type=str(workload_type),
                query_text=record.problem,
                response_text=str(exc),
                total_wall_clock_s=end_time - start_time,
                completed=False,
                is_resolved=record.metadata.get("is_resolved"),
            )

        # Unsubscribe EventBus relays
        if agent_bus is not None:
            for etype, cb in _bus_unsubs:
                try:
                    agent_bus.unsubscribe(etype, cb)
                except Exception:
                    pass

        end_time = time.time()
        end_ns = time.monotonic_ns()

        # Collect telemetry samples for this query window
        readings: list[Any] = []
        if self._telemetry is not None:
            readings = self._telemetry.window(start_ns, end_ns)

        # Build turn traces from event recorder
        events = event_recorder.get_events()
        turns = self._build_turn_traces(events, readings)

        # Build turn traces from task_env's run_agent_loop data when
        # the EventRecorder captured nothing (run_agent_loop calls
        # agent.ask() directly, bypassing the recorder).
        if (
            not turns
            and task_env is not None
            and hasattr(task_env, "turn_wall_clocks")
            and task_env.turn_wall_clocks
        ):
            turns = [
                TurnTrace(turn_index=i, wall_clock_s=tw)
                for i, tw in enumerate(task_env.turn_wall_clocks)
            ]

        # Synthetic turn when EventRecorder captured nothing
        in_tok = result_tokens.get("input_tokens", 0)
        out_tok = result_tokens.get("output_tokens", 0)
        cost = result_tokens.get("cost_usd", 0.0)
        if not turns and (in_tok > 0 or out_tok > 0):
            turns = [TurnTrace(
                turn_index=0,
                input_tokens=in_tok,
                output_tokens=out_tok,
                wall_clock_s=end_time - start_time,
                cost_usd=cost if cost else None,
            )]

        # Backfill tokens from result when turns have zero tokens
        if turns and in_tok > 0 and out_tok > 0:
            total_turn_in = sum(t.input_tokens for t in turns)
            total_turn_out = sum(t.output_tokens for t in turns)
            if total_turn_in == 0 and total_turn_out == 0:
                turns[0].input_tokens = in_tok
                turns[0].output_tokens = out_tok
                turns[0].wall_clock_s = (
                    turns[0].wall_clock_s or (end_time - start_time)
                )
                if cost and turns[0].cost_usd is None:
                    turns[0].cost_usd = cost

        # Compute cost for turns missing it
        for turn in turns:
            if turn.cost_usd is None and (
                turn.input_tokens > 0 or turn.output_tokens > 0
            ):
                from openjarvis.evals.core.pricing import compute_turn_cost
                turn.cost_usd = compute_turn_cost(
                    model, turn.input_tokens, turn.output_tokens
                )

        # Query-level energy from telemetry window
        query_gpu_energy = _compute_energy_delta(readings, "gpu_energy_j")
        query_cpu_energy = _compute_energy_delta(readings, "cpu_energy_j")
        query_gpu_power_avg = _compute_power_avg(readings, "gpu_power_w")
        query_cpu_power_avg = _compute_power_avg(readings, "cpu_power_w")

        # Extract MBU from telemetry readings
        mbu_values = [
            getattr(s, "gpu_memory_bandwidth_utilization_pct", None)
            for s in readings
        ]
        mbu_values = [
            v for v in mbu_values
            if v is not None and v >= 0
        ]
        query_mbu_avg = (
            statistics.mean(mbu_values) if mbu_values else None
        )
        query_mbu_max = max(mbu_values) if mbu_values else None

        trace = QueryTrace(
            query_id=query_id,
            workload_type=str(workload_type),
            query_text=record.problem,
            response_text=response_text,
            turns=turns,
            total_wall_clock_s=end_time - start_time,
            completed=True,
            query_gpu_energy_joules=query_gpu_energy,
            query_cpu_energy_joules=query_cpu_energy,
            query_gpu_power_avg_watts=query_gpu_power_avg,
            query_cpu_power_avg_watts=query_cpu_power_avg,
            is_resolved=record.metadata.get("is_resolved"),
            query_mbu_avg_pct=query_mbu_avg,
            query_mbu_max_pct=query_mbu_max,
        )

        # Correlate energy with trace
        trace = self._correlate_energy(trace, readings)

        return trace

    @staticmethod
    def _action_energy_from_readings(
        readings: list[Any],
        start_s: float,
        end_s: float,
    ) -> dict[str, Optional[float]]:
        """Compute energy for a time span from telemetry readings.

        Events use ``time.time()`` (epoch seconds); telemetry samples use
        ``time.time_ns()`` (epoch nanoseconds).  Convert and filter.
        """
        start_ns = int(start_s * 1e9)
        end_ns = int(end_s * 1e9)
        window = [
            r for r in readings
            if start_ns <= r.timestamp_ns <= end_ns
        ]
        gpu_energy = _compute_energy_delta(window, "gpu_energy_j")
        cpu_energy = _compute_energy_delta(window, "cpu_energy_j")
        avg_gpu_power = _compute_power_avg(window, "gpu_power_w")
        avg_cpu_power = _compute_power_avg(window, "cpu_power_w")
        return {
            "gpu_energy_joules": gpu_energy,
            "cpu_energy_joules": cpu_energy,
            "avg_gpu_power_watts": avg_gpu_power,
            "avg_cpu_power_watts": avg_cpu_power,
        }

    def _build_turn_traces(
        self,
        events: list[AgentEvent],
        readings: list[Any],
    ) -> list[TurnTrace]:
        """Build TurnTrace objects from recorded events."""
        turns: list[TurnTrace] = []
        current_turn_index = 0
        current_turn_start: Optional[float] = None
        current_tools: list[str] = []
        current_tool_latencies: dict[str, float] = {}
        current_tool_calls: list[dict[str, Any]] = []
        current_tool_args: dict[str, Any] = {}
        tool_start_times: dict[str, float] = {}
        input_tokens = 0
        output_tokens = 0
        # Collect per-action time spans for energy attribution
        current_action_spans: list[dict[str, Any]] = []

        for event in events:
            etype = event.event_type

            if etype == EventType.LM_INFERENCE_START:
                current_turn_start = event.timestamp

            elif etype == EventType.LM_INFERENCE_END:
                wall_clock = 0.0
                if current_turn_start is not None:
                    wall_clock = event.timestamp - current_turn_start
                    current_action_spans.append({
                        "action_type": "lm_inference",
                        "start_s": current_turn_start,
                        "end_s": event.timestamp,
                        "duration_s": wall_clock,
                    })

                input_tokens = event.metadata.get("prompt_tokens", 0)
                output_tokens = event.metadata.get("completion_tokens", 0)

                # Compute per-action energy if readings available
                action_breakdown = None
                if readings and current_action_spans:
                    action_breakdown = []
                    for span in current_action_spans:
                        energy = self._action_energy_from_readings(
                            readings, span["start_s"], span["end_s"],
                        )
                        action_breakdown.append({
                            "action_type": span["action_type"],
                            "duration_s": span["duration_s"],
                            **energy,
                        })

                turn = TurnTrace(
                    turn_index=current_turn_index,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    tools_called=list(current_tools),
                    tool_latencies_s=dict(current_tool_latencies),
                    tool_calls=list(current_tool_calls),
                    wall_clock_s=wall_clock,
                    action_energy_breakdown=action_breakdown,
                )
                turns.append(turn)

                current_turn_index += 1
                current_turn_start = None
                current_tools = []
                current_tool_latencies = {}
                current_tool_calls = []
                current_tool_args = {}
                current_action_spans = []
                input_tokens = 0
                output_tokens = 0

            elif etype == EventType.TOOL_CALL_START:
                tool_name = event.metadata.get("tool", "unknown")
                tool_start_times[tool_name] = event.timestamp
                current_tool_args[tool_name] = event.metadata.get("arguments", {})

            elif etype == EventType.TOOL_CALL_END:
                tool_name = event.metadata.get("tool", "unknown")
                current_tools.append(tool_name)
                current_tool_calls.append({
                    "name": tool_name,
                    "arguments": current_tool_args.pop(tool_name, {}),
                    "result": event.metadata.get("result", ""),
                })
                start_ts = tool_start_times.pop(tool_name, None)
                if start_ts is not None:
                    duration = event.timestamp - start_ts
                    current_tool_latencies[tool_name] = duration
                    current_action_spans.append({
                        "action_type": f"tool_call:{tool_name}",
                        "start_s": start_ts,
                        "end_s": event.timestamp,
                        "duration_s": duration,
                    })

        # Synthetic turn if events but no complete LM_START/END pair
        if not turns and events:
            turns.append(
                TurnTrace(
                    turn_index=0,
                    tools_called=current_tools,
                    tool_latencies_s=current_tool_latencies,
                    tool_calls=list(current_tool_calls),
                )
            )

        return turns

    def _correlate_energy(
        self,
        trace: QueryTrace,
        readings: list[Any],
    ) -> QueryTrace:
        """Distribute energy across turns proportionally by wall clock time.

        Only runs when per-turn energy was not already populated from events.
        """
        if not readings or not trace.turns:
            return trace

        has_turn_energy = any(
            t.gpu_energy_joules is not None for t in trace.turns
        )
        if has_turn_energy:
            return trace

        total_gpu_energy = _compute_energy_delta(readings, "gpu_energy_j")
        total_cpu_energy = _compute_energy_delta(readings, "cpu_energy_j")

        total_wall = sum(t.wall_clock_s for t in trace.turns)
        if total_wall > 0:
            for turn in trace.turns:
                fraction = turn.wall_clock_s / total_wall
                if total_gpu_energy is not None:
                    turn.gpu_energy_joules = total_gpu_energy * fraction
                if total_cpu_energy is not None:
                    turn.cpu_energy_joules = total_cpu_energy * fraction

        return trace

    def _save_query_artifacts(
        self,
        index: int,
        record: Any,
        trace: QueryTrace,
    ) -> None:
        """Save per-query artifacts to structured subdirectories."""
        assert self._run_dir is not None
        instance_id = record.metadata.get("instance_id", record.record_id)
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", str(instance_id))[:80]
        query_dir = self._run_dir / "artifacts" / f"q{index:04d}_{slug}"
        query_dir.mkdir(parents=True, exist_ok=True)

        (query_dir / "response.txt").write_text(
            trace.response_text or "", encoding="utf-8"
        )

        meta: dict[str, object] = {
            "query_id": trace.query_id,
            "instance_id": str(instance_id),
            "completed": trace.completed,
            "timed_out": trace.timed_out,
            "wall_clock_s": trace.total_wall_clock_s,
            "num_turns": trace.num_turns,
        }
        for key in (
            "repo", "base_commit", "dataset_name",
            "is_resolved", "test_results",
        ):
            val = record.metadata.get(key)
            if val is not None:
                meta[key] = val
        (query_dir / "metadata.json").write_text(
            json.dumps(meta, indent=2, default=str), encoding="utf-8"
        )

        patch = _extract_patch(trace.response_text or "")
        if patch:
            (query_dir / "patch.diff").write_text(patch, encoding="utf-8")

    @property
    def traces(self) -> list[QueryTrace]:
        """Return collected traces."""
        return list(self._traces)


__all__ = ["AgenticRunner"]
