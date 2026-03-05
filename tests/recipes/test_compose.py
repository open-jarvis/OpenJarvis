"""Tests for the unified compose system — enhanced Recipe, bridges, and discovery."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from openjarvis.recipes.loader import (
    Recipe,
    discover_recipes,
    load_recipe,
    resolve_recipe,
)

# -- Discrete recipe TOML -----------------------------------------------

DISCRETE_TOML = textwrap.dedent("""\
    [recipe]
    name = "bench-agent"
    kind = "discrete"
    description = "A discrete agent for benchmarking"
    version = "1.0.0"

    [intelligence]
    model = "qwen3:8b"
    quantization = "q4_K_M"
    provider = "ollama"

    [engine]
    key = "ollama"

    [agent]
    type = "native_react"
    max_turns = 20
    temperature = 0.2
    tools = ["shell_exec", "file_read", "think"]
    system_prompt = "You are a benchmark agent."

    [learning]
    routing = "heuristic"
    agent = "none"

    [eval]
    benchmarks = ["terminalbench", "gaia"]
    backend = "jarvis-agent"
    max_samples = 50
    judge_model = "gpt-4o"
""")

# -- Operator recipe TOML -----------------------------------------------

OPERATOR_TOML = textwrap.dedent("""\
    [recipe]
    name = "my-operator"
    kind = "operator"
    description = "A test operator"
    version = "2.0.0"

    [intelligence]
    model = "qwen3:8b"

    [engine]
    key = "ollama"

    [agent]
    type = "orchestrator"
    max_turns = 15
    temperature = 0.3
    tools = ["web_search", "memory_store", "think"]
    system_prompt = "You are a monitoring agent."

    [schedule]
    type = "interval"
    value = "600"

    [channels]
    output = ["slack", "telegram"]

    [learning]
    routing = "heuristic"
""")

# -- Legacy operator TOML -----------------------------------------------

LEGACY_OPERATOR_TOML = textwrap.dedent("""\
    [operator]
    name = "legacy-op"
    description = "A legacy operator manifest"
    version = "1.0.0"

    [operator.agent]
    max_turns = 10
    temperature = 0.4
    tools = ["think", "web_search"]
    system_prompt = "Legacy prompt."

    [operator.schedule]
    type = "cron"
    value = "0 */2 * * *"
