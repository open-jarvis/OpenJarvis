"""TerminalBench V2.1 dataset provider.

Loads tasks from the terminal-bench-2.1 repo layout (ekellbuch/terminal-bench-2,
branch terminal-bench-2.1). Each task lives in a top-level directory containing:

    <task_name>/
      task.toml          # metadata + docker image + timeouts
      instruction.md     # the agent prompt
      environment/       # Dockerfile + supporting files (pre-built into task.toml's docker_image)
      solution/          # oracle solve.sh (not used by eval)
      tests/             # test.sh + test_outputs.py (pytest) used by the verifier

Reference: https://github.com/ekellbuch/terminal-bench-2/tree/terminal-bench-2.1
"""

from __future__ import annotations

import logging
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_DEFAULT_REPO = "https://github.com/ekellbuch/terminal-bench-2.git"
_DEFAULT_BRANCH = "terminal-bench-2.1"
# Shared cache across isolated HOMEs; falls back to $HOME/.cache if env override set
import os as _os  # noqa: E402

_DEFAULT_CACHE = Path(
    _os.environ.get("TBV21_REPO_DIR") or "/home/ubuntu/.cache/terminalbench-v2.1/repo"
)


def _load_task_toml(task_dir: Path) -> Dict[str, Any]:
    """Parse task.toml using tomllib (3.11+) or tomli fallback."""
    task_file = task_dir / "task.toml"
    if not task_file.exists():
        return {}
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            LOGGER.warning("tomllib/tomli not available; skipping %s", task_dir)
            return {}
    try:
        return tomllib.loads(task_file.read_text()) or {}
    except Exception as exc:  # noqa: BLE001 - defensive
        LOGGER.warning("Failed to parse %s: %s", task_file, exc)
        return {}


class TerminalBenchV21Dataset(DatasetProvider):
    """TerminalBench V2.1 dataset (89 Docker-based terminal tasks)."""

    dataset_id = "terminalbench-v2.1"
    dataset_name = "TerminalBench V2.1"

    def __init__(
        self,
        repo_url: str = _DEFAULT_REPO,
        branch: str = _DEFAULT_BRANCH,
        path: Optional[str] = None,
        task_ids: Optional[List[str]] = None,
    ) -> None:
        self._repo_url = repo_url
        self._branch = branch
        self._repo_dir: Path = Path(path) if path else _DEFAULT_CACHE
        self._task_ids = task_ids
        self._records: List[EvalRecord] = []

    def _ensure_repo(self) -> Path:
        """Clone the TB v2.1 repo once and cache it locally."""
        if self._repo_dir.exists() and (self._repo_dir / ".git").is_dir():
            return self._repo_dir
        if shutil.which("git") is None:
            raise RuntimeError(
                "git binary not found. Install git to clone TerminalBench V2.1 tasks."
            )
        self._repo_dir.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Cloning %s (branch %s) into %s", self._repo_url, self._branch, self._repo_dir)
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                self._branch,
                "--depth",
                "1",
                self._repo_url,
                str(self._repo_dir),
            ],
            check=True,
        )
        return self._repo_dir

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        repo = self._ensure_repo()
        task_dirs = sorted(
            d
            for d in repo.iterdir()
            if d.is_dir() and (d / "task.toml").exists()
        )

        if self._task_ids:
            wanted = set(self._task_ids)
            task_dirs = [d for d in task_dirs if d.name in wanted]

        if seed is not None:
            rng = random.Random(seed)
            task_dirs = list(task_dirs)
            rng.shuffle(task_dirs)

        if max_samples is not None:
            task_dirs = task_dirs[:max_samples]

        self._records = []
        for idx, task_dir in enumerate(task_dirs):
            record = self._convert_task(task_dir, idx)
            if record is not None:
                self._records.append(record)

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _convert_task(self, task_dir: Path, idx: int) -> Optional[EvalRecord]:
        task_data = _load_task_toml(task_dir)
        instruction_file = task_dir / "instruction.md"
        if not instruction_file.exists():
            return None

        raw_instruction = instruction_file.read_text().strip()
        if not raw_instruction:
            return None

        # Agentic framing — works for both the one-shot direct backend
        # (model emits a single bash script) and the multi-turn agent
        # backend (model calls `docker_shell_exec` repeatedly). When the
        # agentic backend is in use, the container is live, and every
        # `docker_shell_exec` call lands there. The test verifier runs
        # after the agent finishes.
        instruction = (
            "You are solving a TerminalBench V2.1 task inside a Linux "
            "container (working dir /app, root access, internet available, "
            "common tools: bash, python3, pip, curl, apt, git). Use the "
            "`docker_shell_exec` tool to inspect the environment, install "
            "packages, run commands, and create files. Iterate until the "
            "task is complete and the required output files are in place. "
            "Do not claim you are done until you have verified the outputs "
            "exist. If you are limited to a single response (no tool use), "
            "output a full bash script inside a ```bash ... ``` fence that "
            "solves the task end-to-end.\n\n"
            "--- TASK ---\n" + raw_instruction
        )

        meta = task_data.get("metadata", {}) or {}
        env = task_data.get("environment", {}) or {}
        verifier = task_data.get("verifier", {}) or {}
        agent = task_data.get("agent", {}) or {}

        task_id = task_dir.name or f"tbv21_{idx}"
        category = meta.get("category", "terminal")

        metadata: Dict[str, Any] = {
            "task_id": task_id,
            "task_dir": str(task_dir),
            "category": category,
            "difficulty": meta.get("difficulty"),
            "tags": meta.get("tags", []),
            "docker_image": env.get("docker_image"),
            "cpus": env.get("cpus"),
            "memory": env.get("memory"),
            "storage": env.get("storage"),
            "build_timeout_sec": env.get("build_timeout_sec"),
            "verifier_timeout_sec": verifier.get("timeout_sec"),
            "agent_timeout_sec": agent.get("timeout_sec"),
            "author_name": meta.get("author_name"),
            "expert_time_estimate_min": meta.get("expert_time_estimate_min"),
        }

        return EvalRecord(
            record_id=f"terminalbench-v2.1-{task_id}",
            problem=instruction,
            reference="",
            category="agentic",
            subject=category,
            metadata=metadata,
        )

    def create_task_env(self, record):
        """Return a per-task Docker environment (context manager).

        The runner enters this around the agent call so that tools like
        ``docker_shell_exec`` can target the running container.
        """
        try:
            from openjarvis.evals.execution.terminalbench_v2_1_env import (
                TerminalBenchV21TaskEnv,
            )
        except ImportError:
            return None
        return TerminalBenchV21TaskEnv(record.metadata)

    def verify_requirements(self) -> List[str]:
        """Check runtime prerequisites (docker, git, tomllib)."""
        issues: List[str] = []
        if shutil.which("docker") is None:
            issues.append("docker not found in PATH (required to run TB v2.1 tasks)")
        if shutil.which("git") is None:
            issues.append("git not found in PATH (required to clone TB v2.1 repo)")
        try:
            import tomllib  # noqa: F401
        except ImportError:
            try:
                import tomli  # noqa: F401
            except ImportError:
                issues.append(
                    "tomllib (3.11+) or tomli not available — cannot parse task.toml"
                )
        return issues


__all__ = ["TerminalBenchV21Dataset"]
