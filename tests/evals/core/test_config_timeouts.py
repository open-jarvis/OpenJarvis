"""Tests for terminal-bench harness timeout plumbing through TOML configs."""

from __future__ import annotations

import textwrap

from openjarvis.evals.core.config import expand_suite, load_eval_config


def _write(tmp_path, body: str):
    path = tmp_path / "suite.toml"
    path.write_text(textwrap.dedent(body))
    return path


BASE = """
    [meta]
    name = "timeouts"

    [run]
    output_dir = "results/"
    {run_extra}

    [[models]]
    name = "test-model"

    [[benchmarks]]
    name = "terminalbench-native"
    backend = "terminalbench-native"
    {bench_extra}
"""


class TestTimeoutConfigPlumbing:
    def test_run_level_timeouts_parse_and_expand(self, tmp_path):
        path = _write(
            tmp_path,
            BASE.format(
                run_extra=(
                    "global_agent_timeout_sec = 1200\n"
                    "    global_timeout_multiplier = 1.5"
                ),
                bench_extra="",
            ),
        )
        suite = load_eval_config(path)
        assert suite.run.global_agent_timeout_sec == 1200.0
        assert suite.run.global_timeout_multiplier == 1.5

        (rc,) = expand_suite(suite)
        assert rc.global_agent_timeout_sec == 1200.0
        assert rc.global_timeout_multiplier == 1.5

    def test_benchmark_override_wins(self, tmp_path):
        path = _write(
            tmp_path,
            BASE.format(
                run_extra="global_agent_timeout_sec = 1200",
                bench_extra="global_agent_timeout_sec = 300",
            ),
        )
        (rc,) = expand_suite(load_eval_config(path))
        assert rc.global_agent_timeout_sec == 300.0

    def test_defaults_are_none(self, tmp_path):
        path = _write(tmp_path, BASE.format(run_extra="", bench_extra=""))
        suite = load_eval_config(path)
        assert suite.run.global_agent_timeout_sec is None
        assert suite.run.global_timeout_multiplier is None
        (rc,) = expand_suite(suite)
        assert rc.global_agent_timeout_sec is None
        assert rc.global_timeout_multiplier is None
