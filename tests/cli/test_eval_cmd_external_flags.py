"""Verify jarvis eval run exposes --base-url / --api-key for hermes/openclaw."""

from __future__ import annotations

from click.testing import CliRunner


class TestEvalCmdExternalFlags:
    def test_help_lists_external_backend_flags(self) -> None:
        from openjarvis.cli.eval_cmd import eval_run

        runner = CliRunner()
        result = runner.invoke(eval_run, ["--help"])
        assert result.exit_code == 0
        assert "--base-url" in result.output
        assert "--api-key" in result.output
        assert "hermes" in result.output

    def test_help_backend_choices_include_hermes_openclaw(self) -> None:
        from openjarvis.cli.eval_cmd import eval_run

        runner = CliRunner()
        result = runner.invoke(eval_run, ["--help"])
        assert result.exit_code == 0
        assert "hermes" in result.output
        assert "openclaw" in result.output
