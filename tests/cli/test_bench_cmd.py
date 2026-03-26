"""Tests for the ``jarvis bench`` CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli import cli


class TestBenchCLI:
    def test_bench_group_in_help(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "bench" in result.output

    def test_run_help(self):
        result = CliRunner().invoke(cli, ["bench", "run", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--samples" in result.output

    def test_run_no_engine_error(self):
        with patch("openjarvis.cli.bench_cmd.get_engine", return_value=None):
            result = CliRunner().invoke(cli, ["bench", "run"])
        assert result.exit_code != 0

    def test_run_with_mock(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.list_models.return_value = ["test-model"]
        engine.generate.return_value = {
            "content": "Hello",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        with patch(
            "openjarvis.cli.bench_cmd.get_engine",
            return_value=("mock", engine),
        ):
            result = CliRunner().invoke(cli, ["bench", "run", "-n", "2"])
        assert result.exit_code == 0

    def test_json_output(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.list_models.return_value = ["test-model"]
        engine.generate.return_value = {
            "content": "Hello",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        with patch(
            "openjarvis.cli.bench_cmd.get_engine",
            return_value=("mock", engine),
        ):
            result = CliRunner().invoke(
                cli,
                ["bench", "run", "-n", "2", "--json"],
            )
        assert result.exit_code == 0
        assert "benchmark_count" in result.output

    def test_output_to_file(self, tmp_path):
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.list_models.return_value = ["test-model"]
        engine.generate.return_value = {
            "content": "Hello",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        out_file = tmp_path / "results.jsonl"
        with patch(
            "openjarvis.cli.bench_cmd.get_engine",
            return_value=("mock", engine),
        ):
            result = CliRunner().invoke(
                cli,
                ["bench", "run", "-n", "2", "-o", str(out_file)],
            )
        assert result.exit_code == 0
        assert out_file.exists()
