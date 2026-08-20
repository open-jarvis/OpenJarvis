"""Tests for openjarvis.optimize.types module."""

from __future__ import annotations

from openjarvis.learning.optimize.types import (
    OptimizationRun,
    SampleScore,
    SearchDimension,
    SearchSpace,
    TrialConfig,
    TrialFeedback,
    TrialResult,
)
from openjarvis.recipes.loader import Recipe

# ---------------------------------------------------------------------------
# SearchDimension
# ---------------------------------------------------------------------------


class TestSearchDimension:
    """Tests for SearchDimension dataclass."""

    def test_categorical_dimension(self) -> None:
        dim = SearchDimension(
            name="agent.type",
            dim_type="categorical",
            values=["simple", "orchestrator", "native_react"],
            description="Agent architecture",
            primitive="agent",
        )
        assert dim.name == "agent.type"
        assert dim.dim_type == "categorical"
        assert dim.values == [
            "simple",
            "orchestrator",
            "native_react",
        ]
        assert dim.description == "Agent architecture"
        assert dim.primitive == "agent"
        assert dim.low is None
        assert dim.high is None

    def test_continuous_dimension(self) -> None:
        dim = SearchDimension(
            name="intelligence.temperature",
            dim_type="continuous",
            low=0.0,
            high=1.0,
            description="Generation temperature",
            primitive="intelligence",
        )
        assert dim.dim_type == "continuous"
        assert dim.low == 0.0
        assert dim.high == 1.0
        assert dim.values == []

    def test_integer_dimension(self) -> None:
        dim = SearchDimension(
            name="agent.max_turns",
            dim_type="integer",
            low=1,
            high=30,
            primitive="agent",
        )
        assert dim.dim_type == "integer"
        assert dim.low == 1
        assert dim.high == 30

    def test_subset_dimension(self) -> None:
        dim = SearchDimension(
            name="tools.tool_set",
            dim_type="subset",
            values=["calculator", "think", "web_search"],
            primitive="tools",
        )
        assert dim.dim_type == "subset"
        assert len(dim.values) == 3

    def test_text_dimension(self) -> None:
        dim = SearchDimension(
            name="intelligence.system_prompt",
            dim_type="text",
            description="System prompt to guide model behavior",
            primitive="intelligence",
        )
        assert dim.dim_type == "text"
        assert dim.values == []
        assert dim.low is None
        assert dim.high is None

    def test_defaults(self) -> None:
        dim = SearchDimension(name="x", dim_type="categorical")
        assert dim.values == []
        assert dim.low is None
        assert dim.high is None
        assert dim.description == ""
        assert dim.primitive == ""

    def test_mutable_default_isolation(self) -> None:
        """Ensure mutable defaults are independent."""
        dim1 = SearchDimension(name="a", dim_type="categorical")
        dim2 = SearchDimension(name="b", dim_type="categorical")
        dim1.values.append("x")
        assert dim2.values == []


# ---------------------------------------------------------------------------
# SearchSpace
# ---------------------------------------------------------------------------


