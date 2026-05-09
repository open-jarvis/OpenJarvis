"""PinchBench dataset provider — real-world agent task benchmark.

Clones the pinchbench/skill repo at runtime and parses task markdown files
into EvalRecords for use with AgenticRunner.

Reference: https://github.com/pinchbench/skill
"""

from __future__ import annotations

import logging
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

PINCHBENCH_REPO = "https://github.com/pinchbench/skill.git"
CACHE_DIR = Path.home() / ".cache" / "pinchbench"


def _parse_task_markdown(content: str, filename: str = "") -> Dict[str, Any]:
    """Parse a PinchBench task markdown file into a dict.

    Extracts YAML frontmatter and markdown sections (## Prompt,
    ## Expected Behavior, ## Automated Checks, ## LLM Judge Rubric).
    """
    # Split frontmatter
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Missing YAML frontmatter in {filename}")

    frontmatter = yaml.safe_load(parts[1])
    body = parts[2]

    # Parse sections by ## headers
    sections: Dict[str, str] = {}
    current_header: Optional[str] = None
    current_lines: List[str] = []

    for line in body.split("\n"):
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            if current_header is not None:
                sections[current_header] = "\n".join(current_lines).strip()
            current_header = header_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_header is not None:
        sections[current_header] = "\n".join(current_lines).strip()

    # Extract Python code block from Automated Checks section
    automated_checks = None
    checks_section = sections.get("Automated Checks", "")
    code_match = re.search(r"```python\s*\n(.*?)```", checks_section, re.DOTALL)
    if code_match:
        automated_checks = code_match.group(1).strip()

    return {
        "id": frontmatter.get("id", ""),
        "name": frontmatter.get("name", ""),
        "category": frontmatter.get("category", ""),
        "grading_type": frontmatter.get("grading_type", "automated"),
        "timeout_seconds": frontmatter.get("timeout_seconds", 180),
        "workspace_files": frontmatter.get("workspace_files", []),
        "grading_weights": frontmatter.get("grading_weights"),
        "multi_session": frontmatter.get("multi_session", False),
        "sessions": frontmatter.get("sessions", []),
        "prompt": sections.get("Prompt", ""),
        "expected_behavior": sections.get("Expected Behavior", ""),
        "grading_criteria": sections.get("Grading Criteria", ""),
        "automated_checks": automated_checks,
        "llm_judge_rubric": sections.get("LLM Judge Rubric"),
    }


class PinchBenchDataset(DatasetProvider):
    """PinchBench real-world agent benchmark.

    Clones pinchbench/skill from GitHub (or uses a local path) and
    parses task markdown files into EvalRecords.
    """

    dataset_id = "pinchbench"
    dataset_name = "PinchBench"

    def __init__(self, path: Optional[str] = None) -> None:
        self._local_path = Path(path) if path else None
        self._repo_dir: Path = self._local_path or CACHE_DIR
        self._records: List[EvalRecord] = []

    def verify_requirements(self) -> List[str]:
        issues: List[str] = []
        if self._local_path is None and shutil.which("git") is None:
            issues.append(
                "git binary not found. Install git to clone PinchBench tasks."
            )
        if self._repo_dir.exists() and not (self._repo_dir / "tasks").is_dir():
            issues.append(
                f"PinchBench cache at {self._repo_dir} is corrupted (missing tasks/). "
                "Delete and re-run to re-clone."
            )
        return issues

    def _ensure_repo(self) -> Path:
        """Clone the repo if not already cached. Returns repo dir."""
        if self._local_path is not None:
            if not self._local_path.exists():
                raise FileNotFoundError(
                    f"PinchBench path not found: {self._local_path}"
                )
            return self._local_path

        if not self._repo_dir.exists():
            LOGGER.info("Cloning PinchBench from %s ...", PINCHBENCH_REPO)
            self._repo_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", PINCHBENCH_REPO, str(self._repo_dir)],
                check=True,
                capture_output=True,
            )
            LOGGER.info("PinchBench cloned to %s", self._repo_dir)

        return self._repo_dir

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        repo_dir = self._ensure_repo()
        tasks_dir = repo_dir / "tasks"

        if not tasks_dir.is_dir():
            raise FileNotFoundError(f"No tasks/ directory in {repo_dir}")

        task_files = sorted(tasks_dir.glob("task_*.md"))
        if not task_files:
            raise FileNotFoundError(f"No task_*.md files in {tasks_dir}")

        tasks = []
        for tf in task_files:
            try:
                parsed = _parse_task_markdown(tf.read_text(), filename=tf.name)
                tasks.append(parsed)
            except Exception as exc:
                LOGGER.warning("Skipping %s: %s", tf.name, exc)

        effective_seed = 42 if seed is None else seed
        if split in ("train", "test", "all"):
            tasks = apply_split(tasks, split=split, seed=effective_seed, train_frac=0.2)
        elif seed is not None:
            random.Random(seed).shuffle(tasks)
        if max_samples is not None:
            tasks = tasks[:max_samples]

        self._records = [
            EvalRecord(
                record_id=t["id"],
                problem=(
                    t["sessions"][0]["prompt"]
                    if t.get("multi_session") and t.get("sessions")
                    else t["prompt"]
                ),
                reference=t["expected_behavior"],
                category=t["category"],
                subject=t["name"],
                metadata={
                    "grading_type": t["grading_type"],
                    "grading_weights": t["grading_weights"],
                    "automated_checks": t["automated_checks"],
                    "llm_judge_rubric": t["llm_judge_rubric"],
                    "timeout_seconds": t["timeout_seconds"],
                    "workspace_files": t["workspace_files"],
                    "pinchbench_repo_dir": str(repo_dir),
                    "multi_session": t.get("multi_session", False),
                    "sessions": t.get("sessions", []),
                },
            )
            for t in tasks
        ]

        LOGGER.info("PinchBench: loaded %d tasks", len(self._records))

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def set_judge(self, judge_backend: Any, judge_model: str) -> None:
        """Set the judge backend/model for LLM-judge and hybrid grading."""
        self._judge_backend = judge_backend
        self._judge_model = judge_model

    def create_task_env(self, record: EvalRecord):
        from openjarvis.evals.execution.pinchbench_env import PinchBenchTaskEnv

        return PinchBenchTaskEnv(
            record,
            judge_backend=getattr(self, "_judge_backend", None),
            judge_model=getattr(self, "_judge_model", "anthropic/claude-opus-4-5"),
        )


__all__ = ["PinchBenchDataset"]
