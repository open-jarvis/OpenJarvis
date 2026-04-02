"""TauBench V2 dataset provider — multi-turn customer service benchmark.

Wraps the tau2-bench framework for evaluation within OpenJarvis.
Supports airline, retail, and telecom domains.

Reference: https://github.com/sierra-research/tau2-bench
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

TAU2_REPO = "https://github.com/sierra-research/tau2-bench.git"
CACHE_DIR = Path.home() / ".cache" / "tau2-bench"

DOMAINS = ("airline", "retail", "telecom")


def _ensure_tau2() -> None:
    """Ensure tau2 package is importable; install from cache if needed."""
    try:
        import tau2  # noqa: F401
    except ImportError:
        # Clone and install from source
        if not CACHE_DIR.exists():
            LOGGER.info("Cloning tau2-bench from %s ...", TAU2_REPO)
            CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--depth", "1", TAU2_REPO, str(CACHE_DIR)],
                check=True,
                capture_output=True,
            )
        LOGGER.info("Installing tau2-bench ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(CACHE_DIR)],
            check=True,
            capture_output=True,
        )


class TauBenchDataset(DatasetProvider):
    """TauBench V2 multi-turn customer service benchmark.

    Wraps tau2-bench's task loading and evaluation infrastructure.
    Each EvalRecord represents a single customer service scenario.
    """

    dataset_id = "taubench"
    dataset_name = "TauBench"

    def __init__(
        self,
        domains: Optional[List[str]] = None,
    ) -> None:
        self._domains = domains or list(DOMAINS)
        self._records: List[EvalRecord] = []
        self._engine_key: Optional[str] = None
        self._model: Optional[str] = None
        self._temperature: float = 0.7
        self._max_tokens: int = 4096
        self._user_model: Optional[str] = None
        self._num_trials: int = 3  # pass^k: best of k trials per task
        self._telemetry: bool = False
        self._gpu_metrics: bool = False

    def set_engine_config(
        self,
        engine_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        user_model: Optional[str] = None,
        num_trials: Optional[int] = None,
        telemetry: bool = False,
        gpu_metrics: bool = False,
    ) -> None:
        """Inject engine configuration for the agent. Called by CLI."""
        if engine_key is not None:
            self._engine_key = engine_key
        if model is not None:
            self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        if user_model is not None:
            self._user_model = user_model
        if num_trials is not None:
            self._num_trials = num_trials
        self._telemetry = telemetry
        self._gpu_metrics = gpu_metrics

    def verify_requirements(self) -> List[str]:
        issues: List[str] = []
        try:
            _ensure_tau2()
        except Exception as exc:
            issues.append(f"tau2-bench not available: {exc}")
        return issues

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        _ensure_tau2()
        from tau2.runner import get_tasks

        # split overrides domains if provided (e.g. "airline,retail")
        domains = self._domains
        if split:
            domains = [d.strip() for d in split.split(",") if d.strip()]

        all_records: List[EvalRecord] = []

        for domain in domains:
            if domain not in DOMAINS:
                LOGGER.warning("Unknown TauBench domain: %s", domain)
                continue

            # Load tasks, filtering to test split when available
            from tau2.runner import load_task_splits
            try:
                task_splits = load_task_splits(domain)
                test_ids = (
                    set(str(t) for t in task_splits.get("test", []))
                    if task_splits
                    else set()
                )
            except Exception:
                test_ids = set()

            tasks = get_tasks(domain)
            if test_ids:
                tasks = [t for t in tasks if str(t.id) in test_ids]
                LOGGER.info(
                    "TauBench: loaded %d test-split tasks for domain '%s'",
                    len(tasks), domain,
                )
            else:
                LOGGER.info(
                    "TauBench: loaded %d tasks for domain '%s' (no test split)",
                    len(tasks), domain,
                )

            for task in tasks:
                # Build the user's reason for calling as the problem prompt
                user_scenario = task.user_scenario
                instructions = user_scenario.instructions
                problem = (
                    f"Domain: {domain}\n"
                    f"Reason for call: {instructions.reason_for_call}\n"
                    f"Known info: {instructions.known_info or 'None'}\n"
                )

                # Extract evaluation criteria
                eval_criteria = task.evaluation_criteria
                actions = []
                nl_assertions = []
                communicate_info = []
                reward_basis = []
                if eval_criteria:
                    actions = [
                        a.model_dump() if hasattr(a, "model_dump") else a
                        for a in (eval_criteria.actions or [])
                    ]
                    nl_assertions = eval_criteria.nl_assertions or []
                    communicate_info = [
                        c.model_dump() if hasattr(c, "model_dump") else c
                        for c in (eval_criteria.communicate_info or [])
                    ]
                    reward_basis = [
                        r.value if hasattr(r, "value") else r
                        for r in (eval_criteria.reward_basis or [])
                    ]

                record = EvalRecord(
                    record_id=f"{domain}_{task.id}",
                    problem=problem,
                    reference=task.description.purpose if task.description else "",
                    category=domain,
                    subject=f"taubench-{domain}",
                    metadata={
                        "domain": domain,
                        "task_id": task.id,
                        "task_instructions": instructions.task_instructions,
                        "reason_for_call": instructions.reason_for_call,
                        "known_info": instructions.known_info,
                        "unknown_info": instructions.unknown_info,
                        "actions": actions,
                        "nl_assertions": nl_assertions,
                        "communicate_info": communicate_info,
                        "reward_basis": reward_basis,
                    },
                )
                all_records.append(record)

        if seed is not None:
            import random
            random.Random(seed).shuffle(all_records)
        if max_samples is not None:
            all_records = all_records[:max_samples]

        self._records = all_records
        LOGGER.info(
            "TauBench: loaded %d total tasks across %s",
            len(self._records),
            ", ".join(self._domains),
        )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def create_task_env(self, record: EvalRecord):
        """Create a TauBench task environment for evaluation."""
        from openjarvis.evals.execution.taubench_env import TauBenchTaskEnv
        return TauBenchTaskEnv(
            record,
            engine_key=self._engine_key,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            user_model=self._user_model,
            num_trials=self._num_trials,
            telemetry=self._telemetry,
            gpu_metrics=self._gpu_metrics,
        )


__all__ = ["TauBenchDataset"]
