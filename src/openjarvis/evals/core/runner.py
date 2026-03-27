"""EvalRunner — parallel execution of evaluation samples.

Supports two modes:
- **Parallel mode** (default): Samples processed concurrently via ThreadPoolExecutor.
- **Episode mode** (``episode_mode=True``): Samples processed sequentially within
  episodes, with in-context example injection from prior successful completions.
  Required for lifelong-learning benchmarks like LifelongAgentBench.

When a dataset provides ``create_task_env()`` returning a ``TaskEnvironment``,
samples are evaluated via multi-turn interactive loops instead of single-shot
generation — matching benchmarks that require agent-environment interaction.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import re
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.export import _hardware_info_dict
from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.tracker import ResultTracker
from openjarvis.evals.core.types import (
    EvalRecord,
    EvalResult,
    MetricStats,
    RunConfig,
    RunSummary,
)

try:
    from openjarvis.telemetry.efficiency import compute_efficiency
except ImportError:  # pragma: no cover
    compute_efficiency = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return _THINK_TAG_RE.sub("", text).strip()


class EvalRunner:
    """Runs an evaluation benchmark with parallel sample execution."""

    def __init__(
        self,
        config: RunConfig,
        dataset: DatasetProvider,
        backend: InferenceBackend,
        scorer: Scorer,
        trackers: Optional[List[ResultTracker]] = None,
    ) -> None:
        self._config = config
        self._dataset = dataset
        self._backend = backend
        self._scorer = scorer
        self._trackers: List[ResultTracker] = trackers or []
        self._results: List[EvalResult] = []
        self._output_file: Optional[Any] = None

    @property
    def results(self) -> List[EvalResult]:
        """Return a copy of collected evaluation results."""
        return list(self._results)

    def run(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> RunSummary:
        """Execute the evaluation and return a summary.

        Args:
            progress_callback: Optional ``(completed, total)`` callback invoked
                after each sample completes, useful for driving progress bars.
        """
        cfg = self._config
        started_at = time.time()

        self._dataset.load(
            max_samples=cfg.max_samples,
            split=cfg.dataset_split,
            seed=cfg.seed,
        )

        # Auto-enable episode_mode when the dataset *overrides*
        # iter_episodes() (i.e. it is a lifelong/sequential benchmark like
        # LifelongAgentBench).  The base DatasetProvider always defines a
        # default iter_episodes() that wraps each record in its own episode,
        # so hasattr() is always True — we must check for a real override.
        from openjarvis.evals.core.dataset import DatasetProvider as _DP

        try:
            _overrides_episodes = (
                type(self._dataset).iter_episodes is not _DP.iter_episodes
            )
        except AttributeError:
            _overrides_episodes = False
        if not cfg.episode_mode and _overrides_episodes:
            LOGGER.info(
                "%s requires sequential episode processing — "
                "auto-enabling episode_mode.",
                cfg.benchmark,
            )
            cfg = dataclasses.replace(cfg, episode_mode=True)
            self._config = cfg

        # Detect if dataset provides task environments (e.g. PinchBench)
        try:
            self._has_task_env = (
                type(self._dataset).create_task_env is not _DP.create_task_env
            )
        except AttributeError:
            self._has_task_env = False

        records = list(self._dataset.iter_records())
        LOGGER.info(
            "Running %s: %d samples, backend=%s, model=%s, workers=%d, episode_mode=%s",
            cfg.benchmark,
            len(records),
            cfg.backend,
            cfg.model,
            cfg.max_workers,
            cfg.episode_mode,
        )

        # --- Warmup phase (discard results) ---
        warmup_count = cfg.warmup_samples
        if warmup_count > 0 and records:
            warmup_records = records[:warmup_count]
            for rec in warmup_records:
                self._process_one(rec)
            LOGGER.info("Warmup complete: %d samples discarded", len(warmup_records))

        # Open output file for incremental JSONL writing
        output_path = self._resolve_output_path()
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._output_file = open(output_path, "w")

        # Notify trackers of run start
        for tracker in self._trackers:
            try:
                tracker.on_run_start(cfg)
            except Exception as exc:
                LOGGER.warning(
                    "Tracker %s.on_run_start failed: %s",
                    type(tracker).__name__,
                    exc,
                )

        total = len(records)
        try:
            if cfg.episode_mode:
                self._run_episode_mode(records, progress_callback, total)
            elif self._has_task_env:
                # Task environments (PinchBench etc.) change CWD —
                # must process sequentially for thread safety.
                for record in records:
                    result = self._process_one(record)
                    self._results.append(result)
                    self._flush_result(result)
                    if progress_callback is not None:
                        progress_callback(len(self._results), total)
            else:
                with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
                    futures = {pool.submit(self._process_one, r): r for r in records}
                    for future in as_completed(futures):
                        result = future.result()
                        self._results.append(result)
                        self._flush_result(result)
                        if progress_callback is not None:
                            progress_callback(len(self._results), total)
        finally:
            if self._output_file:
                self._output_file.close()
                self._output_file = None

        ended_at = time.time()
        summary = self._compute_summary(records, started_at, ended_at)

        # Notify trackers of summary and run end
        for tracker in self._trackers:
            try:
                tracker.on_summary(summary)
            except Exception as exc:
                LOGGER.warning(
                    "Tracker %s.on_summary failed: %s",
                    type(tracker).__name__,
                    exc,
                )
            try:
                tracker.on_run_end()
            except Exception as exc:
                LOGGER.warning(
                    "Tracker %s.on_run_end failed: %s",
                    type(tracker).__name__,
                    exc,
                )

        # Write summary JSON alongside JSONL
        traces_dir: Optional[Path] = None
        if output_path:
            summary_path = output_path.with_suffix(".summary.json")
            with open(summary_path, "w") as f:
                json.dump(_summary_to_dict(summary), f, indent=2)
            LOGGER.info("Results written to %s", output_path)
            LOGGER.info("Summary written to %s", summary_path)

            # Write per-trace data
            traces_dir = self._write_traces(output_path)

        # Attach paths to summary for callers (e.g. CLI display)
        summary._output_path = output_path  # type: ignore[attr-defined]
        summary._traces_dir = traces_dir  # type: ignore[attr-defined]

        return summary

    def _write_traces(self, output_path: Path) -> Optional[Path]:
        """Write per-sample trace data to a traces subdirectory."""
        if not self._results:
            return None
        cfg = self._config
        model_slug = cfg.model.replace("/", "-").replace(":", "-")
        traces_dir = output_path.parent / "traces" / f"{cfg.benchmark}_{model_slug}"
        traces_dir.mkdir(parents=True, exist_ok=True)
        with open(traces_dir / "traces.jsonl", "w") as f:
            for result in self._results:
                f.write(json.dumps(_result_to_trace_dict(result), default=str) + "\n")
        LOGGER.info("Traces written to %s", traces_dir)
        return traces_dir

    def _process_one(self, record: EvalRecord) -> EvalResult:
        """Process a single evaluation sample."""
        cfg = self._config
        try:
            gen_kwargs: dict = dict(
                model=cfg.model,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            if cfg.system_prompt:
                gen_kwargs["system"] = cfg.system_prompt

            if getattr(self, "_has_task_env", False):
                from contextlib import nullcontext

                task_env = self._dataset.create_task_env(record)
                ctx = task_env if task_env is not None else nullcontext()
                with ctx:
                    full = self._backend.generate_full(
                        record.problem,
                        **gen_kwargs,
                    )
                    full = full or {}
                    all_tool_results = list(
                        full.get(
                            "tool_results",
                            [],
                        )
                    )

                    # Multi-session: execute remaining sessions
                    sessions = record.metadata.get("sessions", [])
                    if record.metadata.get("multi_session") and len(sessions) > 1:
                        for session in sessions[1:]:
                            prompt = session.get("prompt", "")
                            if not prompt:
                                continue
                            sfull = self._backend.generate_full(
                                prompt,
                                **gen_kwargs,
                            )
                            sfull = sfull or {}
                            all_tool_results.extend(
                                sfull.get("tool_results", []),
                            )

                    record.metadata["tool_results"] = all_tool_results
                    # Score INSIDE context so workspace files still exist
                    content = full.get("content", "")
                    is_correct, scoring_meta = self._scorer.score(
                        record,
                        content,
                    )
            else:
                full = self._backend.generate_full(
                    record.problem,
                    **gen_kwargs,
                )
                full = full or {}
                content = full.get("content", "")
                is_correct, scoring_meta = self._scorer.score(
                    record,
                    content,
                )

            usage = full.get("usage", {})
            latency = full.get("latency_seconds", 0.0)
            cost = full.get("cost_usd", 0.0)

            energy_j = full.get("energy_joules", 0.0)
            power_w = full.get("power_watts", 0.0)
            throughput = full.get("throughput_tok_per_sec", 0.0)
            accuracy_score = 1.0 if is_correct else 0.0

            # Compute IPW and IPJ
            ipw = (accuracy_score / power_w) if power_w > 0 else 0.0
            ipj = (accuracy_score / energy_j) if energy_j > 0 else 0.0

            # Compute MFU/MBU if efficiency module available and we have
            # model params from config metadata
            mfu = 0.0
            mbu = 0.0
            if compute_efficiency is not None and throughput > 0:
                model_meta = cfg.metadata or {}
                param_b = model_meta.get("param_count_b", 0.0)
                active_b = model_meta.get("active_params_b")
                gpu_tflops = model_meta.get("gpu_peak_tflops", 0.0)
                gpu_bw = model_meta.get("gpu_peak_bandwidth_gb_s", 0.0)
                num_gpus = model_meta.get("num_gpus", 1)
                if param_b > 0 and gpu_tflops > 0:
                    eff = compute_efficiency(
                        param_count_b=param_b,
                        active_params_b=active_b,
                        gpu_peak_tflops=gpu_tflops,
                        gpu_peak_bandwidth_gb_s=gpu_bw,
                        tokens_per_sec=throughput,
                        num_gpus=num_gpus,
                        energy_joules=energy_j,
                        accuracy=accuracy_score,
                    )
                    mfu = eff.mfu_pct
                    mbu = eff.mbu_pct

            # Extract derived and ITL metrics from _telemetry dict
            _telem = full.get("_telemetry", {})
            energy_per_out_tok = _telem.get("energy_per_output_token_joules", 0.0)
            throughput_per_w = _telem.get("throughput_per_watt", 0.0)
            mean_itl = _telem.get("mean_itl_ms", 0.0)

            return EvalResult(
                record_id=record.record_id,
                model_answer=content,
                is_correct=is_correct,
                score=1.0 if is_correct else (0.0 if is_correct is not None else None),
                latency_seconds=latency,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                cost_usd=cost,
                scoring_metadata=scoring_meta,
                ttft=full.get("ttft", 0.0),
                energy_joules=energy_j,
                power_watts=power_w,
                gpu_utilization_pct=full.get("gpu_utilization_pct", 0.0),
                throughput_tok_per_sec=throughput,
                mfu_pct=mfu,
                mbu_pct=mbu,
                ipw=ipw,
                ipj=ipj,
                energy_per_output_token_joules=energy_per_out_tok,
                throughput_per_watt=throughput_per_w,
                mean_itl_ms=mean_itl,
            )
        except Exception as exc:
            LOGGER.error("Error processing %s: %s", record.record_id, exc)
            return EvalResult(
                record_id=record.record_id,
                model_answer="",
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Episode mode: sequential processing with lifelong learning
    # ------------------------------------------------------------------

    # Max prior examples to inject (FIFO eviction), matching original default
    _MAX_PRIOR_EXAMPLES = 3

    def _run_episode_mode(
        self,
        records: List[EvalRecord],
        progress_callback: Optional[Callable[[int, int], None]],
        total: int,
    ) -> None:
        """Process samples sequentially within episodes.

        Mirrors the original LifelongAgentBench ``PreviousSampleUtilizationCallback``:
        successful completions are accumulated and injected as in-context
        examples into subsequent tasks within the same episode.

        The original injects the full interaction history (question + all
        agent/environment exchanges) from prior successful sessions, not
        just problem/answer summaries.  We replicate this by storing
        the full message history for each successful task.
        """
        # Only treat a dataset as having interactive environments if it actually
        # overrides create_task_env.  The DatasetProvider base class provides a
        # default implementation that returns None, so hasattr() is always True —
        # we must check for a real override to avoid calling env.reset() on None.
        from openjarvis.evals.core.dataset import DatasetProvider

        has_task_env = (
            type(self._dataset).create_task_env is not DatasetProvider.create_task_env
        )

        for episode in self._dataset.iter_episodes():
            successful_examples: List[Dict[str, Any]] = []

            for record in episode:
                if has_task_env:
                    result = self._process_interactive(
                        record,
                        successful_examples,
                    )
                else:
                    # Inject prior examples into prompt, then single-shot
                    augmented = self._inject_examples(
                        record,
                        successful_examples,
                    )
                    result = self._process_one(augmented)

                self._results.append(result)
                self._flush_result(result)

                # Accumulate successful examples for lifelong learning.
                # Store the full interaction history when available.
                if result.is_correct:
                    example: Dict[str, Any] = {
                        "problem": record.problem,
                        "answer": result.model_answer,
                    }
                    # Attach full interaction history if recorded
                    interaction = (
                        result.scoring_metadata.get(
                            "_interaction_history",
                        )
                        if result.scoring_metadata
                        else None
                    )
                    if interaction:
                        example["interaction_history"] = interaction
                    successful_examples.append(example)
                    # FIFO eviction matching original's utilized_sample_count
                    if len(successful_examples) > self._MAX_PRIOR_EXAMPLES:
                        successful_examples.pop(0)

                if progress_callback is not None:
                    progress_callback(len(self._results), total)

    def _inject_examples(
        self,
        record: EvalRecord,
        examples: List[Dict[str, Any]],
    ) -> EvalRecord:
        """Create a copy of the record with prior examples prepended.

        Matches the original's ``PreviousSampleUtilizationCallback``
        which injects the full interaction history (question + all
        agent/environment exchanges) from prior successful tasks.
        """
        if not examples:
            return record

        example_text = "## Previously Completed Tasks\n\n"
        for i, ex in enumerate(examples, 1):
            example_text += f"### Example {i}\n"
            # Use full interaction history if available (matching original)
            history = ex.get("interaction_history")
            if history and isinstance(history, list):
                # Format the full multi-turn exchange
                for msg in history:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "system":
                        continue
                    label = "Agent" if role == "assistant" else "User"
                    example_text += f"{label}: {content}\n"
                example_text += "\n"
            else:
                # Fallback: problem + answer summary
                example_text += (
                    f"Task: {ex['problem'][:800]}\nSolution: {ex['answer'][:800]}\n\n"
                )
        example_text += "## Current Task\n\n"

        return EvalRecord(
            record_id=record.record_id,
            problem=example_text + record.problem,
            reference=record.reference,
            category=record.category,
            subject=record.subject,
            metadata=record.metadata,
        )

    # ------------------------------------------------------------------
    # Interactive multi-turn processing
    # ------------------------------------------------------------------

    _MAX_INTERACTIVE_TURNS_DEFAULT = 15

    def _process_interactive(
        self,
        record: EvalRecord,
        prior_examples: List[Dict[str, Any]],
    ) -> EvalResult:
        """Process a record via multi-turn environment interaction.

        Used when the dataset provides ``create_task_env()``, e.g. for
        LifelongAgentBench where agents must interact with DB/KG/OS
        environments across multiple turns.

        The full interaction history is recorded in scoring_metadata so
        it can be injected into subsequent tasks in the same episode,
        matching the original's ``PreviousSampleUtilizationCallback``.
        """
        cfg = self._config
        env = None
        total_latency = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        all_responses: List[str] = []

        try:
            env = self._dataset.create_task_env(record)
            env.reset(record)

            # Build system prompt from record (first part before task)
            system_prompt = ""
            problem_text = record.problem
            # Split on "## Task" or "## Question" to separate system from task
            for sep in ("## Task\n", "## Question\n", "## Database Schema\n"):
                if sep in problem_text:
                    idx = problem_text.index(sep)
                    system_prompt = problem_text[:idx].strip()
                    break

            # Build conversation with optional prior examples
            messages: List[Dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Inject prior examples (lifelong learning) — use full
            # interaction history when available, matching the original's
            # PreviousSampleUtilizationCallback which replays the complete
            # chat history from prior successful sessions.
            if prior_examples:
                examples_text = "Here are examples of previously completed tasks:\n\n"
                for i, ex in enumerate(prior_examples, 1):
                    history = ex.get("interaction_history")
                    if history and isinstance(history, list):
                        # Full interaction replay (original format)
                        examples_text += f"Example {i}:\n"
                        for msg in history:
                            role = msg.get("role", "user")
                            content = msg.get("content", "")
                            if role == "system":
                                continue
                            label = "Agent" if role == "assistant" else "User"
                            examples_text += f"{label}: {content}\n"
                        examples_text += "\n"
                    else:
                        # Fallback: problem + answer summary
                        examples_text += (
                            f"Example {i}:\n"
                            f"Task: {ex['problem'][:800]}\n"
                            f"Solution: {ex['answer'][:800]}\n\n"
                        )
                messages.append({"role": "user", "content": examples_text})
                messages.append(
                    {
                        "role": "assistant",
                        "content": "I've reviewed the examples. Ready.",
                    }
                )

            # Initial task message — always use the full problem text which
            # contains the system prompt, schema, AND task instruction.
            # env.reset() is called for side effects (DB init, container
            # start) but its return value (schema-only observation) is
            # intentionally NOT used as the prompt because record.problem
            # already has everything the agent needs.
            task_content = problem_text
            messages.append({"role": "user", "content": task_content})

            # Use environment's max_turns if available, else default
            max_turns = (
                env.max_turns
                if hasattr(env, "max_turns")
                else self._MAX_INTERACTIVE_TURNS_DEFAULT
            )

            for turn in range(max_turns):
                # Format conversation as prompt for the backend
                prompt = self._format_messages_as_prompt(messages)

                full = self._backend.generate_full(
                    prompt,
                    model=cfg.model,
                    system=system_prompt,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                )
                content = full.get("content", "")
                usage = full.get("usage", {})
                total_latency += full.get("latency_seconds", 0.0)
                total_prompt_tokens += usage.get("prompt_tokens", 0)
                total_completion_tokens += usage.get("completion_tokens", 0)
                total_cost += full.get("cost_usd", 0.0)
                all_responses.append(content)

                # Strip <think> tags before parsing actions
                cleaned = _strip_think_tags(content)
                messages.append({"role": "assistant", "content": cleaned})

                # Step the environment
                observation, is_done = env.step(cleaned)
                messages.append({"role": "user", "content": observation})

                if is_done:
                    break

            # Evaluate
            is_correct, scoring_meta = env.evaluate()
            scoring_meta["num_turns"] = len(all_responses)
            scoring_meta["interactive"] = True
            # Store full interaction history for lifelong example injection.
            # Filter out system messages to save space.
            scoring_meta["_interaction_history"] = [
                msg for msg in messages if msg.get("role") != "system"
            ]

            return EvalResult(
                record_id=record.record_id,
                model_answer="\n---\n".join(all_responses),
                is_correct=is_correct,
                score=1.0 if is_correct else (0.0 if is_correct is not None else None),
                latency_seconds=total_latency,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                cost_usd=total_cost,
                scoring_metadata=scoring_meta,
            )
        except Exception as exc:
            LOGGER.error(
                "Interactive processing failed for %s: %s",
                record.record_id,
                exc,
            )
            return EvalResult(
                record_id=record.record_id,
                model_answer="",
                error=str(exc),
                scoring_metadata={"interactive": True, "error": str(exc)},
            )
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass

    @staticmethod
    def _format_messages_as_prompt(messages: List[Dict[str, str]]) -> str:
        """Format a message list as a single prompt string.

        Uses a clear role-labeled format that works with most LLMs when
        passed as a user prompt via the backend.
        """
        parts: List[str] = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                # System prompt handled separately via backend's system param
                continue
            elif role == "user":
                parts.append(f"[User]\n{content}")
            elif role == "assistant":
                parts.append(f"[Assistant]\n{content}")
        parts.append("[Assistant]")  # Prompt the next assistant turn
        return "\n\n".join(parts)

    def _flush_result(self, result: EvalResult) -> None:
        """Append a single result to the output JSONL file."""
        if not self._output_file:
            return
        record_dict = {
            "record_id": result.record_id,
            "benchmark": self._config.benchmark,
            "model": self._config.model,
            "backend": self._config.backend,
            "model_answer": result.model_answer,
            "is_correct": result.is_correct,
            "score": result.score,
            "latency_seconds": result.latency_seconds,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost_usd": result.cost_usd,
            "error": result.error,
            "scoring_metadata": result.scoring_metadata,
            "ttft": result.ttft,
            "energy_joules": result.energy_joules,
            "power_watts": result.power_watts,
            "gpu_utilization_pct": result.gpu_utilization_pct,
            "throughput_tok_per_sec": result.throughput_tok_per_sec,
            "mfu_pct": result.mfu_pct,
            "mbu_pct": result.mbu_pct,
            "ipw": result.ipw,
            "ipj": result.ipj,
            "energy_per_output_token_joules": result.energy_per_output_token_joules,
            "throughput_per_watt": result.throughput_per_watt,
            "mean_itl_ms": result.mean_itl_ms,
        }
        try:
            line = json.dumps(record_dict, default=str)
        except Exception as exc:
            LOGGER.error(
                "Failed to serialize result %s to JSON: %s — writing error record",
                result.record_id,
                exc,
            )
            line = json.dumps(
                {
                    "record_id": result.record_id,
                    "benchmark": self._config.benchmark,
                    "model": self._config.model,
                    "is_correct": result.is_correct,
                    "error": f"serialization_error: {exc}",
                }
            )
        self._output_file.write(line + "\n")
        self._output_file.flush()

        # Notify trackers of each result
        for tracker in self._trackers:
            try:
                tracker.on_result(result, self._config)
            except Exception as exc:
                LOGGER.warning(
                    "Tracker %s.on_result failed: %s",
                    type(tracker).__name__,
                    exc,
                )

    def _resolve_output_path(self) -> Optional[Path]:
        """Determine the output file path."""
        if self._config.output_path:
            return Path(self._config.output_path)
        # Auto-generate under results/ based on benchmark + model
        model_slug = self._config.model.replace("/", "-").replace(":", "-")
        name = f"{self._config.benchmark}_{model_slug}.jsonl"
        return Path("results") / name

    def _compute_summary(
        self,
        records: List[EvalRecord],
        started_at: float,
        ended_at: float,
    ) -> RunSummary:
        """Compute aggregate statistics from results."""
        cfg = self._config
        results = self._results

        scored = [r for r in results if r.is_correct is not None]
        correct = [r for r in scored if r.is_correct]
        errors = [r for r in results if r.error]

        latencies = [r.latency_seconds for r in results if r.latency_seconds > 0]
        mean_latency = sum(latencies) / len(latencies) if latencies else 0.0
        total_cost = sum(r.cost_usd for r in results)

        # Per-subject breakdown
        record_map = {r.record_id: r for r in records}
        subject_groups: Dict[str, List[EvalResult]] = defaultdict(list)
        for r in results:
            rec = record_map.get(r.record_id)
            subj = rec.subject if rec and rec.subject else "general"
            subject_groups[subj].append(r)

        per_subject: Dict[str, Dict[str, float]] = {}
        for subj, subj_results in sorted(subject_groups.items()):
            subj_scored = [r for r in subj_results if r.is_correct is not None]
            subj_correct = [r for r in subj_scored if r.is_correct]
            subj_acc = len(subj_correct) / len(subj_scored) if subj_scored else 0.0
            per_subject[subj] = {
                "accuracy": round(subj_acc, 4),
                "total": float(len(subj_results)),
                "scored": float(len(subj_scored)),
                "correct": float(len(subj_correct)),
            }

        # Determine category from records
        categories = {r.category for r in records}
        category = categories.pop() if len(categories) == 1 else cfg.benchmark

        accuracy = len(correct) / len(scored) if scored else 0.0

        # Compute MetricStats for each metric
        accuracy_vals = [1.0 if r.is_correct else 0.0 for r in scored]
        latency_vals = [r.latency_seconds for r in results if r.latency_seconds > 0]
        ttft_vals = [r.ttft for r in results if r.ttft > 0]
        energy_vals = [r.energy_joules for r in results if r.energy_joules > 0]
        power_vals = [r.power_watts for r in results if r.power_watts > 0]
        gpu_util_vals = [
            r.gpu_utilization_pct for r in results if r.gpu_utilization_pct > 0
        ]
        throughput_vals = [
            r.throughput_tok_per_sec for r in results if r.throughput_tok_per_sec > 0
        ]
        mfu_vals = [r.mfu_pct for r in results if r.mfu_pct > 0]
        mbu_vals = [r.mbu_pct for r in results if r.mbu_pct > 0]
        ipw_vals = [r.ipw for r in results if r.ipw > 0]
        ipj_vals = [r.ipj for r in results if r.ipj > 0]
        epot_vals = [
            r.energy_per_output_token_joules
            for r in results
            if r.energy_per_output_token_joules > 0
        ]
        tpw_vals = [r.throughput_per_watt for r in results if r.throughput_per_watt > 0]
        itl_vals = [r.mean_itl_ms for r in results if r.mean_itl_ms > 0]
        input_tok_vals = [r.prompt_tokens for r in results if r.prompt_tokens > 0]
        output_tok_vals = [
            r.completion_tokens for r in results if r.completion_tokens > 0
        ]

        total_energy = sum(r.energy_joules for r in results)
        total_input_tokens = sum(r.prompt_tokens for r in results)
        total_output_tokens = sum(r.completion_tokens for r in results)
        avg_power = statistics.mean(power_vals) if power_vals else 0.0

        # Compute efficiency section
        efficiency_dict: Dict[str, Any] = {
            "accuracy": round(accuracy, 4),
            "total_energy_joules": round(total_energy, 6),
            "avg_power_watts": round(avg_power, 4),
            "ipj": (round(accuracy / total_energy, 6) if total_energy > 0 else None),
            "ipw": (round(accuracy / avg_power, 6) if avg_power > 0 else None),
        }

        # Compute normalized statistics (trim 5% outliers by latency)
        normalized_stats, normalized_eff = _compute_normalized_stats(
            results,
            accuracy,
        )

        return RunSummary(
            benchmark=cfg.benchmark,
            category=category,
            backend=cfg.backend,
            model=cfg.model,
            total_samples=len(results),
            scored_samples=len(scored),
            correct=len(correct),
            accuracy=round(accuracy, 4),
            errors=len(errors),
            mean_latency_seconds=round(mean_latency, 4),
            total_cost_usd=round(total_cost, 6),
            per_subject=per_subject,
            started_at=started_at,
            ended_at=ended_at,
            accuracy_stats=_metric_stats(accuracy_vals),
            latency_stats=_metric_stats(latency_vals),
            ttft_stats=_metric_stats(ttft_vals),
            energy_stats=_metric_stats(energy_vals),
            power_stats=_metric_stats(power_vals),
            gpu_utilization_stats=_metric_stats(gpu_util_vals),
            throughput_stats=_metric_stats(throughput_vals),
            mfu_stats=_metric_stats(mfu_vals),
            mbu_stats=_metric_stats(mbu_vals),
            ipw_stats=_metric_stats(ipw_vals),
            ipj_stats=_metric_stats(ipj_vals),
            energy_per_output_token_stats=_metric_stats(epot_vals),
            throughput_per_watt_stats=_metric_stats(tpw_vals),
            itl_stats=_metric_stats(itl_vals),
            input_token_stats=_metric_stats([float(v) for v in input_tok_vals]),
            output_token_stats=_metric_stats([float(v) for v in output_tok_vals]),
            total_energy_joules=round(total_energy, 6),
            warmup_samples_excluded=cfg.warmup_samples,
            avg_power_watts=round(avg_power, 4),
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            efficiency=efficiency_dict,
            normalized_statistics=normalized_stats,
            normalized_efficiency=normalized_eff,
        )


def _compute_normalized_stats(
    results: List[EvalResult],
    accuracy: float,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Compute stats after trimming top/bottom 5% outliers by latency.

    Returns (normalized_statistics, normalized_efficiency) or (None, None)
    if fewer than 4 results.
    """
    n = len(results)
    if n < 4:
        return None, None

    trim_count = max(1, math.floor(n * 0.05))
    sorted_results = sorted(results, key=lambda r: r.latency_seconds)
    trimmed = sorted_results[trim_count : n - trim_count]

    if not trimmed:
        return None, None

    # Recompute key metric stats on trimmed set
    t_scored = [r for r in trimmed if r.is_correct is not None]
    t_correct = [r for r in t_scored if r.is_correct]
    t_accuracy = len(t_correct) / len(t_scored) if t_scored else 0.0
    t_latency_vals = [r.latency_seconds for r in trimmed if r.latency_seconds > 0]
    t_energy_vals = [r.energy_joules for r in trimmed if r.energy_joules > 0]
    t_power_vals = [r.power_watts for r in trimmed if r.power_watts > 0]
    t_throughput_vals = [
        r.throughput_tok_per_sec for r in trimmed if r.throughput_tok_per_sec > 0
    ]
    t_mbu_vals = [r.mbu_pct for r in trimmed if r.mbu_pct > 0]

    norm_stats: Dict[str, Any] = {
        "_description": (
            f"Statistics recomputed after trimming {trim_count} outlier(s) "
            f"from each end by latency ({len(trimmed)}/{n} results kept)"
        ),
        "_outliers_removed": trim_count * 2,
        "accuracy": round(t_accuracy, 4),
        "latency_stats": _metric_stats_to_dict(_metric_stats(t_latency_vals)),
        "energy_stats": _metric_stats_to_dict(_metric_stats(t_energy_vals)),
        "power_stats": _metric_stats_to_dict(_metric_stats(t_power_vals)),
        "throughput_stats": _metric_stats_to_dict(
            _metric_stats(t_throughput_vals),
        ),
        "mbu_stats": _metric_stats_to_dict(_metric_stats(t_mbu_vals)),
    }

    t_total_energy = sum(r.energy_joules for r in trimmed)
    t_avg_power = statistics.mean(t_power_vals) if t_power_vals else 0.0
    norm_eff: Dict[str, Any] = {
        "accuracy": round(t_accuracy, 4),
        "total_energy_joules": round(t_total_energy, 6),
        "avg_power_watts": round(t_avg_power, 4),
        "ipj": (round(t_accuracy / t_total_energy, 6) if t_total_energy > 0 else None),
        "ipw": (round(t_accuracy / t_avg_power, 6) if t_avg_power > 0 else None),
    }

    return norm_stats, norm_eff


