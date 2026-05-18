"""TerminalBench V2.1 task environment.

Per-task Docker container + scoring lifecycle. Intended to be used as a
context manager by the eval runner so that the agent has a live
container to interact with through :mod:`openjarvis.tools.docker_shell_exec`.

On ``__enter__``:
    * Pulls / runs the task's docker image with ``sleep infinity``.
    * Mounts the task's ``tests/`` directory read-only at ``/tests``.
    * Creates ``/logs/verifier/`` for reward output.
    * Binds the container name into :mod:`docker_shell_exec`'s thread-local
      state so the agent's ``docker_shell_exec`` tool targets this container.

On ``__exit__``:
    * Runs ``/tests/test.sh`` to produce ``/logs/verifier/reward.txt``.
    * Reads the reward, stashes it on ``record.metadata``.
    * Clears the ``docker_shell_exec`` thread-local.
    * Tears down the container.
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any, MutableMapping, Optional, Type

LOGGER = logging.getLogger(__name__)


class TerminalBenchV21TaskEnv:
    """Per-task Docker + scoring lifecycle for TerminalBench V2.1."""

    def __init__(self, metadata: MutableMapping[str, Any]) -> None:
        self._metadata = metadata
        self._container: Optional[str] = None
        self._started = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------
    def __enter__(self) -> "TerminalBenchV21TaskEnv":
        from openjarvis.tools.docker_shell_exec import set_active_container

        docker_image = self._metadata.get("docker_image")
        task_dir = self._metadata.get("task_dir")
        if not docker_image or not task_dir:
            raise ValueError(
                "TerminalBenchV21TaskEnv missing 'docker_image' or 'task_dir' "
                "metadata"
            )

        tests_dir = Path(task_dir) / "tests"
        if not tests_dir.is_dir():
            raise ValueError(f"Missing tests/ dir in {task_dir}")

        task_id = str(self._metadata.get("task_id") or "task")
        name = f"tbv21-{task_id}-{uuid.uuid4().hex[:8]}"
        name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)[:63]
        self._container = name

        cpus = str(self._metadata.get("cpus") or 2)
        memory = str(self._metadata.get("memory") or "4G")

        start = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
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
            self._metadata["tbv21_env_error"] = start.stderr[:500]
            raise RuntimeError(
                f"docker run failed for {task_id}: {start.stderr[:300]}"
            )

        self._started = True
        self._metadata["tbv21_container"] = name
        set_active_container(name)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Clean up the container + thread-local binding.

        Test execution + reward reading lives on the scorer, which runs
        *inside* this context manager (while the container is still up).
        """
        from openjarvis.tools.docker_shell_exec import set_active_container

        set_active_container(None)
        if self._container:
            subprocess.run(
                ["docker", "rm", "-f", self._container],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self._container = None


__all__ = ["TerminalBenchV21TaskEnv"]