class TestSearchSpace:
    """Tests for SearchSpace dataclass."""

    def test_empty_search_space(self) -> None:
        space = SearchSpace()
        assert space.dimensions == []
        assert space.fixed == {}
        assert space.constraints == []

    def test_search_space_with_dimensions(self) -> None:
        dims = [
            SearchDimension(
                name="a",
                dim_type="categorical",
                values=["x", "y"],
            ),
            SearchDimension(
                name="b",
                dim_type="continuous",
                low=0.0,
                high=1.0,
            ),
        ]
        space = SearchSpace(
            dimensions=dims,
            fixed={"engine": "ollama"},
            constraints=["a must not be x when b > 0.5"],
        )
        assert len(space.dimensions) == 2
        assert space.fixed == {"engine": "ollama"}
        assert len(space.constraints) == 1

    def test_to_prompt_description_has_header(self) -> None:
        space = SearchSpace(
            dimensions=[
                SearchDimension(
                    name="agent.type",
                    dim_type="categorical",
                    values=["simple", "orchestrator"],
                    description="Agent kind",
                    primitive="agent",
                ),
            ],
        )
        desc = space.to_prompt_description()
        assert "# Search Space" in desc
        assert "## Agent" in desc
        assert "agent.type" in desc
        assert "categorical" in desc
        assert "Agent kind" in desc
        assert "simple" in desc
        assert "orchestrator" in desc

    def test_to_prompt_description_continuous(self) -> None:
        space = SearchSpace(
            dimensions=[
                SearchDimension(
                    name="intelligence.temperature",
                    dim_type="continuous",
                    low=0.0,
                    high=1.0,
                    primitive="intelligence",
                ),
            ],
        )
        desc = space.to_prompt_description()
        assert "Range:" in desc
        assert "0.0" in desc
        assert "1.0" in desc

    def test_to_prompt_description_text(self) -> None:
        space = SearchSpace(
            dimensions=[
                SearchDimension(
                    name="intelligence.system_prompt",
                    dim_type="text",
                    primitive="intelligence",
                ),
            ],
        )
        desc = space.to_prompt_description()
        assert "Free-form text" in desc

    def test_to_prompt_description_fixed_params(self) -> None:
        space = SearchSpace(
            dimensions=[],
            fixed={"engine": "ollama", "model": "qwen3:8b"},
        )
        desc = space.to_prompt_description()
        assert "## Fixed Parameters" in desc
        assert "engine = ollama" in desc
        assert "model = qwen3:8b" in desc

    def test_to_prompt_description_constraints(self) -> None:
        space = SearchSpace(
            dimensions=[],
            constraints=[
                "max_turns must be >= 1",
                "temperature must be <= 1.0",
            ],
        )
        desc = space.to_prompt_description()
        assert "## Constraints" in desc
        assert "max_turns must be >= 1" in desc
        assert "temperature must be <= 1.0" in desc

    def test_to_prompt_description_groups_by_primitive(self) -> None:
        space = SearchSpace(
            dimensions=[
                SearchDimension(
                    name="a.x",
                    dim_type="categorical",
                    values=["1"],
                    primitive="agent",
                ),
                SearchDimension(
                    name="i.y",
                    dim_type="continuous",
                    low=0,
                    high=1,
                    primitive="intelligence",
                ),
                SearchDimension(
                    name="a.z",
                    dim_type="integer",
                    low=1,
                    high=10,
                    primitive="agent",
                ),
            ],
        )
        desc = space.to_prompt_description()
        # Both agent dimensions under the Agent header
        assert "## Agent" in desc
        assert "## Intelligence" in desc

    def test_mutable_default_isolation(self) -> None:
        s1 = SearchSpace()
        s2 = SearchSpace()
        s1.dimensions.append(
            SearchDimension(name="x", dim_type="categorical"),
        )
        s1.fixed["key"] = "val"
        s1.constraints.append("rule")
        assert s2.dimensions == []
        assert s2.fixed == {}
        assert s2.constraints == []


# ---------------------------------------------------------------------------
# TrialConfig
# ---------------------------------------------------------------------------


