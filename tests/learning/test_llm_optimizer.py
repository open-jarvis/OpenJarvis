"""Tests for openjarvis.optimize.llm_optimizer module."""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.types import RunSummary
from openjarvis.learning.optimize.llm_optimizer import LLMOptimizer
from openjarvis.learning.optimize.types import (
    SampleScore,
    SearchDimension,
    SearchSpace,
    TrialConfig,
    TrialFeedback,
    TrialResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_search_space() -> SearchSpace:
    """Build a small search space for testing."""
    return SearchSpace(
        dimensions=[
            SearchDimension(
                name="agent.type",
                dim_type="categorical",
                values=["simple", "orchestrator", "native_react"],
                description="Agent architecture",
                primitive="agent",
            ),
            SearchDimension(
                name="intelligence.temperature",
                dim_type="continuous",
                low=0.0,
                high=1.0,
                description="Generation temperature",
                primitive="intelligence",
            ),
            SearchDimension(
                name="agent.max_turns",
                dim_type="integer",
                low=1,
                high=30,
                description="Maximum reasoning turns",
                primitive="agent",
            ),
        ],
        fixed={"engine": "ollama"},
        constraints=["SimpleAgent should only have max_turns = 1"],
    )


def _make_mock_backend(response: str) -> MagicMock:
    """Create a mock InferenceBackend that returns the given response."""
    backend = MagicMock(spec=InferenceBackend)
    backend.backend_id = "mock"
    backend.generate.return_value = response
    return backend


def _make_trial_result(
    trial_id: str = "t1",
    params: Dict[str, Any] | None = None,
    accuracy: float = 0.75,
    latency: float = 1.5,
    cost: float = 0.02,
    analysis: str = "Decent results",
    failure_modes: list[str] | None = None,
) -> TrialResult:
    """Create a TrialResult for testing."""
    if params is None:
        params = {
            "agent.type": "orchestrator",
            "intelligence.temperature": 0.5,
        }
    config = TrialConfig(
        trial_id=trial_id,
        params=params,
        reasoning="Test reasoning",
    )
    return TrialResult(
        trial_id=trial_id,
        config=config,
        accuracy=accuracy,
        mean_latency_seconds=latency,
        total_cost_usd=cost,
        analysis=analysis,
        failure_modes=failure_modes or [],
    )


def _make_trace(
    trace_id: str = "trace-001",
    query: str = "What is 2+2?",
    agent: str = "orchestrator",
    model: str = "qwen3:8b",
    outcome: str = "success",
    result: str = "4",
    total_latency: float = 0.5,
    total_tokens: int = 100,
    num_steps: int = 2,
) -> Trace:
    """Create a Trace for testing."""
    steps = []
    for i in range(num_steps):
        step_type = StepType.GENERATE if i % 2 == 0 else StepType.TOOL_CALL
        steps.append(
            TraceStep(
                step_type=step_type,
                timestamp=float(i),
                duration_seconds=0.1,
                input={"prompt": f"step {i} input"},
                output={"content": f"step {i} output"},
            )
        )
    return Trace(
        trace_id=trace_id,
        query=query,
        agent=agent,
        model=model,
        steps=steps,
        result=result,
        outcome=outcome,
        total_latency_seconds=total_latency,
        total_tokens=total_tokens,
    )


def _make_run_summary(
    accuracy: float = 0.80,
    latency: float = 1.2,
    cost: float = 0.03,
) -> RunSummary:
    """Create a RunSummary for testing."""
    return RunSummary(
        benchmark="supergpqa",
        category="reasoning",
        backend="ollama",
        model="qwen3:8b",
        total_samples=100,
        scored_samples=95,
        correct=76,
        accuracy=accuracy,
        errors=5,
        mean_latency_seconds=latency,
        total_cost_usd=cost,
        per_subject={"math": {"accuracy": 0.85, "count": 20.0}},
    )


# ---------------------------------------------------------------------------
# TestLLMOptimizer.__init__
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for LLMOptimizer.__init__."""

    def test_stores_search_space(self) -> None:
        space = _make_search_space()
        opt = LLMOptimizer(search_space=space)
        assert opt.search_space is space

    def test_stores_optimizer_model(self) -> None:
        space = _make_search_space()
        opt = LLMOptimizer(search_space=space, optimizer_model="gpt-4o")
        assert opt.optimizer_model == "gpt-4o"

    def test_default_optimizer_model(self) -> None:
        space = _make_search_space()
        opt = LLMOptimizer(search_space=space)
        assert opt.optimizer_model == "claude-sonnet-4-6"

    def test_stores_optimizer_backend(self) -> None:
        space = _make_search_space()
        backend = _make_mock_backend("")
        opt = LLMOptimizer(search_space=space, optimizer_backend=backend)
        assert opt.optimizer_backend is backend

    def test_default_backend_is_none(self) -> None:
        space = _make_search_space()
        opt = LLMOptimizer(search_space=space)
        assert opt.optimizer_backend is None


# ---------------------------------------------------------------------------
# TestProposeInitial
# ---------------------------------------------------------------------------


class TestProposeInitial:
    """Tests for LLMOptimizer.propose_initial."""

    def test_returns_trial_config(self) -> None:
        response = json.dumps(
            {
                "params": {
                    "agent.type": "native_react",
                    "intelligence.temperature": 0.3,
                },
                "reasoning": "Balanced starting point",
            }
        )
        response = f"```json\n{response}\n```"
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        config = opt.propose_initial()
        assert isinstance(config, TrialConfig)
        assert config.params["agent.type"] == "native_react"
        assert config.params["intelligence.temperature"] == 0.3
        assert config.reasoning == "Balanced starting point"
        assert len(config.trial_id) == 12

    def test_calls_backend_generate(self) -> None:
        response = '```json\n{"params": {}, "reasoning": "test"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        opt.propose_initial()
        backend.generate.assert_called_once()
        call_kwargs = backend.generate.call_args
        assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs.kwargs["temperature"] == 0.7

    def test_prompt_contains_search_space(self) -> None:
        response = '```json\n{"params": {}, "reasoning": "ok"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        opt.propose_initial()
        prompt = backend.generate.call_args.args[0]
        assert "Search Space" in prompt
        assert "agent.type" in prompt
        assert "intelligence.temperature" in prompt
        assert "Objective" in prompt

    def test_raises_without_backend(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        with pytest.raises(ValueError, match="optimizer_backend"):
            opt.propose_initial()


# ---------------------------------------------------------------------------
# TestProposeNext
# ---------------------------------------------------------------------------


class TestProposeNext:
    """Tests for LLMOptimizer.propose_next."""

    def test_returns_trial_config_with_history(self) -> None:
        response = json.dumps(
            {
                "params": {
                    "agent.type": "native_react",
                    "intelligence.temperature": 0.2,
                    "agent.max_turns": 15,
                },
                "reasoning": "Lower temp for better accuracy",
            }
        )
        response = f"```json\n{response}\n```"
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        history = [_make_trial_result()]
        config = opt.propose_next(history)
        assert config.params["agent.type"] == "native_react"
        assert config.params["intelligence.temperature"] == 0.2
        assert config.reasoning == "Lower temp for better accuracy"

    def test_prompt_includes_history(self) -> None:
        response = '```json\n{"params": {}, "reasoning": "ok"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        history = [
            _make_trial_result(
                trial_id="t1",
                accuracy=0.75,
                analysis="Good but slow",
            ),
        ]
        opt.propose_next(history)
        prompt = backend.generate.call_args.args[0]
        assert "Optimization History" in prompt
        assert "Trial 1" in prompt
        assert "0.75" in prompt
        assert "Good but slow" in prompt

    def test_prompt_includes_traces(self) -> None:
        response = '```json\n{"params": {}, "reasoning": "ok"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        traces = [_make_trace()]
        opt.propose_next([], traces=traces)
        prompt = backend.generate.call_args.args[0]
        assert "Execution Traces" in prompt
        assert "trace-001" in prompt
        assert "What is 2+2?" in prompt

    def test_empty_history(self) -> None:
        response = (
            '```json\n{"params": {"agent.type": "simple"},'
            ' "reasoning": "start simple"}\n```'
        )
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        config = opt.propose_next([])
        prompt = backend.generate.call_args.args[0]
        assert "No trials have been run yet" in prompt
        assert config.params["agent.type"] == "simple"

    def test_raises_without_backend(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        with pytest.raises(ValueError, match="optimizer_backend"):
            opt.propose_next([])

    def test_prompt_includes_failure_modes(self) -> None:
        response = '```json\n{"params": {}, "reasoning": "fix failures"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        history = [
            _make_trial_result(
                failure_modes=["timeout on long inputs", "JSON parse error"],
            ),
        ]
        opt.propose_next(history)
        prompt = backend.generate.call_args.args[0]
        assert "timeout on long inputs" in prompt
        assert "JSON parse error" in prompt


# ---------------------------------------------------------------------------
# TestAnalyzeTrial
# ---------------------------------------------------------------------------


class TestAnalyzeTrial:
    """Tests for LLMOptimizer.analyze_trial."""

    def test_returns_trial_feedback(self) -> None:
        backend = _make_mock_backend(
            "The configuration showed strong accuracy at 0.80 "
            "but latency could be improved."
        )
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(
            trial_id="t1",
            params={"agent.type": "orchestrator"},
            reasoning="Test",
        )
        summary = _make_run_summary()
        result = opt.analyze_trial(trial, summary)
        assert isinstance(result, TrialFeedback)
        assert "accuracy" in result.summary_text.lower()

    def test_prompt_contains_config(self) -> None:
        backend = _make_mock_backend("Analysis here.")
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(
            trial_id="t1",
            params={
                "agent.type": "orchestrator",
                "intelligence.temperature": 0.5,
            },
            reasoning="Testing mid-range temperature",
        )
        summary = _make_run_summary()
        opt.analyze_trial(trial, summary)
        prompt = backend.generate.call_args.args[0]
        assert "agent.type" in prompt
        assert "orchestrator" in prompt
        assert "0.5" in prompt
        assert "Testing mid-range temperature" in prompt

    def test_prompt_contains_results(self) -> None:
        backend = _make_mock_backend("Analysis here.")
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary(accuracy=0.85, latency=2.1, cost=0.05)
        opt.analyze_trial(trial, summary)
        prompt = backend.generate.call_args.args[0]
        assert "0.8500" in prompt
        assert "2.1000" in prompt
        assert "0.0500" in prompt

    def test_prompt_contains_per_subject(self) -> None:
        backend = _make_mock_backend("Analysis here.")
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary()
        opt.analyze_trial(trial, summary)
        prompt = backend.generate.call_args.args[0]
        assert "Per-Subject" in prompt
        assert "math" in prompt

    def test_prompt_contains_traces(self) -> None:
        backend = _make_mock_backend("Analysis with traces.")
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary()
        traces = [_make_trace()]
        opt.analyze_trial(trial, summary, traces=traces)
        prompt = backend.generate.call_args.args[0]
        assert "Sample Traces" in prompt
        assert "trace-001" in prompt

    def test_raises_without_backend(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary()
        with pytest.raises(ValueError, match="optimizer_backend"):
            opt.analyze_trial(trial, summary)

    def test_uses_low_temperature(self) -> None:
        backend = _make_mock_backend("Analysis.")
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary()
        opt.analyze_trial(trial, summary)
        call_kwargs = backend.generate.call_args
        assert call_kwargs.kwargs["temperature"] == 0.3


# ---------------------------------------------------------------------------
# TestParseConfigResponse
# ---------------------------------------------------------------------------


class TestParseConfigResponse:
    """Tests for LLMOptimizer._parse_config_response."""

    def _make_optimizer(self) -> LLMOptimizer:
        return LLMOptimizer(search_space=_make_search_space())

    def test_json_code_block(self) -> None:
        opt = self._make_optimizer()
        response = (
            "Here is my suggestion:\n\n"
            "```json\n"
            '{"params": {"agent.type": "native_react"}, '
            '"reasoning": "Best for tool use"}\n'
            "```\n\n"
            "This should improve results."
        )
        config = opt._parse_config_response(response)
        assert config.params["agent.type"] == "native_react"
        assert config.reasoning == "Best for tool use"

    def test_generic_code_block(self) -> None:
        opt = self._make_optimizer()
        response = (
            "```\n"
            '{"params": {"intelligence.temperature": 0.1}, '
            '"reasoning": "Low temp"}\n'
            "```"
        )
        config = opt._parse_config_response(response)
        assert config.params["intelligence.temperature"] == 0.1

    def test_raw_json(self) -> None:
        opt = self._make_optimizer()
        response = (
            'I suggest: {"params": {"agent.max_turns": 10}, "reasoning": "More turns"}'
        )
        config = opt._parse_config_response(response)
        assert config.params["agent.max_turns"] == 10
        assert config.reasoning == "More turns"

    def test_unparseable_response(self) -> None:
        opt = self._make_optimizer()
        response = "I cannot produce a valid configuration right now."
        config = opt._parse_config_response(response)
        # Fixed params are injected even when parsing fails
        assert config.params == {"engine": "ollama"}
        assert "Failed to parse" in config.reasoning

    def test_trial_id_is_12_chars(self) -> None:
        opt = self._make_optimizer()
        response = '```json\n{"params": {}, "reasoning": ""}\n```'
        config = opt._parse_config_response(response)
        assert len(config.trial_id) == 12

    def test_missing_reasoning_key(self) -> None:
        opt = self._make_optimizer()
        response = '```json\n{"params": {"agent.type": "simple"}}\n```'
        config = opt._parse_config_response(response)
        assert config.params["agent.type"] == "simple"
        assert config.reasoning == ""

    def test_missing_params_key(self) -> None:
        opt = self._make_optimizer()
        response = '```json\n{"reasoning": "just thinking"}\n```'
        config = opt._parse_config_response(response)
        # Fixed params are injected even when "params" key is missing
        assert config.params == {"engine": "ollama"}
        assert config.reasoning == "just thinking"

    def test_json_with_surrounding_text(self) -> None:
        opt = self._make_optimizer()
        response = (
            "Based on the analysis, I propose:\n\n"
            "```json\n"
            "{\n"
            '  "params": {\n'
            '    "agent.type": "orchestrator",\n'
            '    "intelligence.temperature": 0.4,\n'
            '    "agent.max_turns": 20\n'
            "  },\n"
            '  "reasoning": "Multi-line\\nreasoning here"\n'
            "}\n"
            "```\n\n"
            "Let me know if you'd like to adjust anything."
        )
        config = opt._parse_config_response(response)
        assert config.params["agent.type"] == "orchestrator"
        assert config.params["intelligence.temperature"] == 0.4
        assert config.params["agent.max_turns"] == 20

    def test_invalid_json_in_code_block_falls_through(self) -> None:
        """If ```json block has invalid JSON, fall back to raw search."""
        opt = self._make_optimizer()
        # Invalid JSON in ```json block, but valid JSON later
        response = (
            "```json\n{invalid json}\n```\n\n"
            'Actually: {"params": {"agent.type": "simple"}, "reasoning": "fallback"}'
        )
        config = opt._parse_config_response(response)
        # Should find the valid JSON via raw search
        assert config.params.get("agent.type") == "simple"


# ---------------------------------------------------------------------------
# TestFormatHistory
# ---------------------------------------------------------------------------


class TestFormatHistory:
    """Tests for LLMOptimizer._format_history."""

    def test_single_trial(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        history = [_make_trial_result(trial_id="abc")]
        result = opt._format_history(history)
        assert "Trial 1" in result
        assert "abc" in result
        assert "0.7500" in result
        assert "Decent results" in result

    def test_multiple_trials(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        history = [
            _make_trial_result(trial_id="t1", accuracy=0.7),
            _make_trial_result(trial_id="t2", accuracy=0.85),
        ]
        result = opt._format_history(history)
        assert "Trial 1" in result
        assert "Trial 2" in result
        assert "t1" in result
        assert "t2" in result

    def test_includes_failure_modes(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        history = [
            _make_trial_result(
                failure_modes=["timeout", "parse_error"],
            ),
        ]
        result = opt._format_history(history)
        assert "timeout" in result
        assert "parse_error" in result

    def test_includes_params(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        history = [
            _make_trial_result(
                params={"agent.type": "native_react"},
            ),
        ]
        result = opt._format_history(history)
        assert "native_react" in result

    def test_empty_history(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        result = opt._format_history([])
        assert result == ""

    def test_marks_frontier_trials(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        history = [
            _make_trial_result(trial_id="t1"),
            _make_trial_result(trial_id="t2"),
        ]
        result = opt._format_history(history, frontier_ids={"t1"})
        assert "[FRONTIER]" in result
        # Only t1 should be marked
        lines = result.split("\n")
        frontier_lines = [line for line in lines if "[FRONTIER]" in line]
        assert len(frontier_lines) == 1
        assert "t1" in frontier_lines[0]


# ---------------------------------------------------------------------------
# TestFormatTraces
# ---------------------------------------------------------------------------


class TestFormatTraces:
    """Tests for LLMOptimizer._format_traces."""

    def test_single_trace(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        traces = [_make_trace()]
        result = opt._format_traces(traces)
        assert "trace-001" in result
        assert "What is 2+2?" in result
        assert "orchestrator" in result
        assert "success" in result

    def test_limits_to_last_10(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        traces = [_make_trace(trace_id=f"trace-{i:03d}") for i in range(20)]
        result = opt._format_traces(traces)
        # Should only include the last 10 (indices 10-19)
        assert "trace-010" in result
        assert "trace-019" in result
        # The first traces should not appear
        assert "trace-000" not in result
        assert "trace-009" not in result

    def test_truncates_long_outputs(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        long_result = "x" * 1000
        traces = [_make_trace(result=long_result)]
        result = opt._format_traces(traces)
        # Should be truncated and end with "..."
        assert "..." in result
        # Should NOT contain the full 1000 chars
        assert long_result not in result

    def test_includes_steps(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        traces = [_make_trace(num_steps=3)]
        result = opt._format_traces(traces)
        assert "Steps:" in result
        assert "generate" in result
        assert "tool_call" in result

    def test_shows_feedback(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        trace = _make_trace()
        trace.feedback = 0.9
        result = opt._format_traces([trace])
        assert "0.9" in result

    def test_empty_traces(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        result = opt._format_traces([])
        assert result == ""

    def test_truncates_long_step_data(self) -> None:
        opt = LLMOptimizer(search_space=_make_search_space())
        trace = _make_trace(num_steps=0)
        # Add a step with very long input/output
        trace.steps.append(
            TraceStep(
                step_type=StepType.GENERATE,
                timestamp=0.0,
                duration_seconds=0.1,
                input={"prompt": "a" * 1000},
                output={"content": "b" * 1000},
            )
        )
        result = opt._format_traces([trace])
        # The full 1000-char strings should not appear verbatim
        assert ("a" * 1000) not in result
        assert ("b" * 1000) not in result
        assert "..." in result


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end tests with mocked backend."""

    def test_propose_initial_then_next(self) -> None:
        """Simulate a two-step optimization loop."""
        space = _make_search_space()
        initial_response = (
            "```json\n"
            '{"params": {"agent.type": "orchestrator", '
            '"intelligence.temperature": 0.5, "agent.max_turns": 10}, '
            '"reasoning": "Balanced start"}\n'
            "```"
        )
        next_response = (
            "```json\n"
            '{"params": {"agent.type": "native_react", '
            '"intelligence.temperature": 0.2, "agent.max_turns": 15}, '
            '"reasoning": "Switch to ReAct for better tool use"}\n'
            "```"
        )
        backend = MagicMock(spec=InferenceBackend)
        backend.backend_id = "mock"
        backend.generate.side_effect = [initial_response, next_response]

        opt = LLMOptimizer(search_space=space, optimizer_backend=backend)

        # Step 1: initial proposal
        config1 = opt.propose_initial()
        assert config1.params["agent.type"] == "orchestrator"

        # Step 2: build history and ask for next
        result1 = TrialResult(
            trial_id=config1.trial_id,
            config=config1,
            accuracy=0.72,
            mean_latency_seconds=2.0,
            analysis="Accuracy needs improvement",
        )
        config2 = opt.propose_next([result1])
        assert config2.params["agent.type"] == "native_react"
        assert config2.params["intelligence.temperature"] == 0.2

    def test_full_loop_with_analysis(self) -> None:
        """Simulate propose -> evaluate -> analyze."""
        space = _make_search_space()
        propose_response = (
            "```json\n"
            '{"params": {"agent.type": "orchestrator"}, '
            '"reasoning": "Start with orchestrator"}\n'
            "```"
        )
        analysis_response = (
            "The orchestrator agent achieved moderate accuracy. "
            "The main bottleneck is latency due to multi-turn reasoning. "
            "Reducing max_turns or switching to native_react may help."
        )
        backend = MagicMock(spec=InferenceBackend)
        backend.backend_id = "mock"
        backend.generate.side_effect = [
            propose_response,
            analysis_response,
        ]

        opt = LLMOptimizer(search_space=space, optimizer_backend=backend)

        config = opt.propose_initial()
        summary = _make_run_summary()
        feedback = opt.analyze_trial(config, summary)
        assert isinstance(feedback, TrialFeedback)
        assert "orchestrator" in feedback.summary_text
        assert "latency" in feedback.summary_text

    def test_custom_optimizer_model(self) -> None:
        """Verify custom model is passed to backend."""
        response = '```json\n{"params": {}, "reasoning": "ok"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_model="gpt-4o",
            optimizer_backend=backend,
        )
        opt.propose_initial()
        call_kwargs = backend.generate.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# TestAnalyzeTrialStructured
# ---------------------------------------------------------------------------


class TestAnalyzeTrialStructured:
    """Tests for analyze_trial returning TrialFeedback."""

    def test_analyze_trial_returns_trial_feedback(self) -> None:
        """Mock backend returns structured JSON -> TrialFeedback."""
        feedback_json = json.dumps(
            {
                "summary_text": "Good accuracy but high latency",
                "failure_patterns": ["timeout on complex queries"],
                "primitive_ratings": {"agent": "high", "intelligence": "medium"},
                "suggested_changes": ["reduce max_turns"],
                "target_primitive": "agent",
            }
        )
        response = f"```json\n{feedback_json}\n```"
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={"agent.type": "orchestrator"})
        summary = _make_run_summary()
        result = opt.analyze_trial(trial, summary)
        assert isinstance(result, TrialFeedback)
        assert result.summary_text == "Good accuracy but high latency"
        assert result.failure_patterns == ["timeout on complex queries"]
        assert result.primitive_ratings == {"agent": "high", "intelligence": "medium"}
        assert result.suggested_changes == ["reduce max_turns"]
        assert result.target_primitive == "agent"

    def test_analyze_trial_fallback_to_text(self) -> None:
        """Unparseable response wraps as summary_text."""
        backend = _make_mock_backend(
            "The config showed good results overall but could use improvement."
        )
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary()
        result = opt.analyze_trial(trial, summary)
        assert isinstance(result, TrialFeedback)
        assert "good results" in result.summary_text
        assert result.failure_patterns == []
        assert result.target_primitive == ""

    def test_analyze_trial_with_sample_scores(self) -> None:
        """Verify sample_scores are included in the prompt."""
        feedback_json = json.dumps(
            {
                "summary_text": "Analysis with scores",
                "failure_patterns": [],
                "primitive_ratings": {},
                "suggested_changes": [],
                "target_primitive": "",
            }
        )
        response = f"```json\n{feedback_json}\n```"
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        trial = TrialConfig(trial_id="t1", params={})
        summary = _make_run_summary()
        scores = [
            SampleScore(record_id="r1", is_correct=True, latency_seconds=0.5),
            SampleScore(record_id="r2", is_correct=False, error="timeout"),
        ]
        opt.analyze_trial(trial, summary, sample_scores=scores)
        prompt = backend.generate.call_args.args[0]
        assert "Per-Sample Scores" in prompt
        assert "r2" in prompt


# ---------------------------------------------------------------------------
# TestProposeTargeted
# ---------------------------------------------------------------------------


class TestProposeTargeted:
    """Tests for LLMOptimizer.propose_targeted."""

    def test_preserves_non_target_params(self) -> None:
        response = json.dumps(
            {
                "params": {
                    "agent.type": "native_react",
                    "agent.max_turns": 20,
                    "intelligence.temperature": 0.9,
                },
                "reasoning": "Change agent only",
            }
        )
        response = f"```json\n{response}\n```"
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        base_config = TrialConfig(
            trial_id="base",
            params={
                "agent.type": "orchestrator",
                "agent.max_turns": 10,
                "intelligence.temperature": 0.5,
            },
        )
        result = opt.propose_targeted([], base_config, "agent")
        # Agent params should be updated
        assert result.params["agent.type"] == "native_react"
        assert result.params["agent.max_turns"] == 20
        # Non-target params should be preserved from base
        assert result.params["intelligence.temperature"] == 0.5

    def test_prompt_mentions_target_primitive(self) -> None:
        response = '```json\n{"params": {}, "reasoning": "ok"}\n```'
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        base_config = TrialConfig(trial_id="base", params={})
        opt.propose_targeted([], base_config, "intelligence")
        prompt = backend.generate.call_args.args[0]
        assert "intelligence" in prompt
        assert "ONLY change" in prompt


# ---------------------------------------------------------------------------
# TestProposeMerge
# ---------------------------------------------------------------------------


class TestProposeMerge:
    """Tests for LLMOptimizer.propose_merge."""

    def test_includes_candidates_in_prompt(self) -> None:
        response = (
            '```json\n{"params": {"agent.type":'
            ' "orchestrator"}, "reasoning":'
            ' "merged"}\n```'
        )
        backend = _make_mock_backend(response)
        opt = LLMOptimizer(
            search_space=_make_search_space(),
            optimizer_backend=backend,
        )
        candidates = [
            _make_trial_result(trial_id="c1", accuracy=0.9),
            _make_trial_result(trial_id="c2", accuracy=0.7),
        ]
        result = opt.propose_merge(candidates, [])
        assert isinstance(result, TrialConfig)
        prompt = backend.generate.call_args.args[0]
        assert "Candidate 1" in prompt
        assert "Candidate 2" in prompt
        assert "c1" in prompt
        assert "c2" in prompt
        assert "Merge" in prompt or "merge" in prompt
