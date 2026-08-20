"""Tests for openjarvis.evals.backends.external.openclaw.OpenClawBackend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.evals.backends.external._subprocess_runner import SubprocessResult
from openjarvis.evals.backends.external.openclaw import OpenClawBackend
from openjarvis.evals.comparison.third_party import (
    CommitDriftError,
    ThirdPartyConfig,
    ThirdPartyEntry,
)


def _fake_third_party(tmp_path: Path) -> ThirdPartyConfig:
    return ThirdPartyConfig(
        entries={
            "openclaw": ThirdPartyEntry(
                name="openclaw",
                path=tmp_path,
                pinned_commit="def456",
                runner_script=(
                    "src/openjarvis/evals/backends/external/_runners/openclaw_runner.mjs"
                ),
                node_executable="",
            )
        }
    )


class TestOpenClawBackend:
    def test_generate_full_builds_correct_subprocess_command(
        self, tmp_path: Path
    ) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.openclaw.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.verify_commit_pin",
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.run_one_shot",
            ) as mock_run,
        ):
            mock_run.return_value = SubprocessResult(
                stdout="",
                stderr="",
                exit_code=0,
                latency_seconds=1.0,
                energy_joules=10.0,
                peak_power_w=5.0,
                sampler_method="nvml",
                parsed_json={
                    "content": "x",
                    "usage": {},
                    "trajectory": [],
                    "tool_calls": 0,
                    "turn_count": 0,
                    "error": None,
                },
                error=None,
            )
            backend = OpenClawBackend(base_url="http://x", api_key="k")
            backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )
            cmd = mock_run.call_args.kwargs["cmd"]
            # First element should be the node executable (or "node")
            assert cmd[0] == "node"
            assert "--task" in cmd and "task" in cmd
            assert "--model" in cmd and "qwen-9b" in cmd

    def test_generate_full_returns_extended_dict(self, tmp_path: Path) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.openclaw.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.verify_commit_pin",
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.run_one_shot",
            ) as mock_run,
        ):
            mock_run.return_value = SubprocessResult(
                stdout="",
                stderr="",
                exit_code=0,
                latency_seconds=3.0,
                energy_joules=99.0,
                peak_power_w=30.0,
                sampler_method="nvml",
                parsed_json={
                    "content": "answer",
                    "usage": {"total_tokens": 100},
                    "trajectory": [],
                    "tool_calls": 1,
                    "turn_count": 2,
                    "error": None,
                },
                error=None,
            )
            backend = OpenClawBackend(base_url="http://x", api_key="k")
            result = backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )
            assert result["content"] == "answer"
            assert result["framework"] == "openclaw"
            assert result["framework_commit"] == "def456"
            assert result["energy_joules"] == 99.0

    def test_generate_full_propagates_subprocess_error(self, tmp_path: Path) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.openclaw.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.verify_commit_pin",
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.run_one_shot",
            ) as mock_run,
        ):
            mock_run.return_value = SubprocessResult(
                stdout="",
                stderr="boom",
                exit_code=1,
                latency_seconds=0.1,
                energy_joules=None,
                peak_power_w=None,
                sampler_method="unavailable",
                parsed_json={},
                error="subprocess_crash",
            )
            backend = OpenClawBackend(base_url="http://x", api_key="k")
            result = backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )
            assert result["error"] == "subprocess_crash"

    def test_init_raises_on_commit_drift(self, tmp_path: Path) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.openclaw.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.openclaw.verify_commit_pin",
                side_effect=CommitDriftError("drift!"),
            ),
        ):
            with pytest.raises(CommitDriftError, match="drift"):
                OpenClawBackend(base_url="http://x", api_key="k")
