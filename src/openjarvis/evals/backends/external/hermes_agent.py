"""HermesBackend - runs real Hermes Agent as a subprocess per task.

Implements the InferenceBackend ABC by spawning hermes_runner.py with the
foreign Hermes installation on sys.path. Foreign code never imports into
this process; we cross the boundary only via stdin/stdout JSON.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

from openjarvis.evals.backends.external._subprocess_runner import run_one_shot
from openjarvis.evals.comparison.third_party import (
    ThirdPartyEntry,
    load_third_party_config,
    verify_commit_pin,
)
from openjarvis.evals.core.backend import InferenceBackend


class HermesBackend(InferenceBackend):
    """Spawn real Hermes Agent (pinned commit) as a subprocess per task."""

    backend_id = "hermes"
    framework_name = "hermes"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_mode: str = "chat_completions",
        max_iterations: int = 90,
        timeout_seconds: float = 7200.0,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._api_mode = api_mode
        self._max_iterations = max_iterations
        self._timeout = timeout_seconds

        cfg = load_third_party_config()
        self._entry: ThirdPartyEntry = cfg.entries["hermes"]
        verify_commit_pin(self._entry)

    @property
    def framework_commit_value(self) -> str:
        """Pinned commit of Hermes Agent (for telemetry tagging)."""
        return self._entry.pinned_commit

    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        return self.generate_full(
            prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )["content"]

    def generate_full(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            output_json = Path(fh.name)

        try:
            python_exe = self._entry.python_executable or sys.executable
            runner_script = (
                Path(__file__).resolve().parents[5] / self._entry.runner_script
            )
            cmd = [
                python_exe,
                str(runner_script),
                "--task",
                prompt,
                "--model",
                model,
                "--base-url",
                self._base_url,
                "--api-key",
                self._api_key,
                "--api-mode",
                self._api_mode,
                "--max-iterations",
                str(self._max_iterations),
                "--output-json",
                str(output_json),
            ]
            if system:
                cmd.extend(["--system-prompt", system])

            env = dict(os.environ)
            env["HERMES_AGENT_PATH"] = str(self._entry.path)

            result = run_one_shot(
                cmd=cmd,
                env=env,
                timeout=self._timeout,
                output_json_path=output_json,
            )
        finally:
            output_json.unlink(missing_ok=True)

        return {
            "content": result.parsed_json.get("content", ""),
            "usage": result.parsed_json.get("usage", {}),
            "model": model,
            "latency_seconds": result.latency_seconds,
            "energy_joules": result.energy_joules,
            "peak_power_w": result.peak_power_w,
            "tool_calls": result.parsed_json.get("tool_calls", 0),
            "turn_count": result.parsed_json.get("turn_count", 0),
            "framework": "hermes",
            "framework_commit": self._entry.pinned_commit,
            "cost_usd": 0.0,
            "error": result.error or result.parsed_json.get("error"),
        }