class TestTrialConfig:
    """Tests for TrialConfig dataclass."""

    def test_creation(self) -> None:
        tc = TrialConfig(
            trial_id="t1",
            params={
                "agent.type": "orchestrator",
                "intelligence.temperature": 0.7,
            },
            reasoning="Higher temperature for creativity",
        )
        assert tc.trial_id == "t1"
        assert tc.params["agent.type"] == "orchestrator"
        assert tc.reasoning == "Higher temperature for creativity"

    def test_defaults(self) -> None:
        tc = TrialConfig(trial_id="t0")
        assert tc.params == {}
        assert tc.reasoning == ""

    def test_to_recipe_basic(self) -> None:
        tc = TrialConfig(
            trial_id="abc",
            params={
                "intelligence.model": "qwen3:8b",
                "intelligence.temperature": 0.5,
                "engine.backend": "ollama",
                "agent.type": "native_react",
                "agent.max_turns": 10,
                "tools.tool_set": ["calculator", "think"],
                "learning.routing_policy": "grpo",
            },
        )
        recipe = tc.to_recipe()
        assert isinstance(recipe, Recipe)
        assert recipe.name == "trial-abc"
        assert recipe.model == "qwen3:8b"
        assert recipe.temperature == 0.5
        assert recipe.engine_key == "ollama"
        assert recipe.agent_type == "native_react"
        assert recipe.max_turns == 10
        assert recipe.tools == ["calculator", "think"]
        assert recipe.routing_policy == "grpo"

    def test_to_recipe_partial_params(self) -> None:
        tc = TrialConfig(
            trial_id="partial",
            params={"intelligence.temperature": 0.3},
        )
        recipe = tc.to_recipe()
        assert recipe.temperature == 0.3
        assert recipe.model is None
        assert recipe.engine_key is None
        assert recipe.agent_type is None

    def test_to_recipe_unknown_params_ignored(self) -> None:
        tc = TrialConfig(
            trial_id="unk",
            params={"some.unknown.param": "value"},
        )
        recipe = tc.to_recipe()
        assert recipe.name == "trial-unk"
        # Unknown params should not cause an error

    def test_to_recipe_system_prompt(self) -> None:
        tc = TrialConfig(
            trial_id="sp",
            params={
                "agent.system_prompt": "You are a helpful assistant.",
            },
        )
        recipe = tc.to_recipe()
        assert recipe.system_prompt == "You are a helpful assistant."

    def test_to_recipe_quantization(self) -> None:
        tc = TrialConfig(
            trial_id="q",
            params={"intelligence.quantization": "q4_K_M"},
        )
        recipe = tc.to_recipe()
        assert recipe.quantization == "q4_K_M"

    def test_to_recipe_agent_policy(self) -> None:
        tc = TrialConfig(
            trial_id="ap",
            params={"learning.agent_policy": "icl_updater"},
        )
        recipe = tc.to_recipe()
        assert recipe.agent_policy == "icl_updater"

    def test_mutable_default_isolation(self) -> None:
        tc1 = TrialConfig(trial_id="a")
        tc2 = TrialConfig(trial_id="b")
        tc1.params["x"] = 1
        assert "x" not in tc2.params


# ---------------------------------------------------------------------------
# TrialResult
# ---------------------------------------------------------------------------


class TestTrialResult:
    """Tests for TrialResult dataclass."""

    def test_creation_with_defaults(self) -> None:
        config = TrialConfig(trial_id="t1")
        result = TrialResult(trial_id="t1", config=config)
        assert result.trial_id == "t1"
        assert result.accuracy == 0.0
        assert result.mean_latency_seconds == 0.0
        assert result.total_cost_usd == 0.0
        assert result.total_energy_joules == 0.0
        assert result.total_tokens == 0
        assert result.samples_evaluated == 0
        assert result.analysis == ""
        assert result.failure_modes == []
        assert result.per_sample_feedback == []
        assert result.summary is None
        assert result.sample_scores == []
        assert result.structured_feedback is None

    def test_creation_with_values(self) -> None:
        config = TrialConfig(
            trial_id="t2",
            params={"agent.type": "orchestrator"},
        )
        result = TrialResult(
            trial_id="t2",
            config=config,
            accuracy=0.85,
            mean_latency_seconds=1.2,
            total_cost_usd=0.05,
            total_energy_joules=150.0,
            total_tokens=5000,
            samples_evaluated=100,
            analysis="Good accuracy, moderate latency",
            failure_modes=["timeout on long inputs"],
            per_sample_feedback=[
                {"id": "s1", "correct": True},
            ],
        )
        assert result.accuracy == 0.85
        assert result.mean_latency_seconds == 1.2
        assert result.total_cost_usd == 0.05
        assert result.total_energy_joules == 150.0
        assert result.total_tokens == 5000
        assert result.samples_evaluated == 100
        assert result.analysis == "Good accuracy, moderate latency"
        assert result.failure_modes == ["timeout on long inputs"]
        assert len(result.per_sample_feedback) == 1

    def test_mutable_default_isolation(self) -> None:
        c1 = TrialConfig(trial_id="a")
        c2 = TrialConfig(trial_id="b")
        r1 = TrialResult(trial_id="a", config=c1)
        r2 = TrialResult(trial_id="b", config=c2)
        r1.failure_modes.append("error")
        r1.per_sample_feedback.append({"x": 1})
        assert r2.failure_modes == []
        assert r2.per_sample_feedback == []


# ---------------------------------------------------------------------------
# OptimizationRun
# ---------------------------------------------------------------------------


