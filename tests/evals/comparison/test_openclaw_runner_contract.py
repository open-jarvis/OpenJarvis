"""Contract tests for the OpenClaw subprocess runner."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_openclaw_runner_parses_real_agent_json_shape(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")

    fake_openclaw = tmp_path / "openclaw.mjs"
    fake_openclaw.write_text(
        "\n".join(
            [
                "console.log(JSON.stringify({",
                "  payloads: [{ text: 'hello from openclaw', mediaUrl: null }],",
                "  meta: {",
                "    agentMeta: { usage: { input: 11, output: 7, total: 18 } },",
                "  },",
                "}));",
            ]
        ),
        encoding="utf-8",
    )

    runner = (
        Path(__file__).resolve().parents[3]
        / "src/openjarvis/evals/backends/external/_runners/openclaw_runner.mjs"
    )
    out_json = tmp_path / "out.json"
    env = {
        "OPENCLAW_PATH": str(tmp_path),
        "HOME": str(tmp_path / "home"),
    }
    result = subprocess.run(
        [
            node,
            str(runner),
            "--task",
            "Say hello.",
            "--model",
            "qwen3:0.6b",
            "--base-url",
            "http://127.0.0.1:11434/v1",
            "--api-key",
            "ollama",
            "--output-json",
            str(out_json),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["content"] == "hello from openclaw"
    assert data["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    assert data["error"] is None
