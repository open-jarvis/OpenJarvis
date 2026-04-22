"""Tests for the jarvis learning CLI subcommand group."""

from __future__ import annotations

from click.testing import CliRunner


class TestLearningCLI:
    def test_learning_group_exists(self) -> None:
        from openjarvis.learning.distillation.cli import learning_group

        runner = CliRunner()
        result = runner.invoke(learning_group, ["--help"])
        assert result.exit_code == 0
        out = result.output.lower()
        assert "learning" in out or "distillation" in out

    def test_init_subcommand(self) -> None:
        from openjarvis.learning.distillation.cli import learning_group

        runner = CliRunner()
        result = runner.invoke(learning_group, ["init", "--help"])
        assert result.exit_code == 0

    def test_run_subcommand(self) -> None:
        from openjarvis.learning.distillation.cli import learning_group

        runner = CliRunner()
        result = runner.invoke(learning_group, ["run", "--help"])
        assert result.exit_code == 0

    def test_history_subcommand(self) -> None:
        from openjarvis.learning.distillation.cli import learning_group

        runner = CliRunner()
        result = runner.invoke(learning_group, ["history", "--help"])
        assert result.exit_code == 0

    def test_rollback_subcommand(self) -> None:
        from openjarvis.learning.distillation.cli import learning_group

        runner = CliRunner()
        result = runner.invoke(learning_group, ["rollback", "--help"])
        assert result.exit_code == 0
