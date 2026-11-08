"""Tests for the ``friday workflow`` CLI commands."""

from __future__ import annotations

from click.testing import CliRunner

from friday_ai.cli import cli


class TestWorkflowCmd:
    def test_workflow_list_help(self) -> None:
        result = CliRunner().invoke(cli, ["workflow", "list", "--help"])
        assert result.exit_code == 0

    def test_workflow_run_help(self) -> None:
        result = CliRunner().invoke(cli, ["workflow", "run", "--help"])
        assert result.exit_code == 0

    def test_workflow_status_help(self) -> None:
        result = CliRunner().invoke(cli, ["workflow", "status", "--help"])
        assert result.exit_code == 0

    def test_workflow_group_help(self) -> None:
        result = CliRunner().invoke(cli, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "run" in result.output
        assert "status" in result.output
