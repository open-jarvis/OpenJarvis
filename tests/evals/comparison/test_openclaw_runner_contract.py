"""Contract tests for the OpenClaw subprocess runner."""

from __future__ import annotations

import json
import os
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
    # subprocess.run's `env` REPLACES the environment rather than merging
    # it, so passing just these two keys wiped everything Node needs to
    # even start on Windows (TEMP/TMP/SystemRoot/PATH) -- os.tmpdir()
    # falls back to the literal string 'undefined' when those are unset,
    # and mkdtemp then fails with ENOENT (#785). Inherit the parent
    # environment and layer the test-specific overrides on top.
    env = {
        **os.environ,
        "OPENCLAW_PATH": str(tmp_path),
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "home"),
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
