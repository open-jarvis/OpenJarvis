"""Tests for openjarvis.evals.backends.external.hermes_agent.HermesBackend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.evals.backends.external._subprocess_runner import SubprocessResult
from openjarvis.evals.backends.external.hermes_agent import HermesBackend
from openjarvis.evals.comparison.third_party import (
    CommitDriftError,
    ThirdPartyConfig,
    ThirdPartyEntry,
)


def _fake_third_party(tmp_path: Path) -> ThirdPartyConfig:
    return ThirdPartyConfig(
        entries={
            "hermes": ThirdPartyEntry(
                name="hermes",
                path=tmp_path,
                pinned_commit="abc123",
                runner_script=(
                    "src/openjarvis/evals/backends/external/_runners/hermes_runner.py"
                ),
                python_executable="",
            )
        }
    )


class TestHermesBackend:
    def test_generate_full_builds_correct_subprocess_command(
        self, tmp_path: Path
    ) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.hermes_agent.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.verify_commit_pin",
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.run_one_shot",
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
                    "content": "answer",
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                    "trajectory": [],
                    "tool_calls": 2,
                    "turn_count": 3,
                    "error": None,
                },
                error=None,
            )
            backend = HermesBackend(base_url="http://x", api_key="k")
            backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )

            cmd = mock_run.call_args.kwargs["cmd"]
            assert "--task" in cmd and "task" in cmd
            assert "--model" in cmd and "qwen-9b" in cmd
            assert "--base-url" in cmd and "http://x" in cmd
            assert "--api-key" in cmd and "k" in cmd

    def test_generate_full_returns_extended_dict(self, tmp_path: Path) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.hermes_agent.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.verify_commit_pin",
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.run_one_shot",
            ) as mock_run,
        ):
            mock_run.return_value = SubprocessResult(
                stdout="",
                stderr="",
                exit_code=0,
                latency_seconds=2.5,
                energy_joules=42.0,
                peak_power_w=20.0,
                sampler_method="nvml",
                parsed_json={
                    "content": "answer",
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                    },
                    "trajectory": [],
                    "tool_calls": 2,
                    "turn_count": 3,
                    "error": None,
                },
                error=None,
            )
            backend = HermesBackend(base_url="http://x", api_key="k")
            result = backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )
            assert result["content"] == "answer"
            assert result["energy_joules"] == 42.0
            assert result["peak_power_w"] == 20.0
            assert result["tool_calls"] == 2
            assert result["turn_count"] == 3
            assert result["framework"] == "hermes"
            assert result["framework_commit"] == "abc123"
            assert result["error"] is None

    def test_generate_full_propagates_subprocess_error(self, tmp_path: Path) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.hermes_agent.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.verify_commit_pin",
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.run_one_shot",
            ) as mock_run,
        ):
            mock_run.return_value = SubprocessResult(
                stdout="",
                stderr="boom",
                exit_code=139,
                latency_seconds=0.5,
                energy_joules=None,
                peak_power_w=None,
                sampler_method="unavailable",
                parsed_json={},
                error="subprocess_crash",
            )
            backend = HermesBackend(base_url="http://x", api_key="k")
            result = backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )
            assert result["error"] == "subprocess_crash"
            assert result["content"] == ""

    def test_init_raises_on_commit_drift(self, tmp_path: Path) -> None:
        cfg = _fake_third_party(tmp_path)
        with (
            patch(
                "openjarvis.evals.backends.external.hermes_agent.load_third_party_config",
                return_value=cfg,
            ),
            patch(
                "openjarvis.evals.backends.external.hermes_agent.verify_commit_pin",
                side_effect=CommitDriftError("drift!"),
            ),
        ):
            with pytest.raises(CommitDriftError, match="drift"):
                HermesBackend(base_url="http://x", api_key="k")
