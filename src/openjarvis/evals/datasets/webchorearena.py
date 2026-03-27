"""WebChoreArena: Realistic tedious web browsing tasks.

Evaluates web agents on 532 tasks across Shopping, Shopping Admin,
Reddit, GitLab, and Cross-site environments. Tests massive memory,
calculation, and long-term memory capabilities.

Requires a running WebArena standalone environment (Shopping/Magento,
Reddit/Postmill, GitLab, Shopping Admin). Tasks are per-site JSON configs
cloned from the original GitHub repository.

Source: https://github.com/WebChoreArena/WebChoreArena
"""

from __future__ import annotations

import json
import logging
import os
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_GITHUB_REPO = "https://github.com/WebChoreArena/WebChoreArena.git"

_SITE_DIRS = {
    "shopping": "test_shopping.json",
    "shopping_admin": "test_shopping_admin.json",
    "reddit": "test_reddit.json",
    "gitlab": "test_gitlab.json",
    "cross": "test_cross.raw.json",
}


class WebChoreArenaDataset(DatasetProvider):
    """WebChoreArena benchmark — interactive browser-based web tasks.

    Tasks are enumerated from the original GitHub repository's
    ``config_files/`` JSON files.  Each task requires a live WebArena
    standalone environment and Playwright for evaluation.
    """

    dataset_id = "webchorearena"
    dataset_name = "WebChoreArena"

    def __init__(
        self,
        subset: str = "all",
        cache_dir: Optional[str] = None,
        headless: bool = True,
    ) -> None:
        self._subset = subset  # "all", "small", or a site name
        self._cache_dir = (
            Path(cache_dir) if cache_dir else Path.home() / ".cache" / "webchorearena"
        )
        self._headless = headless
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        repo_dir = self._cache_dir / "repo"
        config_dir = repo_dir / "AgentOccam" / "config_files"

        if not config_dir.exists():
            self._clone_repo(repo_dir)

        tasks = self._load_tasks(config_dir)

        if seed is not None:
            random.Random(seed).shuffle(tasks)
        if max_samples is not None:
            tasks = tasks[:max_samples]

        self._records = [self._task_to_record(t, i) for i, t in enumerate(tasks)]
        logger.info(
            "WebChoreArena[%s]: loaded %d tasks",
            self._subset,
            len(self._records),
        )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def verify_requirements(self) -> List[str]:
        import urllib.request

        issues: List[str] = []
        try:
            import playwright  # noqa: F401
        except ImportError:
            issues.append(
                "playwright required for WebChoreArena. "
                "Install with: pip install playwright && playwright install"
            )

        # Core services — eval fails without these
        _REQUIRED = {
            "SHOPPING": "http://localhost:7770",
            "SHOPPING_ADMIN": "http://localhost:7780",
            "REDDIT": "http://localhost:9999",
            "GITLAB": "http://localhost:8023",
            "WIKIPEDIA": "http://localhost:8888",
        }
        # Optional — only needed for map tasks; requires a full OpenStreetMap
        # Docker Compose setup (AWS AMI or manual)
        _OPTIONAL = {
            "MAP": "http://localhost:3000",
        }

        unreachable = []
        for env_var, default_url in _REQUIRED.items():
            url = os.environ.get(env_var, default_url)
            try:
                urllib.request.urlopen(url, timeout=5)
            except Exception:
                unreachable.append(f"  {env_var}={url}")

        if unreachable:
            issues.append(
                "The following WebArena backend services are not reachable.\n"
                "Run scripts/setup_webchorearena.sh to start them:\n"
                + "\n".join(unreachable)
            )

        for env_var, default_url in _OPTIONAL.items():
            url = os.environ.get(env_var, default_url)
            try:
                urllib.request.urlopen(url, timeout=5)
            except Exception:
                logger.warning(
                    "Optional WebArena service %s (%s) is not reachable — "
                    "map-related tasks will fail. "
                    "See scripts/setup_webchorearena.sh for setup instructions.",
                    env_var,
                    url,
                )

        return issues

    def create_task_env(self, record: EvalRecord):
        """Return a WebChoreArenaTaskEnv for the given record."""
        try:
            from openjarvis.evals.execution.webchorearena_env import (
                WebChoreArenaTaskEnv,
            )

            return WebChoreArenaTaskEnv(record.metadata, headless=self._headless)
        except ImportError:
            return None

    # ------------------------------------------------------------------

    def _clone_repo(self, repo_dir: Path) -> None:
        """Clone the WebChoreArena repository from GitHub."""
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Cloning WebChoreArena from %s ...", _GITHUB_REPO)
        subprocess.run(
            ["git", "clone", "--depth", "1", _GITHUB_REPO, str(repo_dir)],
            check=True,
            capture_output=True,
        )
        logger.info("WebChoreArena cloned to %s", repo_dir)

    def _load_tasks(self, config_dir: Path) -> List[Dict[str, Any]]:
        """Load task definitions from the original config_files/ directory."""
        tasks: List[Dict[str, Any]] = []

        if self._subset == "small":
            small_ids = self._load_small_set_ids(config_dir)

        for site_key, filename in _SITE_DIRS.items():
            if self._subset not in ("all", "small") and self._subset != site_key:
                continue

            filepath = config_dir / filename
            if not filepath.exists():
                logger.warning("Config file not found: %s", filepath)
                continue

            try:
                with open(filepath) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load %s: %s", filepath, exc)
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if not item.get("intent") and not item.get("intent_template"):
                    continue

                if self._subset == "small":
                    task_id = str(item.get("task_id", ""))
                    if task_id not in small_ids:
                        continue

                tasks.append(item)

        return tasks

    def _load_small_set_ids(self, config_dir: Path) -> set:
        """Load small subset IDs from small_set_ids.txt."""
        ids: set = set()
        small_file = config_dir / "small_set_ids.txt"
        if small_file.exists():
            with open(small_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ids.add(line)
        return ids

    def _task_to_record(
        self,
        task: Dict[str, Any],
        idx: int,
    ) -> EvalRecord:
        """Convert an original WebChoreArena task config into an EvalRecord."""
        task_id = str(task.get("task_id", idx))
        intent = str(task.get("intent", task.get("intent_template", "")))

        sites = task.get("sites", [])
        site = sites[0].lower().replace(" ", "_") if sites else "unknown"

        return EvalRecord(
            record_id=f"webchorearena-{task_id}",
            problem=intent,
            reference="",
            category="agentic",
            subject=site,
            metadata={
                "task_id": task_id,
                "task_config": task,
                "site": site,
                "sites": sites,
                "start_url": task.get("start_url", ""),
                "start_url_lite": task.get("start_url_lite", ""),
                "storage_state": task.get(
                    "storage_state", task.get("strage_state", "")
                ),
                "required_obs": task.get("required_obs", "text"),
                "type_main": task.get("type_main", ""),
                "type_sub": task.get("type_sub", ""),
                "affect_environment": task.get("affect_environment", False),
                "eval": task.get("eval", {}),
                "headless": self._headless,
            },
        )


__all__ = ["WebChoreArenaDataset"]
