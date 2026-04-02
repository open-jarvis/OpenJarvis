"""LiveResearchBench dataset provider — deep research benchmark.

Clones the deep_research_bench repo at runtime and parses query + criteria
JSONL files into EvalRecords for use with AgenticRunner.

Reference: https://github.com/Ayanami0730/deep_research_bench
Paper: https://arxiv.org/abs/2510.14240
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

LIVERESEARCH_REPO = "https://github.com/Ayanami0730/deep_research_bench.git"
CACHE_DIR = Path.home() / ".cache" / "liveresearch_bench"


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts."""
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _build_criteria_index(
    criteria_records: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """Index criteria records by their integer id."""
    index: Dict[int, Dict[str, Any]] = {}
    for rec in criteria_records:
        rec_id = rec.get("id")
        if rec_id is not None:
            index[int(rec_id)] = rec
    return index


class LiveResearchBenchDataset(DatasetProvider):
    """LiveResearchBench — deep research with 100 expert-curated tasks.

    Clones Ayanami0730/deep_research_bench from GitHub (or uses a local
    path) and parses query + criteria JSONL files into EvalRecords.
    """

    dataset_id = "liveresearch"
    dataset_name = "LiveResearchBench"

    def __init__(self, path: Optional[str] = None) -> None:
        self._local_path = Path(path) if path else None
        self._repo_dir: Path = self._local_path or CACHE_DIR
        self._records: List[EvalRecord] = []

    def verify_requirements(self) -> List[str]:
        issues: List[str] = []
        if self._local_path is None and shutil.which("git") is None:
            issues.append(
                "git binary not found. Install git to clone LiveResearchBench."
            )
        return issues

    def _ensure_repo(self) -> Path:
        """Clone the repo if not already cached. Returns repo dir."""
        if self._local_path is not None:
            if not self._local_path.exists():
                raise FileNotFoundError(
                    f"LiveResearchBench path not found: {self._local_path}"
                )
            return self._local_path

        if not self._repo_dir.exists():
            LOGGER.info("Cloning LiveResearchBench from %s ...", LIVERESEARCH_REPO)
            self._repo_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    LIVERESEARCH_REPO,
                    str(self._repo_dir),
                ],
                check=True,
                capture_output=True,
            )
            LOGGER.info("LiveResearchBench cloned to %s", self._repo_dir)

        return self._repo_dir

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        repo_dir = self._ensure_repo()

        # Load queries
        query_path = repo_dir / "data" / "prompt_data" / "query.jsonl"
        if not query_path.exists():
            raise FileNotFoundError(f"Query file not found: {query_path}")

        queries = _load_jsonl(query_path)
        if not queries:
            raise FileNotFoundError(f"No queries found in {query_path}")

        # Load criteria (optional — used for rubric-based scoring)
        criteria_path = repo_dir / "data" / "criteria_data" / "criteria.jsonl"
        criteria_index: Dict[int, Dict[str, Any]] = {}
        if criteria_path.exists():
            criteria_records = _load_jsonl(criteria_path)
            criteria_index = _build_criteria_index(criteria_records)
            LOGGER.info(
                "Loaded %d criteria records for rubric scoring", len(criteria_index)
            )

        # Optionally filter by language via split (e.g. split="en" or split="zh")
        if split and split in ("en", "zh"):
            queries = [q for q in queries if q.get("language") == split]

        if seed is not None:
            random.Random(seed).shuffle(queries)
        if max_samples is not None:
            queries = queries[:max_samples]

        self._records = []
        for query in queries:
            q_id = query.get("id")
            topic = query.get("topic", "")
            language = query.get("language", "en")
            prompt = query.get("prompt", "")

            if not prompt:
                LOGGER.warning("Skipping query %s: empty prompt", q_id)
                continue

            # Build the research task prompt
            research_prompt = (
                "You are a deep research assistant. Conduct thorough research "
                "on the following topic and produce a comprehensive, well-structured "
                "research report with citations and analysis.\n\n"
                f"## Research Task\n\n{prompt}"
            )

            # Attach criteria metadata if available
            criteria = criteria_index.get(int(q_id)) if q_id is not None else None
            metadata: Dict[str, Any] = {
                "topic": topic,
                "language": language,
                "original_id": q_id,
            }

            if criteria:
                metadata["dimension_weight"] = criteria.get("dimension_weight", {})
                metadata["criterions"] = criteria.get("criterions", {})

            self._records.append(
                EvalRecord(
                    record_id=f"liveresearch-{q_id or len(self._records)}",
                    problem=research_prompt,
                    reference="",  # No single reference answer; rubric-based
                    category="agentic",
                    subject=topic,
                    metadata=metadata,
                )
            )

        LOGGER.info("LiveResearchBench: loaded %d tasks", len(self._records))

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["LiveResearchBenchDataset"]