def _eval_percentile(data: list[float], p: float) -> float:
    """Compute the p-th percentile using linear interpolation."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def _metric_stats(values: List[float]) -> Optional[MetricStats]:
    """Compute MetricStats from a list of float values."""
    if not values:
        return None
    return MetricStats(
        mean=statistics.mean(values),
        median=statistics.median(values),
        min=min(values),
        max=max(values),
        std=statistics.stdev(values) if len(values) > 1 else 0.0,
        p90=_eval_percentile(values, 0.90),
        p95=_eval_percentile(values, 0.95),
        p99=_eval_percentile(values, 0.99),
    )


def _metric_stats_to_dict(ms: Optional[MetricStats]) -> Optional[Dict[str, float]]:
    """Convert MetricStats to a JSON-serializable dict."""
    if ms is None:
        return None
    return {
        "mean": ms.mean,
        "median": ms.median,
        "min": ms.min,
        "max": ms.max,
        "std": ms.std,
        "p90": ms.p90,
        "p95": ms.p95,
        "p99": ms.p99,
    }


def _summary_to_dict(s: RunSummary) -> Dict[str, Any]:
    """Convert a RunSummary to a JSON-serializable dict."""
    return {
        "hardware_info": _hardware_info_dict(),
        "benchmark": s.benchmark,
        "category": s.category,
        "backend": s.backend,
        "model": s.model,
        "total_samples": s.total_samples,
        "scored_samples": s.scored_samples,
        "correct": s.correct,
        "accuracy": s.accuracy,
        "errors": s.errors,
        "mean_latency_seconds": s.mean_latency_seconds,
        "total_cost_usd": s.total_cost_usd,
        "per_subject": s.per_subject,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "accuracy_stats": _metric_stats_to_dict(s.accuracy_stats),
        "latency_stats": _metric_stats_to_dict(s.latency_stats),
        "ttft_stats": _metric_stats_to_dict(s.ttft_stats),
        "energy_stats": _metric_stats_to_dict(s.energy_stats),
        "power_stats": _metric_stats_to_dict(s.power_stats),
        "gpu_utilization_stats": _metric_stats_to_dict(s.gpu_utilization_stats),
        "throughput_stats": _metric_stats_to_dict(s.throughput_stats),
        "mfu_stats": _metric_stats_to_dict(s.mfu_stats),
        "mbu_stats": _metric_stats_to_dict(s.mbu_stats),
        "ipw_stats": _metric_stats_to_dict(s.ipw_stats),
        "ipj_stats": _metric_stats_to_dict(s.ipj_stats),
        "energy_per_output_token_stats": _metric_stats_to_dict(
            s.energy_per_output_token_stats,
        ),
        "throughput_per_watt_stats": _metric_stats_to_dict(
            s.throughput_per_watt_stats,
        ),
        "itl_stats": _metric_stats_to_dict(s.itl_stats),
        "input_token_stats": _metric_stats_to_dict(s.input_token_stats),
        "output_token_stats": _metric_stats_to_dict(s.output_token_stats),
        "total_energy_joules": s.total_energy_joules,
        "warmup_samples_excluded": s.warmup_samples_excluded,
        "steady_state_reached": s.steady_state_reached,
        "energy_method": s.energy_method,
        "avg_power_watts": s.avg_power_watts,
        "total_input_tokens": s.total_input_tokens,
        "total_output_tokens": s.total_output_tokens,
        "efficiency": s.efficiency,
        "normalized_statistics": s.normalized_statistics,
        "normalized_efficiency": s.normalized_efficiency,
    }


def _result_to_trace_dict(result: EvalResult) -> Dict[str, Any]:
    """Convert an EvalResult to a full trace dict for per-sample export."""
    return {
        "record_id": result.record_id,
        "model_answer": result.model_answer,
        "is_correct": result.is_correct,
        "score": result.score,
        "latency_seconds": result.latency_seconds,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost_usd": result.cost_usd,
        "error": result.error,
        "scoring_metadata": result.scoring_metadata,
        "ttft": result.ttft,
        "energy_joules": result.energy_joules,
        "power_watts": result.power_watts,
        "gpu_utilization_pct": result.gpu_utilization_pct,
        "throughput_tok_per_sec": result.throughput_tok_per_sec,
        "mfu_pct": result.mfu_pct,
        "mbu_pct": result.mbu_pct,
        "ipw": result.ipw,
        "ipj": result.ipj,
        "energy_per_output_token_joules": result.energy_per_output_token_joules,
        "throughput_per_watt": result.throughput_per_watt,
        "mean_itl_ms": result.mean_itl_ms,
    }


__all__ = ["EvalRunner"]
