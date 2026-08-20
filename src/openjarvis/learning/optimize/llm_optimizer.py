"""LLM-based optimizer for OpenJarvis configuration tuning.

Uses a cloud LLM to propose optimal OpenJarvis configs, inspired by DSPy's
GEPA approach: textual feedback from execution traces rather than just scalar
rewards guides the optimizer toward better configurations.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from openjarvis.core.types import Trace
from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.types import RunSummary
from openjarvis.learning.optimize.types import (
    BenchmarkScore,
    SampleScore,
    SearchSpace,
    TrialConfig,
    TrialFeedback,
    TrialResult,
)

logger = logging.getLogger(__name__)


class LLMOptimizer:
    """Uses a cloud LLM to propose optimal OpenJarvis configs.

    Inspired by DSPy's GEPA: uses textual feedback from execution
    traces rather than just scalar rewards.
    """

    def __init__(
        self,
        search_space: SearchSpace,
        optimizer_model: str = "claude-sonnet-4-6",
        optimizer_backend: Optional[InferenceBackend] = None,
    ) -> None:
        self.search_space = search_space
        self.optimizer_model = optimizer_model
        self.optimizer_backend = optimizer_backend

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose_initial(self) -> TrialConfig:
        """Propose a reasonable starting config from the search space."""
        if self.optimizer_backend is None:
            raise ValueError("optimizer_backend is required to propose configurations")

        prompt = self._build_initial_prompt()
        response = self.optimizer_backend.generate(
            prompt,
            model=self.optimizer_model,
            system="You are an expert AI systems optimizer.",
            temperature=0.7,
            max_tokens=2048,
        )
        return self._parse_config_response(response)

    def propose_next(
        self,
        history: List[TrialResult],
        traces: Optional[List[Trace]] = None,
        frontier_ids: Optional[set] = None,
    ) -> TrialConfig:
        """Ask the LLM to propose the next config to evaluate."""
        if self.optimizer_backend is None:
            raise ValueError("optimizer_backend is required to propose configurations")

        prompt = self._build_propose_prompt(history, traces, frontier_ids=frontier_ids)
        response = self.optimizer_backend.generate(
            prompt,
            model=self.optimizer_model,
            system="You are an expert AI systems optimizer.",
            temperature=0.7,
            max_tokens=2048,
        )
        return self._parse_config_response(response)

    def analyze_trial(
        self,
        trial: TrialConfig,
        summary: RunSummary,
        traces: Optional[List[Trace]] = None,
        sample_scores: Optional[List[SampleScore]] = None,
        per_benchmark: Optional[List[BenchmarkScore]] = None,
    ) -> TrialFeedback:
        """Ask the LLM to analyze a completed trial. Returns structured feedback."""
        if self.optimizer_backend is None:
            raise ValueError("optimizer_backend is required to analyze trials")

        prompt = self._build_analyze_prompt(
            trial,
            summary,
            traces,
            sample_scores,
            per_benchmark,
        )
        response = self.optimizer_backend.generate(
            prompt,
            model=self.optimizer_model,
            system="You are an expert AI systems analyst.",
            temperature=0.3,
            max_tokens=2048,
        )
        return self._parse_feedback_response(response)

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_initial_prompt(self) -> str:
        """Construct the prompt for the initial config proposal."""
        lines: List[str] = []
        lines.append("You are optimizing an OpenJarvis AI system configuration.")
        lines.append("")
        lines.append(self.search_space.to_prompt_description())
        lines.append("## Objective")
        lines.append("Maximize accuracy while minimizing latency and cost.")
        lines.append("")
        lines.append("## Your Task")
        lines.append(
            "Propose an initial configuration that is a reasonable starting "
            "point for optimization. Choose sensible defaults that balance "
            "accuracy, latency, and cost."
        )
        lines.append("")
        lines.append("Return a JSON object inside a ```json code block with:")
        lines.append(
            '1. "params": dict of config params (dotted keys matching the search space)'
        )
        lines.append(
            '2. "reasoning": string explaining why this is a good '
            "starting configuration"
        )
        return "\n".join(lines)

    def _build_propose_prompt(
        self,
        history: List[TrialResult],
        traces: Optional[List[Trace]] = None,
        frontier_ids: Optional[set] = None,
    ) -> str:
        """Construct the full prompt for propose_next."""
        lines: List[str] = []
        lines.append("You are optimizing an OpenJarvis AI system configuration.")
        lines.append("")
        lines.append(self.search_space.to_prompt_description())

        lines.append("## Optimization History")
        if history:
            lines.append(self._format_history(history, frontier_ids=frontier_ids))
        else:
            lines.append("No trials have been run yet.")
        lines.append("")

        if traces:
            lines.append("## Recent Execution Traces")
            lines.append(self._format_traces(traces))
            lines.append("")

        lines.append("## Objective")
        lines.append("Maximize accuracy while minimizing latency and cost.")
        lines.append("")
        lines.append("## Your Task")
        lines.append(
            "Propose the next configuration to evaluate. Learn from "
            "previous trials to improve results."
        )
        lines.append("")
        lines.append("Return a JSON object inside a ```json code block with:")
        lines.append(
            '1. "params": dict of config params (dotted keys matching the search space)'
        )
        lines.append(
            '2. "reasoning": string explaining why this config should improve results'
        )
        return "\n".join(lines)

    def _build_analyze_prompt(
        self,
        trial: TrialConfig,
        summary: RunSummary,
        traces: Optional[List[Trace]] = None,
        sample_scores: Optional[List[SampleScore]] = None,
        per_benchmark: Optional[List[BenchmarkScore]] = None,
    ) -> str:
        """Construct the prompt for analyze_trial."""
        lines: List[str] = []
        lines.append("Analyze this OpenJarvis evaluation result.")
        lines.append("")

        lines.append("## Configuration")
        for key, value in sorted(trial.params.items()):
            lines.append(f"- {key}: {value}")
        if trial.reasoning:
            lines.append(f"\nOptimizer reasoning: {trial.reasoning}")
        lines.append("")

        # Per-benchmark breakdown (multi-benchmark mode)
        if per_benchmark:
            lines.append("## Per-Benchmark Results")
            total_weight = sum(b.weight for b in per_benchmark) or 1.0
            for b in per_benchmark:
                lines.append(
                    f"### {b.benchmark} (weight={b.weight:.1f}): "
                    f"accuracy={b.accuracy:.4f}, "
                    f"latency={b.mean_latency_seconds:.2f}s, "
                    f"cost=${b.total_cost_usd:.4f}, "
                    f"energy={b.total_energy_joules:.2f}J, "
                    f"samples={b.samples_evaluated}, errors={b.errors}"
                )
            weighted_acc = (
                sum(b.accuracy * b.weight for b in per_benchmark) / total_weight
            )
            lines.append(f"\nOverall weighted accuracy: {weighted_acc:.4f}")
            lines.append("")

        lines.append("## Aggregate Results")
        lines.append(f"- accuracy: {summary.accuracy:.4f}")
        lines.append(f"- mean_latency_seconds: {summary.mean_latency_seconds:.4f}")
        lines.append(f"- total_cost_usd: {summary.total_cost_usd:.4f}")
        lines.append(f"- total_samples: {summary.total_samples}")
        lines.append(f"- scored_samples: {summary.scored_samples}")
        lines.append(f"- correct: {summary.correct}")
        lines.append(f"- errors: {summary.errors}")
        if summary.per_subject:
            lines.append("\n### Per-Subject Breakdown")
            for subject, metrics in sorted(summary.per_subject.items()):
                metrics_str = ", ".join(
                    f"{k}={v:.3f}" for k, v in sorted(metrics.items())
                )
                lines.append(f"- {subject}: {metrics_str}")
        lines.append("")

        if sample_scores:
            lines.append("## Per-Sample Scores")
            lines.append(self._format_sample_scores(sample_scores))
            lines.append("")

        if traces:
            lines.append("## Sample Traces")
            lines.append(self._format_traces(traces))
            lines.append("")

        lines.append(
            "Provide your analysis as a JSON object inside a ```json code block with:\n"
            '1. "summary_text": string with detailed analysis\n'
            '2. "failure_patterns": list of identified failure patterns\n'
            '3. "primitive_ratings": dict mapping primitive names '
            'to "high"/"medium"/"low"\n'
            '4. "suggested_changes": list of specific config changes to try\n'
            '5. "target_primitive": which primitive to change next '
            "(intelligence/engine/agent/tools/learning)"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_history(
        self,
        history: List[TrialResult],
        frontier_ids: Optional[set] = None,
    ) -> str:
        """Render trial history as structured text for the LLM prompt."""
        lines: List[str] = []
        for i, result in enumerate(history, 1):
            tag = ""
            if frontier_ids and result.trial_id in frontier_ids:
                tag = " [FRONTIER]"
            lines.append(f"### Trial {i} (id={result.trial_id}){tag}")
            lines.append(f"Params: {json.dumps(result.config.params)}")
            lines.append(f"Accuracy: {result.accuracy:.4f}")
            lines.append(f"Latency: {result.mean_latency_seconds:.4f}s")
            lines.append(f"Cost: ${result.total_cost_usd:.4f}")
            lines.append(f"Energy: {result.total_energy_joules:.4f}J")
            if result.per_benchmark:
                bench_parts = [
                    f"{b.benchmark}={b.accuracy:.4f}" for b in result.per_benchmark
                ]
                lines.append(f"Per-benchmark accuracy: {', '.join(bench_parts)}")
            if result.summary:
                s = result.summary
                if s.throughput_stats:
                    lines.append(f"Throughput: {s.throughput_stats.mean:.2f} tok/s")
                if s.ipw_stats:
                    lines.append(f"IPW: {s.ipw_stats.mean:.4f}")
            if result.structured_feedback:
                fb = result.structured_feedback
                if fb.failure_patterns:
                    lines.append(f"Failure patterns: {', '.join(fb.failure_patterns)}")
                if fb.primitive_ratings:
                    ratings = ", ".join(
                        f"{k}={v}" for k, v in sorted(fb.primitive_ratings.items())
                    )
                    lines.append(f"Primitive ratings: {ratings}")
                if fb.target_primitive:
                    lines.append(f"Target primitive: {fb.target_primitive}")
            elif result.analysis:
                lines.append(f"Analysis: {result.analysis}")
            if result.failure_modes:
                lines.append(f"Failure modes: {', '.join(result.failure_modes)}")
            lines.append("")
        return "\n".join(lines)

    def _format_traces(self, traces: List[Trace]) -> str:
        """Render traces as structured text for the LLM prompt.

        Limits to the last 10 traces and truncates long outputs to keep
        the prompt manageable.
        """
        max_traces = 10
        max_result_len = 500
        max_steps_per_trace = 10

        recent = traces[-max_traces:]
        lines: List[str] = []

        for trace in recent:
            lines.append(
                f"### Trace {trace.trace_id} (agent={trace.agent}, model={trace.model})"
            )
            lines.append(f"Query: {trace.query}")
            if trace.outcome:
                lines.append(f"Outcome: {trace.outcome}")
            if trace.feedback is not None:
                lines.append(f"Feedback: {trace.feedback}")
            lines.append(
                f"Latency: {trace.total_latency_seconds:.3f}s, "
                f"Tokens: {trace.total_tokens}"
            )

            # Show steps (limited)
            steps = trace.steps[:max_steps_per_trace]
            if steps:
                lines.append("Steps:")
                for step in steps:
                    step_input = json.dumps(step.input)
                    step_output = json.dumps(step.output)
                    if len(step_input) > max_result_len:
                        step_input = step_input[:max_result_len] + "..."
                    if len(step_output) > max_result_len:
                        step_output = step_output[:max_result_len] + "..."
                    lines.append(
                        f"  - {step.step_type.value}: "
                        f"input={step_input}, "
                        f"output={step_output} "
                        f"({step.duration_seconds:.3f}s)"
                    )
                if len(trace.steps) > max_steps_per_trace:
                    lines.append(
                        f"  ... ({len(trace.steps) - max_steps_per_trace} more steps)"
                    )

            result_text = trace.result
            if len(result_text) > max_result_len:
                result_text = result_text[:max_result_len] + "..."
            lines.append(f"Result: {result_text}")
            lines.append("")

        return "\n".join(lines)

    def propose_targeted(
        self,
        history: List[TrialResult],
        base_config: TrialConfig,
        target_primitive: str,
        frontier_ids: Optional[set] = None,
    ) -> TrialConfig:
        """Propose a config that only changes one primitive."""
        if self.optimizer_backend is None:
            raise ValueError("optimizer_backend is required to propose configurations")

        prompt = self._build_targeted_prompt(
            history,
            base_config,
            target_primitive,
            frontier_ids,
        )
        response = self.optimizer_backend.generate(
            prompt,
            model=self.optimizer_model,
            system="You are an expert AI systems optimizer.",
            temperature=0.7,
            max_tokens=2048,
        )
        proposed = self._parse_config_response(response)

        # Enforce constraint: preserve non-target params from base_config
        merged_params = dict(base_config.params)
        for key, value in proposed.params.items():
            if key.startswith(target_primitive + ".") or key.startswith(
                target_primitive.rstrip("s") + "."
            ):
                merged_params[key] = value
        proposed.params = merged_params
        return proposed

    def propose_merge(
        self,
        candidates: List[TrialResult],
        history: List[TrialResult],
        frontier_ids: Optional[set] = None,
    ) -> TrialConfig:
        """Combine best aspects of frontier members into one config."""
        if self.optimizer_backend is None:
            raise ValueError("optimizer_backend is required to propose configurations")

        prompt = self._build_merge_prompt(candidates, history, frontier_ids)
        response = self.optimizer_backend.generate(
            prompt,
            model=self.optimizer_model,
            system="You are an expert AI systems optimizer.",
            temperature=0.7,
            max_tokens=2048,
        )
        return self._parse_config_response(response)

    # ------------------------------------------------------------------
    # Targeted / Merge prompt builders
    # ------------------------------------------------------------------

    def _build_targeted_prompt(
        self,
        history: List[TrialResult],
        base_config: TrialConfig,
        target_primitive: str,
        frontier_ids: Optional[set] = None,
    ) -> str:
        """Build prompt for primitive-targeted mutation."""
        lines: List[str] = []
        lines.append("You are optimizing an OpenJarvis AI system configuration.")
        lines.append("")
        lines.append(self.search_space.to_prompt_description())

        lines.append("## Base Configuration")
        for key, value in sorted(base_config.params.items()):
            lines.append(f"- {key}: {value}")
        lines.append("")

        lines.append(f"## Target Primitive: {target_primitive}")
        lines.append(
            f"ONLY change parameters under the '{target_primitive}' primitive. "
            "Keep all other parameters exactly as they are."
        )
        lines.append("")

        lines.append("## Optimization History")
        if history:
            lines.append(self._format_history(history, frontier_ids=frontier_ids))
        lines.append("")

        lines.append(
            "Return a JSON object inside a ```json code block with:\n"
            '1. "params": dict of config params (only change '
            f"{target_primitive} params)\n"
            '2. "reasoning": string explaining your changes'
        )
        return "\n".join(lines)

    def _build_merge_prompt(
        self,
        candidates: List[TrialResult],
        history: List[TrialResult],
        frontier_ids: Optional[set] = None,
    ) -> str:
        """Build prompt for merging frontier configs."""
        lines: List[str] = []
        lines.append("You are optimizing an OpenJarvis AI system configuration.")
        lines.append("")
        lines.append(self.search_space.to_prompt_description())

        lines.append("## Frontier Candidates to Merge")
        for i, cand in enumerate(candidates, 1):
            lines.append(f"### Candidate {i} (id={cand.trial_id})")
            lines.append(f"Params: {json.dumps(cand.config.params)}")
            lines.append(f"Accuracy: {cand.accuracy:.4f}")
            lines.append(f"Latency: {cand.mean_latency_seconds:.4f}s")
            lines.append(f"Cost: ${cand.total_cost_usd:.4f}")
            lines.append(f"Energy: {cand.total_energy_joules:.4f}J")
            lines.append("")

        lines.append(
            "Combine the best aspects of these frontier configs into "
            "one unified configuration."
        )
        lines.append("")

        if history:
            lines.append("## Full History")
            lines.append(self._format_history(history, frontier_ids=frontier_ids))
            lines.append("")

        lines.append(
            "Return a JSON object inside a ```json code block with:\n"
            '1. "params": dict of merged config params\n'
            '2. "reasoning": string explaining the merge strategy'
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Sample score + feedback helpers
    # ------------------------------------------------------------------

    def _format_sample_scores(self, scores: List[SampleScore]) -> str:
        """Render per-sample scores for the LLM prompt."""
        passed = [s for s in scores if s.is_correct]
        failed = [s for s in scores if s.is_correct is False]
        errored = [s for s in scores if s.error]

        lines: List[str] = []
        lines.append(
            f"Total: {len(scores)} | Passed: {len(passed)} | "
            f"Failed: {len(failed)} | Errors: {len(errored)}"
        )

        if failed:
            lines.append("\n### Failed Samples")
            for s in failed[:20]:
                lines.append(f"- {s.record_id}: latency={s.latency_seconds:.2f}s")

        if errored:
            lines.append("\n### Error Samples")
            for s in errored[:10]:
                error_text = (s.error or "")[:200]
                lines.append(f"- {s.record_id}: {error_text}")

        return "\n".join(lines)

    def _parse_feedback_response(self, response: str) -> TrialFeedback:
        """Parse LLM response into a TrialFeedback, with fallback."""
        response = response.strip()

        # Try JSON code block
        json_block_match = re.search(
            r"```json\s*\n?(.*?)\n?\s*```", response, re.DOTALL
        )
        raw_json = None
        if json_block_match:
            raw_json = json_block_match.group(1).strip()
        else:
            # Try generic code block
            code_block_match = re.search(
                r"```\s*\n?(.*?)\n?\s*```", response, re.DOTALL
            )
            if code_block_match:
                raw_json = code_block_match.group(1).strip()
            else:
                # Try raw JSON object
                decoder = json.JSONDecoder()
                for m in re.finditer(r"\{", response):
                    try:
                        data, _ = decoder.raw_decode(response, m.start())
                        if isinstance(data, dict):
                            raw_json = json.dumps(data)
                            break
                    except json.JSONDecodeError as exc:
                        logger.debug(
                            "Failed to parse LLM optimizer JSON response: %s",
                            exc,
                        )
                        continue

        if raw_json:
            try:
                data = json.loads(raw_json)
                return TrialFeedback(
                    summary_text=data.get("summary_text", ""),
                    failure_patterns=data.get("failure_patterns", []),
                    primitive_ratings=data.get("primitive_ratings", {}),
                    suggested_changes=data.get("suggested_changes", []),
                    target_primitive=data.get("target_primitive", ""),
                )
            except json.JSONDecodeError as exc:
                logger.debug("Failed to parse LLM optimizer JSON response: %s", exc)

        # Fallback: wrap raw text as summary
        return TrialFeedback(summary_text=response)

    def _parse_config_response(self, response: str) -> TrialConfig:
        """Extract a TrialConfig from an LLM response.

        Looks for a ```json ... ``` block first, then falls back to
        finding a raw JSON object in the response text.
        """
        trial_id = uuid.uuid4().hex[:12]

        # Try to extract from a ```json code block
        json_block_match = re.search(
            r"```json\s*\n?(.*?)\n?\s*```", response, re.DOTALL
        )
        if json_block_match:
            raw_json = json_block_match.group(1).strip()
            try:
                data = json.loads(raw_json)
                return self._config_from_dict(data, trial_id)
            except json.JSONDecodeError as exc:
                logger.debug("Failed to parse LLM optimizer JSON response: %s", exc)

        # Try to extract from a generic ``` code block
        code_block_match = re.search(r"```\s*\n?(.*?)\n?\s*```", response, re.DOTALL)
        if code_block_match:
            raw_json = code_block_match.group(1).strip()
            try:
                data = json.loads(raw_json)
                return self._config_from_dict(data, trial_id)
            except json.JSONDecodeError as exc:
                logger.debug("Failed to parse LLM optimizer JSON response: %s", exc)

        # Try to find a raw JSON object in the response by scanning
        # for each '{' and attempting to parse from that position.
        decoder = json.JSONDecoder()
        for m in re.finditer(r"\{", response):
            try:
                data, _ = decoder.raw_decode(response, m.start())
                if isinstance(data, dict):
                    return self._config_from_dict(data, trial_id)
            except json.JSONDecodeError as exc:
                logger.debug("Failed to parse LLM optimizer JSON response: %s", exc)
                continue

        # Last resort: return config with at least the fixed params
        ss = self.search_space
        fixed = dict(ss.fixed) if ss and ss.fixed else {}
        return TrialConfig(
            trial_id=trial_id,
            params=fixed,
            reasoning="Failed to parse LLM response.",
        )

    def _config_from_dict(self, data: Dict[str, Any], trial_id: str) -> TrialConfig:
        """Build a TrialConfig from a parsed JSON dict.

        Merges fixed parameters from the search space so that fixed values
        (e.g. intelligence.model, engine.backend) are always present.
        """
        params = data.get("params", {})
        reasoning = data.get("reasoning", "")

        # Inject fixed params — these override anything the LLM proposed
        if self.search_space and self.search_space.fixed:
            for key, value in self.search_space.fixed.items():
                params[key] = value

        return TrialConfig(
            trial_id=trial_id,
            params=params,
            reasoning=reasoning,
        )


__all__ = ["LLMOptimizer"]