""")


# ========================================================================
# Recipe loading
# ========================================================================


class TestLoadDiscreteRecipe:
    def test_load_discrete_fields(self, tmp_path: Path) -> None:
        p = tmp_path / "bench.toml"
        p.write_text(DISCRETE_TOML)
        r = load_recipe(p)

        assert r.name == "bench-agent"
        assert r.kind == "discrete"
        assert r.model == "qwen3:8b"
        assert r.quantization == "q4_K_M"
        assert r.provider == "ollama"
        assert r.engine_key == "ollama"
        assert r.agent_type == "native_react"
        assert r.max_turns == 20
        assert r.temperature == pytest.approx(0.2)
        assert r.tools == ["shell_exec", "file_read", "think"]
        assert r.system_prompt == "You are a benchmark agent."
        assert r.routing_policy == "heuristic"
        assert r.eval_benchmarks == ["terminalbench", "gaia"]
        assert r.eval_backend == "jarvis-agent"
        assert r.eval_max_samples == 50
        assert r.eval_judge_model == "gpt-4o"

    def test_default_kind_is_discrete(self, tmp_path: Path) -> None:
        p = tmp_path / "min.toml"
        p.write_text('[recipe]\nname = "min"\n[intelligence]\nmodel = "x"\n')
        r = load_recipe(p)
        assert r.kind == "discrete"


class TestLoadOperatorRecipe:
    def test_load_operator_fields(self, tmp_path: Path) -> None:
        p = tmp_path / "op.toml"
        p.write_text(OPERATOR_TOML)
        r = load_recipe(p)

        assert r.name == "my-operator"
        assert r.kind == "operator"
        assert r.schedule_type == "interval"
        assert r.schedule_value == "600"
        assert r.channels == ["slack", "telegram"]
        assert r.tools == ["web_search", "memory_store", "think"]

    def test_schedule_implies_operator_kind(self, tmp_path: Path) -> None:
        toml = textwrap.dedent("""\
            [recipe]
            name = "auto-op"

            [agent]
            type = "orchestrator"
            tools = ["think"]

            [schedule]
            type = "cron"
            value = "0 8 * * *"
        """)
        p = tmp_path / "auto.toml"
        p.write_text(toml)
        r = load_recipe(p)
        assert r.kind == "operator"

    def test_external_prompt_file(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("External prompt content.")

        toml = textwrap.dedent(f"""\
            [recipe]
            name = "ext-prompt"

            [agent]
            type = "simple"
            system_prompt_path = "{prompt_file}"
        """)
        p = tmp_path / "ext.toml"
        p.write_text(toml)
        r = load_recipe(p)
        assert r.system_prompt == "External prompt content."


class TestLoadLegacyOperator:
    def test_legacy_operator_converted_to_recipe(self, tmp_path: Path) -> None:
        p = tmp_path / "legacy.toml"
        p.write_text(LEGACY_OPERATOR_TOML)
        r = load_recipe(p)

        assert r.kind == "operator"
        assert r.name == "legacy-op"
        assert r.max_turns == 10
        assert r.temperature == pytest.approx(0.4)
        assert r.tools == ["think", "web_search"]
        assert r.system_prompt == "Legacy prompt."
        assert r.schedule_type == "cron"
        assert r.schedule_value == "0 */2 * * *"


# ========================================================================
# Discovery
# ========================================================================


class TestDiscoverByKind:
    def test_discover_all(self) -> None:
        all_recipes = discover_recipes()
        kinds = {r.kind for r in all_recipes}
        assert "discrete" in kinds
        assert len(all_recipes) >= 4  # at least original 3 + new ones

    def test_discover_discrete_only(self) -> None:
        discrete = discover_recipes(kind="discrete")
        for r in discrete:
            assert r.kind == "discrete"

    def test_discover_operator_only(self) -> None:
        operators = discover_recipes(kind="operator")
        for r in operators:
            assert r.kind == "operator"

    def test_discover_operators_subdir(self) -> None:
        """Operator recipes in data/operators/ are discovered."""
        all_recipes = discover_recipes()
        names = {r.name for r in all_recipes}
        # The new unified operator recipes should be found
        assert "twitter-sentinel" in names or "correspondent" in names

    def test_extra_dirs_discrete(self, tmp_path: Path) -> None:
        p = tmp_path / "custom.toml"
        p.write_text(DISCRETE_TOML)
        recipes = discover_recipes(extra_dirs=[tmp_path], kind="discrete")
        names = {r.name for r in recipes}
        assert "bench-agent" in names

    def test_extra_dirs_operator(self, tmp_path: Path) -> None:
        p = tmp_path / "custom_op.toml"
        p.write_text(OPERATOR_TOML)
        recipes = discover_recipes(extra_dirs=[tmp_path], kind="operator")
        names = {r.name for r in recipes}
        assert "my-operator" in names


# ========================================================================
# Bridge: to_eval_suite
# ========================================================================


class TestRecipeToEvalSuite:
    def test_basic_eval_suite(self, tmp_path: Path) -> None:
        p = tmp_path / "bench.toml"
        p.write_text(DISCRETE_TOML)
        r = load_recipe(p)

        suite = r.to_eval_suite()

        assert suite.meta.name == "bench-agent-eval"
        assert len(suite.models) == 1
        assert suite.models[0].name == "qwen3:8b"
        assert suite.models[0].engine == "ollama"
        assert len(suite.benchmarks) == 2
        bench_names = {b.name for b in suite.benchmarks}
        assert bench_names == {"terminalbench", "gaia"}
        for b in suite.benchmarks:
            assert b.backend == "jarvis-agent"
            assert b.agent == "native_react"
            assert b.tools == ["shell_exec", "file_read", "think"]
            assert b.max_samples == 50
            assert b.judge_model == "gpt-4o"

    def test_eval_suite_benchmark_override(self, tmp_path: Path) -> None:
        p = tmp_path / "bench.toml"
        p.write_text(DISCRETE_TOML)
        r = load_recipe(p)

        suite = r.to_eval_suite(benchmarks=["supergpqa"])

        assert len(suite.benchmarks) == 1
        assert suite.benchmarks[0].name == "supergpqa"

    def test_eval_suite_max_samples_override(self, tmp_path: Path) -> None:
        p = tmp_path / "bench.toml"
        p.write_text(DISCRETE_TOML)
        r = load_recipe(p)

        suite = r.to_eval_suite(max_samples=10)

        for b in suite.benchmarks:
            assert b.max_samples == 10

    def test_eval_suite_judge_override(self, tmp_path: Path) -> None:
        p = tmp_path / "bench.toml"
        p.write_text(DISCRETE_TOML)
        r = load_recipe(p)

        suite = r.to_eval_suite(judge_model="gpt-5")

        assert suite.judge.model == "gpt-5"
        for b in suite.benchmarks:
            assert b.judge_model == "gpt-5"

    def test_eval_suite_no_model_raises(self) -> None:
        r = Recipe(name="no-model", eval_benchmarks=["gaia"])
        with pytest.raises(ValueError, match="no model"):
            r.to_eval_suite()

    def test_eval_suite_no_benchmarks_raises(self) -> None:
        r = Recipe(name="no-bench", model="qwen3:8b")
        with pytest.raises(ValueError, match="no benchmarks"):
            r.to_eval_suite()

    def test_eval_suite_falls_back_to_suites(self) -> None:
        r = Recipe(
            name="suites-fallback",
            model="qwen3:8b",
            eval_suites=["coding"],
        )
        suite = r.to_eval_suite()
        assert len(suite.benchmarks) == 1
        assert suite.benchmarks[0].name == "coding"

    def test_eval_suite_direct_backend_when_no_agent(self) -> None:
        r = Recipe(
            name="direct",
            model="qwen3:8b",
            eval_benchmarks=["supergpqa"],
        )
        suite = r.to_eval_suite()
        assert suite.benchmarks[0].backend == "jarvis-direct"
        assert suite.benchmarks[0].agent is None
        assert suite.benchmarks[0].tools == []


# ========================================================================
# Bridge: to_operator_manifest
# ========================================================================


class TestRecipeToOperatorManifest:
    def test_basic_operator_manifest(self, tmp_path: Path) -> None:
        p = tmp_path / "op.toml"
        p.write_text(OPERATOR_TOML)
        r = load_recipe(p)

        m = r.to_operator_manifest()

        assert m.id == "my-operator"
        assert m.name == "my-operator"
        assert m.version == "2.0.0"
        assert m.description == "A test operator"
        assert m.tools == ["web_search", "memory_store", "think"]
        assert m.system_prompt == "You are a monitoring agent."
        assert m.max_turns == 15
        assert m.temperature == pytest.approx(0.3)
        assert m.schedule_type == "interval"
        assert m.schedule_value == "600"

    def test_operator_no_schedule_raises(self) -> None:
        r = Recipe(name="no-sched", kind="operator")
        with pytest.raises(ValueError, match="no \\[schedule\\]"):
            r.to_operator_manifest()

    def test_operator_defaults(self) -> None:
        r = Recipe(
            name="minimal-op",
            kind="operator",
            schedule_type="interval",
            schedule_value="300",
        )
        m = r.to_operator_manifest()
        assert m.max_turns == 20
        assert m.temperature == pytest.approx(0.3)
        assert m.schedule_value == "300"


# ========================================================================
# Builder kwargs with new fields
# ========================================================================


class TestBuilderKwargsNewFields:
    def test_provider_in_kwargs(self) -> None:
        r = Recipe(name="cloud", model="gpt-4o", provider="openai")
        kw = r.to_builder_kwargs()
        assert kw["provider"] == "openai"

    def test_system_prompt_path_resolved(self, tmp_path: Path) -> None:
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("Hello from file.")
        r = Recipe(
            name="ext",
            system_prompt_path=str(prompt),
        )
        kw = r.to_builder_kwargs()
        assert kw["system_prompt"] == "Hello from file."

    def test_schedule_and_channels_not_in_kwargs(self) -> None:
        """Schedule/channel fields are operator-specific and not builder kwargs."""
        r = Recipe(
            name="op",
            kind="operator",
            schedule_type="cron",
            schedule_value="0 * * * *",
            channels=["slack"],
        )
        kw = r.to_builder_kwargs()
        assert "schedule_type" not in kw
        assert "channels" not in kw


# ========================================================================
# Built-in recipe loading
# ========================================================================


class TestBuiltinRecipes:
    def test_terminalbench_react_loads(self) -> None:
        r = resolve_recipe("terminalbench-react")
        assert r is not None
        assert r.kind == "discrete"
        assert r.agent_type == "native_react"
        assert "terminalbench" in r.eval_benchmarks

    def test_gaia_orchestrator_loads(self) -> None:
        r = resolve_recipe("gaia-orchestrator")
        assert r is not None
        assert r.kind == "discrete"
        assert r.agent_type == "orchestrator"
        assert "gaia" in r.eval_benchmarks

    def test_swebench_openhands_loads(self) -> None:
        r = resolve_recipe("swebench-openhands")
        assert r is not None
        assert r.kind == "discrete"
        assert r.agent_type == "native_openhands"

    def test_coding_benchmark_loads(self) -> None:
        r = resolve_recipe("coding-benchmark")
        assert r is not None
        assert r.kind == "discrete"
        assert "terminalbench" in r.eval_benchmarks
        assert "swebench" in r.eval_benchmarks

    def test_twitter_sentinel_loads(self) -> None:
        r = resolve_recipe("twitter-sentinel")
        assert r is not None
        assert r.kind == "operator"
        assert r.schedule_type == "interval"

    def test_inbox_triage_loads(self) -> None:
        r = resolve_recipe("inbox-triage")
        assert r is not None
        assert r.kind == "operator"
        assert r.schedule_type == "interval"

    def test_news_briefing_loads(self) -> None:
        r = resolve_recipe("news-briefing")
        assert r is not None
        assert r.kind == "operator"
        assert r.schedule_type == "cron"

    def test_repo_watcher_loads(self) -> None:
        r = resolve_recipe("repo-watcher")
        assert r is not None
        assert r.kind == "operator"
        assert r.schedule_type == "interval"
