"""WorkArena++ enterprise workflow benchmark on ServiceNow.

Faithful integration of the original browsergym-workarena package.
Tasks are Python classes that run against a live ServiceNow instance
via BrowserGym / Playwright — NOT a static JSON dataset.

L1 = 33 atomic tasks (ICML 2024)
L2/L3 = 682 composite tasks (NeurIPS 2024)

Source: https://github.com/ServiceNow/WorkArena
Requires: pip install browsergym-workarena playwright==1.44.0
"""

from __future__ import annotations

import logging
import os
import random
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_WORKARENA_IMPORT_ERROR: str = ""
try:
    from browsergym.workarena import (
        ATOMIC_TASKS,
        TASK_CATEGORY_MAP,
        get_all_tasks_agents,
    )

    _HAS_WORKARENA = True
except ImportError as _e:
    _HAS_WORKARENA = False
    _WORKARENA_IMPORT_ERROR = str(_e)
    ATOMIC_TASKS = []
    TASK_CATEGORY_MAP = {}

    def get_all_tasks_agents(**kwargs):  # type: ignore[misc]
        return []


_VALID_LEVELS = ("l1", "l2", "l3")


class WorkArenaDataset(DatasetProvider):
    """WorkArena++ benchmark using the native browsergym-workarena package.

    Tasks are enumerated from the installed ``browsergym-workarena``
    package exactly as in the original benchmark.  Each task class is
    instantiated with a seed by BrowserGym at evaluation time.  Scoring
    uses the task's native ``validate()`` method against the live
    ServiceNow instance — no LLM judge or text matching.
    """

    dataset_id = "workarena"
    dataset_name = "WorkArena++"

    def __init__(
        self,
        level: str = "l2",
        n_seed_l1: int = 10,
        meta_seed: int = 42,
        headless: bool = True,
    ) -> None:
        if level not in _VALID_LEVELS and level != "all":
            raise ValueError(
                f"Unknown WorkArena level: {level!r}. "
                f"Choose from: {list(_VALID_LEVELS)} or 'all'"
            )
        self._level = level
        self._n_seed_l1 = n_seed_l1
        self._meta_seed = meta_seed
        self._headless = headless
        self._records: List[EvalRecord] = []
        self._episodes: List[List[EvalRecord]] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        if not _HAS_WORKARENA:
            detail = (
                f"\n\nUnderlying error: {_WORKARENA_IMPORT_ERROR}"
                if _WORKARENA_IMPORT_ERROR
                else ""
            )
            raise ImportError(
                "The 'browsergym-workarena' package is required for "
                "WorkArena evaluation. Install with:\n"
                "  uv pip install browsergym-workarena\n"
                "  uv run playwright install\n"
                "You also need access to a ServiceNow instance via "
                "https://huggingface.co/datasets/ServiceNow/WorkArena-Instances"
                + detail
            )

        task_tuples = self._enumerate_tasks()

        if seed is not None:
            random.Random(seed).shuffle(task_tuples)
        if max_samples is not None:
            task_tuples = task_tuples[:max_samples]

        self._records = []
        self._episodes = []
        for idx, (task_class, task_seed) in enumerate(task_tuples):
            record = self._task_to_record(task_class, task_seed, idx)
            self._records.append(record)
            self._episodes.append([record])

        logger.info(
            "WorkArena[%s]: loaded %d task instances",
            self._level,
            len(self._records),
        )

    def _enumerate_tasks(self) -> List[tuple]:
        """Enumerate (task_class, seed) tuples from browsergym-workarena.

        Uses the original ``get_all_tasks_agents()`` for L2/L3 and
        ``ATOMIC_TASKS`` with random seeds for L1, exactly matching
        the original benchmark's sampling strategy.
        """
        levels = list(_VALID_LEVELS) if self._level == "all" else [self._level]
        task_tuples: List[tuple] = []

        for level in levels:
            tuples = get_all_tasks_agents(
                filter=level,
                meta_seed=self._meta_seed,
                n_seed_l1=self._n_seed_l1,
            )
            task_tuples.extend(tuples)

        return task_tuples

    def _task_to_record(
        self,
        task_class: type,
        task_seed: int,
        idx: int,
    ) -> EvalRecord:
        """Convert a (task_class, seed) pair into an EvalRecord."""
        task_id = task_class.get_task_id()
        category = TASK_CATEGORY_MAP.get(task_id, "general")

        # Determine level from task class hierarchy
        level = self._infer_level(task_class)

        problem = (
            f"[BrowserGym task — goal provided by environment at runtime]\n"
            f"Task ID: {task_id}\n"
            f"Category: {category}\n"
            f"Level: {level}"
        )

        return EvalRecord(
            record_id=f"workarena-{task_id}-s{task_seed}",
            problem=problem,
            reference="",
            category="agentic",
            subject=category,
            metadata={
                "task_id": task_id,
                "task_class": task_class,
                "task_seed": task_seed,
                "level": level,
                "category": category,
                "headless": self._headless,
            },
        )

    def _infer_level(self, task_class: type) -> str:
        """Determine the task level from its class hierarchy."""
        try:
            from browsergym.workarena.tasks.compositional.base import (
                CompositionalTask,
            )

            if issubclass(task_class, CompositionalTask):
                task_id = task_class.get_task_id()
                if ".l3." in task_id or "_l3_" in task_id:
                    return "l3"
                return "l2"
        except ImportError:
            pass

        if task_class in ATOMIC_TASKS:
            return "l1"

        task_id = task_class.get_task_id()
        if ".l3." in task_id:
            return "l3"
        if ".l2." in task_id:
            return "l2"
        return "l1"

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def iter_episodes(self) -> Iterable[List[EvalRecord]]:
        return iter(self._episodes)

    def size(self) -> int:
        return len(self._records)

    def create_task_env(self, record: EvalRecord):
        """Return a WorkArenaTaskEnv for the given record."""
        try:
            from openjarvis.evals.execution.workarena_env import (
                WorkArenaTaskEnv,
            )

            return WorkArenaTaskEnv(record.metadata)
        except ImportError:
            return None

    def verify_requirements(self) -> List[str]:
        """Check that all prerequisites for WorkArena evaluation are met."""
        issues: List[str] = []

        if not _HAS_WORKARENA:
            issues.append(
                "browsergym-workarena not installed. "
                "Install with: pip install browsergym-workarena"
            )

        try:
            import playwright  # noqa: F401
        except ImportError:
            issues.append(
                "playwright not installed. "
                "Install with: pip install playwright==1.44.0 && playwright install"
            )

        snow_configured = bool(
            os.environ.get("SNOW_INSTANCE_URL")
            or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        )
        if not snow_configured:
            issues.append(
                "ServiceNow instance not configured. "
                "Set SNOW_INSTANCE_URL or authenticate with HuggingFace: "
                "huggingface-cli login (requires gated access to "
                "ServiceNow/WorkArena-Instances)"
            )

        return issues


__all__ = ["WorkArenaDataset"]
