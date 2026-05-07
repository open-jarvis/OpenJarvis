"""Integration tests that spawn real Hermes/OpenClaw subprocesses.

Requires:
- $HERMES_AGENT_PATH set and pointing to the pinned commit
- $OPENCLAW_PATH set and pointing to the pinned commit
- An OpenAI-compatible mock server reachable at $JARVIS_MOCK_LLM_URL

Skipped by default. Run via:
    uv run pytest tests/evals/comparison/test_live_external.py -m live_external -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_external


def _have_env() -> bool:
    return bool(os.environ.get("HERMES_AGENT_PATH")) and bool(
        os.environ.get("OPENCLAW_PATH")
    )


@pytest.mark.skipif(
    not _have_env(),
    reason="HERMES_AGENT_PATH or OPENCLAW_PATH not set",
)
class TestLiveExternal:
    def test_hermes_runner_emits_valid_json(self, tmp_path: Path) -> None:
        runner = (
            Path(__file__).resolve().parents[3]
            / "src/openjarvis/evals/backends/external/_runners/hermes_runner.py"
        )
        out_json = tmp_path / "out.json"
        env = dict(os.environ)
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "--task",
                "Say hello.",
                "--model",
                "test",
                "--base-url",
                os.environ.get("JARVIS_MOCK_LLM_URL", "http://localhost:8000/v1"),
                "--api-key",
                "dummy",
                "--api-mode",
                "chat_completions",
                "--output-json",
                str(out_json),
                "--max-iterations",
                "3",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert out_json.exists(), f"runner did not emit output. stderr={result.stderr}"
        data = json.loads(out_json.read_text())
        assert "content" in data
        assert "usage" in data
        assert "tool_calls" in data
        assert "turn_count" in data

    def test_openclaw_runner_emits_valid_json(self, tmp_path: Path) -> None:
        runner = (
            Path(__file__).resolve().parents[3]
            / "src/openjarvis/evals/backends/external/_runners/openclaw_runner.mjs"
        )
        if not runner.exists():
            pytest.skip("openclaw_runner.mjs not present")
        out_json = tmp_path / "out.json"
        env = dict(os.environ)
        result = subprocess.run(
            [
                "node",
                str(runner),
                "--task",
                "Say hello.",
                "--model",
                "test",
                "--base-url",
                os.environ.get("JARVIS_MOCK_LLM_URL", "http://localhost:8000/v1"),
                "--api-key",
                "dummy",
                "--output-json",
                str(out_json),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert out_json.exists(), f"runner did not emit output. stderr={result.stderr}"
        data = json.loads(out_json.read_text())
        assert "content" in data

    def test_end_to_end_runs_one_config(self, tmp_path: Path) -> None:
        """Run one full benchmark cell via the CLI; verify summary.json shape."""
        pytest.skip(
            "Requires full eval-CLI integration; enable when Layer 2 wiring stable."
        )
