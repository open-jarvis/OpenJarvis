"""Tests for eval CLI display flags."""

from __future__ import annotations

from click.testing import CliRunner

from friday_ai.evals.cli import main


class TestCompactFlag:
    def test_compact_flag_accepted(self):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "--compact" in result.output

    def test_trace_detail_flag_accepted(self):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "--trace-detail" in result.output
