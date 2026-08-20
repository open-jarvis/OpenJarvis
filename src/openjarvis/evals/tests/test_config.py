"""Tests for eval suite config loading and matrix expansion."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from openjarvis.evals.core.config import EvalConfigError, expand_suite, load_eval_config
from openjarvis.evals.core.types import (
    BenchmarkConfig,
    DefaultsConfig,
    EvalSuiteConfig,
    ExecutionConfig,
    JudgeConfig,
    MetaConfig,
    ModelConfig,
    RunConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, content: str) -> Path:
    """Write a TOML string to a temp file and return its path."""
    p = tmp_path / "suite.toml"
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------


class TestDataclassDefaults:
    def test_meta_config_defaults(self):
        m = MetaConfig()
        assert m.name == ""
        assert m.description == ""

    def test_defaults_config_defaults(self):
        d = DefaultsConfig()
        assert d.temperature == 0.0
        assert d.max_tokens == 2048

    def test_judge_config_defaults(self):
        j = JudgeConfig()
        assert j.model == "gpt-5-mini-2025-08-07"
        assert j.provider is None
        assert j.temperature == 0.0
        assert j.max_tokens == 1024

    def test_execution_config_defaults(self):
        e = ExecutionConfig()
        assert e.max_workers == 4
        assert e.output_dir == "results/"
        assert e.seed == 42

    def test_model_config_defaults(self):
        m = ModelConfig(name="test")
        assert m.engine is None
        assert m.provider is None
        assert m.temperature is None
        assert m.max_tokens is None
        assert m.param_count_b == 0.0
        assert m.active_params_b is None
        assert m.gpu_peak_tflops == 0.0
        assert m.gpu_peak_bandwidth_gb_s == 0.0
        assert m.num_gpus == 1

    def test_benchmark_config_defaults(self):
        b = BenchmarkConfig(name="supergpqa")
        assert b.backend == "jarvis-direct"
        assert b.max_samples is None
        assert b.split is None
        assert b.agent is None
        assert b.tools == []
        assert b.judge_model is None
        assert b.temperature is None
        assert b.max_tokens is None

    def test_eval_suite_config_defaults(self):
        s = EvalSuiteConfig()
        assert s.meta.name == ""
        assert s.defaults.temperature == 0.0
        assert s.judge.model == "gpt-5-mini-2025-08-07"
        assert s.run.max_workers == 4
        assert s.models == []
        assert s.benchmarks == []


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


class TestLoadEvalConfig:
    def test_minimal_config(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        suite = load_eval_config(p)
        assert len(suite.models) == 1
        assert suite.models[0].name == "qwen3:8b"
        assert len(suite.benchmarks) == 1
        assert suite.benchmarks[0].name == "supergpqa"
        # Defaults should be applied
        assert suite.defaults.temperature == 0.0
        assert suite.judge.model == "gpt-5-mini-2025-08-07"

    def test_full_config(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [meta]
            name = "test-suite"
            description = "A test suite"

            [defaults]
            temperature = 0.5
            max_tokens = 4096

            [judge]
            model = "claude-sonnet"
            temperature = 0.1
            max_tokens = 512

            [run]
            max_workers = 8
            output_dir = "out/"
            seed = 123

            [[models]]
            name = "model-a"
            engine = "ollama"
            temperature = 0.3

            [[models]]
            name = "model-b"
            provider = "openai"

            [[benchmarks]]
            name = "supergpqa"
            backend = "jarvis-direct"
            max_samples = 100
            split = "test"

            [[benchmarks]]
            name = "gaia"
            backend = "jarvis-agent"
            agent = "orchestrator"
            tools = ["calc", "think"]
            judge_model = "gpt-4o"
        """,
        )
        suite = load_eval_config(p)
        assert suite.meta.name == "test-suite"
        assert suite.meta.description == "A test suite"
        assert suite.defaults.temperature == 0.5
        assert suite.defaults.max_tokens == 4096
        assert suite.judge.model == "claude-sonnet"
        assert suite.judge.temperature == 0.1
        assert suite.run.max_workers == 8
        assert suite.run.output_dir == "out/"
        assert suite.run.seed == 123

        assert len(suite.models) == 2
        assert suite.models[0].name == "model-a"
        assert suite.models[0].engine == "ollama"
        assert suite.models[0].temperature == 0.3
        assert suite.models[1].name == "model-b"
        assert suite.models[1].provider == "openai"

        assert len(suite.benchmarks) == 2
        assert suite.benchmarks[0].max_samples == 100
        assert suite.benchmarks[0].split == "test"
        assert suite.benchmarks[1].agent == "orchestrator"
        assert suite.benchmarks[1].tools == ["calc", "think"]
        assert suite.benchmarks[1].judge_model == "gpt-4o"

    def test_missing_models_raises(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        with pytest.raises(EvalConfigError, match="at least one \\[\\[models\\]\\]"):
            load_eval_config(p)

    def test_missing_benchmarks_raises(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"
        """,
        )
        with pytest.raises(
            EvalConfigError,
            match="at least one \\[\\[benchmarks\\]\\]",
        ):
            load_eval_config(p)

    def test_model_without_name_raises(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            engine = "ollama"

            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        with pytest.raises(EvalConfigError, match="'name' field"):
            load_eval_config(p)

    def test_benchmark_without_name_raises(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            backend = "jarvis-direct"
        """,
        )
        with pytest.raises(EvalConfigError, match="'name' field"):
            load_eval_config(p)

    def test_invalid_backend_raises(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            name = "supergpqa"
            backend = "invalid-backend"
        """,
        )
        with pytest.raises(EvalConfigError, match="Invalid backend"):
            load_eval_config(p)

    def test_unknown_benchmark_warns(self, tmp_path, caplog):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            name = "custom-bench"
        """,
        )
        import logging

        with caplog.at_level(logging.WARNING):
            suite = load_eval_config(p)
        assert suite.benchmarks[0].name == "custom-bench"
        assert "Unknown benchmark name" in caplog.text

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_eval_config("/nonexistent/path.toml")

    def test_malformed_toml(self, tmp_path):
        p = tmp_path / "bad.toml"
        p.write_text("[[[ invalid toml")
        with pytest.raises(Exception):  # tomllib raises various errors
            load_eval_config(p)

    def test_empty_models_list(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            models = []

            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        with pytest.raises(EvalConfigError, match="at least one \\[\\[models\\]\\]"):
            load_eval_config(p)

    def test_empty_benchmarks_list(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"

            benchmarks = []
        """,
        )
        with pytest.raises(
            EvalConfigError,
            match="at least one \\[\\[benchmarks\\]\\]",
        ):
            load_eval_config(p)

    def test_model_hardware_params(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "GLM-4.7-Flash"
            engine = "vllm"
            param_count_b = 30.0
            active_params_b = 3.0
            gpu_peak_tflops = 312.0
            gpu_peak_bandwidth_gb_s = 2039.0
            num_gpus = 4

            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        suite = load_eval_config(p)
        m = suite.models[0]
        assert m.param_count_b == 30.0
        assert m.active_params_b == 3.0
        assert m.gpu_peak_tflops == 312.0
        assert m.gpu_peak_bandwidth_gb_s == 2039.0
        assert m.num_gpus == 4

    def test_model_hardware_params_defaults(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        suite = load_eval_config(p)
        m = suite.models[0]
        assert m.param_count_b == 0.0
        assert m.active_params_b is None
        assert m.gpu_peak_tflops == 0.0
        assert m.gpu_peak_bandwidth_gb_s == 0.0
        assert m.num_gpus == 1

    def test_telemetry_config(self, tmp_path):
        p = _write_toml(
            tmp_path,
            """\
            [run]
            telemetry = true
            gpu_metrics = true

            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            name = "supergpqa"
        """,
        )
        suite = load_eval_config(p)
        assert suite.run.telemetry is True
        assert suite.run.gpu_metrics is True


# ---------------------------------------------------------------------------
# Example config files load correctly
# ---------------------------------------------------------------------------


class TestExampleConfigs:
    @pytest.fixture(
        params=[
            "minimal.toml",
            "single-run.toml",
            "full-suite.toml",
            "glm-4.7-flash-openhands.toml",
            "glm-4.7-flash-openhands-remaining.toml",
        ]
    )
    def example_config(self, request):
        configs_dir = Path(__file__).resolve().parent.parent / "configs"
        return configs_dir / request.param

    def test_example_configs_load(self, example_config):
        suite = load_eval_config(example_config)
        assert len(suite.models) >= 1
        assert len(suite.benchmarks) >= 1

    def test_full_suite_dimensions(self):
        configs_dir = Path(__file__).resolve().parent.parent / "configs"
        suite = load_eval_config(configs_dir / "full-suite.toml")
        assert len(suite.models) == 3
        assert len(suite.benchmarks) == 4


# ---------------------------------------------------------------------------
# Matrix expansion
# ---------------------------------------------------------------------------


class TestExpandSuite:
    def test_single_model_single_benchmark(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert len(configs) == 1
        assert configs[0].model == "m1"
        assert configs[0].benchmark == "supergpqa"

    def test_cross_product(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1"), ModelConfig(name="m2")],
            benchmarks=[
                BenchmarkConfig(name="supergpqa"),
                BenchmarkConfig(name="gaia"),
                BenchmarkConfig(name="frames"),
            ],
        )
        configs = expand_suite(suite)
        assert len(configs) == 6  # 2 x 3

    def test_temperature_merge_defaults(self):
        suite = EvalSuiteConfig(
            defaults=DefaultsConfig(temperature=0.5),
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].temperature == 0.5

    def test_temperature_model_overrides_defaults(self):
        suite = EvalSuiteConfig(
            defaults=DefaultsConfig(temperature=0.5),
            models=[ModelConfig(name="m1", temperature=0.3)],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].temperature == 0.3

    def test_temperature_benchmark_overrides_model(self):
        suite = EvalSuiteConfig(
            defaults=DefaultsConfig(temperature=0.5),
            models=[ModelConfig(name="m1", temperature=0.3)],
            benchmarks=[BenchmarkConfig(name="supergpqa", temperature=0.9)],
        )
        configs = expand_suite(suite)
        assert configs[0].temperature == 0.9

    def test_max_tokens_merge_precedence(self):
        suite = EvalSuiteConfig(
            defaults=DefaultsConfig(max_tokens=1000),
            models=[ModelConfig(name="m1", max_tokens=2000)],
            benchmarks=[BenchmarkConfig(name="supergpqa", max_tokens=3000)],
        )
        configs = expand_suite(suite)
        assert configs[0].max_tokens == 3000

    def test_max_tokens_model_only(self):
        suite = EvalSuiteConfig(
            defaults=DefaultsConfig(max_tokens=1000),
            models=[ModelConfig(name="m1", max_tokens=2000)],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].max_tokens == 2000

    def test_judge_model_from_judge_config(self):
        suite = EvalSuiteConfig(
            judge=JudgeConfig(model="custom-judge"),
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].judge_model == "custom-judge"

    def test_judge_model_benchmark_override(self):
        suite = EvalSuiteConfig(
            judge=JudgeConfig(model="default-judge"),
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa", judge_model="bench-judge")],
        )
        configs = expand_suite(suite)
        assert configs[0].judge_model == "bench-judge"

    def test_output_path_auto_generated(self):
        suite = EvalSuiteConfig(
            run=ExecutionConfig(output_dir="out/"),
            models=[ModelConfig(name="qwen3:8b")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].output_path == "out/supergpqa_qwen3-8b.jsonl"

    def test_output_path_model_slug(self):
        suite = EvalSuiteConfig(
            run=ExecutionConfig(output_dir="results"),
            models=[ModelConfig(name="org/model:v2")],
            benchmarks=[BenchmarkConfig(name="gaia")],
        )
        configs = expand_suite(suite)
        assert configs[0].output_path == "results/gaia_org-model-v2.jsonl"

    def test_engine_key_from_model(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1", engine="ollama")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].engine_key == "ollama"

    def test_agent_from_benchmark(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="gaia", agent="orchestrator")],
        )
        configs = expand_suite(suite)
        assert configs[0].agent_name == "orchestrator"

    def test_tools_from_benchmark(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="gaia", tools=["calc", "think"])],
        )
        configs = expand_suite(suite)
        assert configs[0].tools == ["calc", "think"]

    def test_tools_list_not_shared(self):
        """Each RunConfig should get its own tools list (no shared mutation)."""
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1"), ModelConfig(name="m2")],
            benchmarks=[BenchmarkConfig(name="gaia", tools=["calc"])],
        )
        configs = expand_suite(suite)
        configs[0].tools.append("extra")
        assert configs[1].tools == ["calc"]

    def test_max_workers_and_seed_from_run(self):
        suite = EvalSuiteConfig(
            run=ExecutionConfig(max_workers=16, seed=99),
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].max_workers == 16
        assert configs[0].seed == 99

    def test_max_samples_and_split_from_benchmark(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[
                BenchmarkConfig(name="supergpqa", max_samples=50, split="test")
            ],
        )
        configs = expand_suite(suite)
        assert configs[0].max_samples == 50
        assert configs[0].dataset_split == "test"

    def test_backend_from_benchmark(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="gaia", backend="jarvis-agent")],
        )
        configs = expand_suite(suite)
        assert configs[0].backend == "jarvis-agent"

    def test_expand_returns_run_config_type(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert all(isinstance(c, RunConfig) for c in configs)

    def test_metadata_from_model_hardware_params(self):
        suite = EvalSuiteConfig(
            models=[
                ModelConfig(
                    name="GLM-4.7-Flash",
                    engine="vllm",
                    param_count_b=30.0,
                    active_params_b=3.0,
                    gpu_peak_tflops=312.0,
                    gpu_peak_bandwidth_gb_s=2039.0,
                    num_gpus=4,
                )
            ],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        meta = configs[0].metadata
        assert meta["param_count_b"] == 30.0
        assert meta["active_params_b"] == 3.0
        assert meta["gpu_peak_tflops"] == 312.0
        assert meta["gpu_peak_bandwidth_gb_s"] == 2039.0
        assert meta["num_gpus"] == 4

    def test_metadata_empty_when_no_hardware_params(self):
        suite = EvalSuiteConfig(
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].metadata == {}

    def test_metadata_partial_hardware_params(self):
        suite = EvalSuiteConfig(
            models=[
                ModelConfig(
                    name="m1",
                    param_count_b=7.0,
                    gpu_peak_tflops=100.0,
                )
            ],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        meta = configs[0].metadata
        assert meta["param_count_b"] == 7.0
        assert meta["gpu_peak_tflops"] == 100.0
        assert "active_params_b" not in meta  # None → omitted
        assert "num_gpus" not in meta  # 1 → omitted (default)

    def test_telemetry_flags_propagated(self):
        suite = EvalSuiteConfig(
            run=ExecutionConfig(telemetry=True, gpu_metrics=True),
            models=[ModelConfig(name="m1")],
            benchmarks=[BenchmarkConfig(name="supergpqa")],
        )
        configs = expand_suite(suite)
        assert configs[0].telemetry is True
        assert configs[0].gpu_metrics is True


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIConfig:
    def test_run_missing_benchmark_and_config(self):
        from click.testing import CliRunner

        from openjarvis.evals.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "-m", "qwen3:8b"])
        assert result.exit_code != 0
        assert "--benchmark" in result.output or "benchmark" in result.output.lower()

    def test_run_missing_model_and_config(self):
        from click.testing import CliRunner

        from openjarvis.evals.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "-b", "supergpqa"])
        assert result.exit_code != 0
        assert "--model" in result.output or "model" in result.output.lower()

    def test_run_config_file_not_found(self):
        from click.testing import CliRunner

        from openjarvis.evals.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--config", "/nonexistent.toml"])
        assert result.exit_code != 0

    def test_run_config_loads_and_prints_suite_info(self, tmp_path):
        """Verify --config loads config and prints suite header.

        We don't actually run the eval (requires backends), but we verify
        the config is loaded and the matrix expansion starts.
        """
        from unittest.mock import patch

        from click.testing import CliRunner

        from openjarvis.evals.cli import main

        p = _write_toml(
            tmp_path,
            """\
            [meta]
            name = "test-suite"

            [[models]]
            name = "qwen3:8b"

            [[benchmarks]]
            name = "supergpqa"
        """,
        )

        runner = CliRunner()
        with patch("openjarvis.evals.cli._run_single", side_effect=Exception("mock")):
            result = runner.invoke(main, ["run", "--config", str(p)])

        # Should print suite info before failing
        assert "test-suite" in result.output
        assert "1 model(s) x 1 benchmark(s)" in result.output