class TestOptimizationRun:
    """Tests for OptimizationRun dataclass."""

    def test_creation_defaults(self) -> None:
        space = SearchSpace()
        run = OptimizationRun(
            run_id="run-001",
            search_space=space,
        )
        assert run.run_id == "run-001"
        assert run.search_space is space
        assert run.trials == []
        assert run.best_trial is None
        assert run.best_recipe_path is None
        assert run.status == "running"
        assert run.optimizer_model == ""
        assert run.benchmark == ""
        assert run.pareto_frontier == []
        assert len(run.objectives) == 3  # DEFAULT_OBJECTIVES

    def test_creation_with_values(self) -> None:
        space = SearchSpace()
        config = TrialConfig(
            trial_id="t1",
            params={"agent.type": "orchestrator"},
        )
        result = TrialResult(
            trial_id="t1",
            config=config,
            accuracy=0.9,
        )
        run = OptimizationRun(
            run_id="run-002",
            search_space=space,
            trials=[result],
            best_trial=result,
            best_recipe_path="/tmp/best.toml",
            status="completed",
            optimizer_model="gpt-5-mini",
            benchmark="supergpqa",
        )
        assert len(run.trials) == 1
        assert run.best_trial is result
        assert run.best_recipe_path == "/tmp/best.toml"
        assert run.status == "completed"
        assert run.optimizer_model == "gpt-5-mini"
        assert run.benchmark == "supergpqa"

    def test_mutable_default_isolation(self) -> None:
        space = SearchSpace()
        r1 = OptimizationRun(run_id="a", search_space=space)
        r2 = OptimizationRun(run_id="b", search_space=space)
        r1.trials.append(
            TrialResult(
                trial_id="t",
                config=TrialConfig(trial_id="t"),
            ),
        )
        assert r2.trials == []


# ---------------------------------------------------------------------------
# SampleScore
# ---------------------------------------------------------------------------


class TestSampleScore:
    """Tests for SampleScore dataclass."""

    def test_creation(self) -> None:
        ss = SampleScore(
            record_id="r1",
            is_correct=True,
            score=1.0,
            latency_seconds=0.5,
        )
        assert ss.record_id == "r1"
        assert ss.is_correct is True
        assert ss.score == 1.0
        assert ss.latency_seconds == 0.5

    def test_defaults(self) -> None:
        ss = SampleScore(record_id="r0")
        assert ss.record_id == "r0"
        assert ss.is_correct is None
        assert ss.score is None
        assert ss.latency_seconds == 0.0
        assert ss.prompt_tokens == 0
        assert ss.completion_tokens == 0
        assert ss.cost_usd == 0.0
        assert ss.error is None
        assert ss.ttft == 0.0
        assert ss.energy_joules == 0.0
        assert ss.power_watts == 0.0
        assert ss.gpu_utilization_pct == 0.0
        assert ss.throughput_tok_per_sec == 0.0
        assert ss.mfu_pct == 0.0
        assert ss.mbu_pct == 0.0
        assert ss.ipw == 0.0
        assert ss.ipj == 0.0
        assert ss.energy_per_output_token_joules == 0.0
        assert ss.throughput_per_watt == 0.0
        assert ss.mean_itl_ms == 0.0


# ---------------------------------------------------------------------------
# TrialFeedback
# ---------------------------------------------------------------------------


class TestTrialFeedback:
    """Tests for TrialFeedback dataclass."""

    def test_creation(self) -> None:
        fb = TrialFeedback(
            summary_text="Trial showed strong accuracy but high latency.",
            failure_patterns=["timeout on long inputs", "hallucination"],
            primitive_ratings={"intelligence": "good", "agent": "needs work"},
            suggested_changes=["lower temperature", "increase max_turns"],
            target_primitive="agent",
        )
        assert fb.summary_text == "Trial showed strong accuracy but high latency."
        assert fb.failure_patterns == ["timeout on long inputs", "hallucination"]
        assert fb.primitive_ratings == {"intelligence": "good", "agent": "needs work"}
        assert fb.suggested_changes == ["lower temperature", "increase max_turns"]
        assert fb.target_primitive == "agent"

    def test_defaults(self) -> None:
        fb = TrialFeedback()
        assert fb.summary_text == ""
        assert fb.failure_patterns == []
        assert fb.primitive_ratings == {}
        assert fb.suggested_changes == []
        assert fb.target_primitive == ""

    def test_mutable_isolation(self) -> None:
        """Ensure mutable defaults are independent across instances."""
        fb1 = TrialFeedback()
        fb2 = TrialFeedback()
        fb1.failure_patterns.append("error")
        assert fb2.failure_patterns == []
