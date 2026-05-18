"""TerminalBench V2.1 scorer.

Two modes:

1. **Agentic mode (preferred)** — the dataset's ``create_task_env`` spun up a
   container, the agent interacted with it through ``docker_shell_exec``, and
   on context exit the env ran ``tests/test.sh`` and wrote ``tbv21_reward``
   into ``record.metadata``. The scorer just reads that value.

2. **One-shot mode (fallback)** — no env was attached. The model answer is
   treated as a bash script (extracted from a ```bash ... ``` fence if
   present). The scorer runs the script in the task container and then the
   tests, same as before.

This means the same scorer supports both ``backend = "jarvis-direct"`` and
``backend = "jarvis-agent"`` TB v2.1 configs.
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_DEFAULT_AGENT_TIMEOUT = 900.0
_DEFAULT_VERIFIER_TIMEOUT = 900.0


def _extract_bash(model_answer: str) -> str:
    for pat in (
        r"```(?:bash|sh|shell)\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ):
        m = re.search(pat, model_answer, re.DOTALL)
        if m:
            return m.group(1).strip()
    stripped = model_answer.strip()
    if stripped.startswith("#!") or stripped.startswith("set -"):
        return stripped
    return stripped


class TerminalBenchV21Scorer(Scorer):
    """Reward = 1 if the task's tests pass, 0 otherwise."""

    scorer_id = "terminalbench-v2.1"

    def __init__(
        self,
        judge_backend=None,
        judge_model: str = "",
    ) -> None:
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        md = record.metadata or {}

        # ---- Agentic mode: container is live (from task env ctx) ----
        agentic_container = md.get("tbv21_container")
        if agentic_container:
            verifier_timeout = float(
                md.get("verifier_timeout_sec") or _DEFAULT_VERIFIER_TIMEOUT
            )
            meta_a: Dict[str, Any] = {"mode": "agentic", "container": agentic_container}
            try:
                tests = subprocess.run(
                    [
                        "docker",
                        "exec",
                        agentic_container,
                        "bash",
                        "/tests/test.sh",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=verifier_timeout + 60,
                )
                meta_a["tests_exit_code"] = tests.returncode
                meta_a["tests_stdout_tail"] = tests.stdout[-2000:]
                meta_a["tests_stderr_tail"] = tests.stderr[-1500:]
            except subprocess.TimeoutExpired:
                meta_a["tests_exit_code"] = -1
                meta_a["tests_stdout_tail"] = "timeout"

            try:
                reward_out = subprocess.run(
                    [
                        "docker",
                        "exec",
                        agentic_container,
                        "bash",
                        "-c",
                        "cat /logs/verifier/reward.txt 2>/dev/null || echo 0",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                raw = (reward_out.stdout or "").strip()
                meta_a["reward_raw"] = raw
                try:
                    reward = float(raw)
                except ValueError:
                    reward = 0.0
                meta_a["reward"] = reward
                meta_a["score"] = reward
                return reward >= 0.5, meta_a
            except Exception as exc:  # noqa: BLE001
                meta_a["reason"] = f"reward_read_failed: {exc}"
                meta_a["score"] = 0.0
                return False, meta_a

        # ---- One-shot fallback ----
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response", "score": 0.0}

        docker_image: Optional[str] = md.get("docker_image")
        task_dir_str: Optional[str] = md.get("task_dir")
        if not docker_image or not task_dir_str:
            return None, {"reason": "missing_metadata", "mode": "oneshot"}
        task_dir = Path(task_dir_str)
        tests_dir = task_dir / "tests"
        if not tests_dir.is_dir():
            return None, {"reason": "no_tests_dir", "mode": "oneshot"}

        agent_timeout = float(md.get("agent_timeout_sec") or _DEFAULT_AGENT_TIMEOUT)
        verifier_timeout = float(
            md.get("verifier_timeout_sec") or _DEFAULT_VERIFIER_TIMEOUT
        )
        cpus = str(md.get("cpus") or 2)
        memory = str(md.get("memory") or "4G")

        solve_script = _extract_bash(model_answer)
        container = f"tbv21-{md.get('task_id', 'task')}-{uuid.uuid4().hex[:8]}"
        container = re.sub(r"[^a-zA-Z0-9_-]", "-", container)[:63]
        meta = {"mode": "oneshot"}

        try:
            start = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    container,
                    "--cpus",
                    cpus,
                    "--memory",
                    memory,
                    "-v",
                    f"{tests_dir}:/tests:ro",
                    "--entrypoint",
                    "/bin/bash",
                    docker_image,
                    "-c",
                    "mkdir -p /logs/verifier && sleep infinity",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if start.returncode != 0:
                meta["docker_start_error"] = start.stderr[:500]
                return False, meta

            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "bash",
                    "-c",
                    "cat > /app/solve.sh && chmod +x /app/solve.sh",
                ],
                input=solve_script,
                text=True,
                capture_output=True,
                timeout=60,
            )
            agent = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "bash",
                    "-c",
                    "cd /app && bash /app/solve.sh",
                ],
                capture_output=True,
                text=True,
                timeout=agent_timeout + 30,
            )
            meta["agent_exit_code"] = agent.returncode
            meta["agent_stdout_tail"] = agent.stdout[-1500:]
            meta["agent_stderr_tail"] = agent.stderr[-1500:]

            tests = subprocess.run(
                ["docker", "exec", container, "bash", "/tests/test.sh"],
                capture_output=True,
                text=True,
                timeout=verifier_timeout + 30,
            )
            meta["tests_exit_code"] = tests.returncode
            meta["tests_stdout_tail"] = tests.stdout[-1500:]
            meta["tests_stderr_tail"] = tests.stderr[-1500:]

            reward_out = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "bash",
                    "-c",
                    "cat /logs/verifier/reward.txt 2>/dev/null || echo 0",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            raw_reward = (reward_out.stdout or "").strip()
            meta["reward_raw"] = raw_reward
            try:
                reward = float(raw_reward)
            except ValueError:
                reward = 0.0
            meta["reward"] = reward
            meta["score"] = reward
            return reward >= 0.5, meta
        except subprocess.TimeoutExpired as exc:
            meta["reason"] = f"timeout: {exc.cmd[:3]}"
            return False, meta
        except Exception as exc:  # noqa: BLE001
            meta["reason"] = f"{type(exc).__name__}: {exc}"
            return False, meta
        finally:
            subprocess.run(
                ["docker", "rm", "-f", container],
                capture_output=True,
                text=True,
                timeout=60,
            )


__all__ = ["TerminalBenchV21Scorer"]
