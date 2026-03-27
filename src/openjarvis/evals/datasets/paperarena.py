"""PaperArena: scientific literature reasoning benchmark.

Evaluates agents on research paper comprehension with three question types:
MC (multiple choice), CA (closed answer), OA (open answer) across
easy/medium/hard difficulty.
Source: https://github.com/Melmaphother/PaperArena
Paper: arXiv:2510.10909
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a scientific research assistant. Read the paper context carefully "
    "and answer the question. For multiple-choice questions, respond with just "
    "the letter (A, B, C, or D). For other questions, provide a precise answer."
)


class PaperArenaDataset(DatasetProvider):
    """PaperArena scientific literature reasoning benchmark.

    Three question types (MC, CA, OA) across three difficulty levels.
    """

    dataset_id = "paperarena"
    dataset_name = "PaperArena"

    def __init__(
        self,
        cache_dir: Optional[str] = None,
    ) -> None:
        self._cache_dir = (
            Path(cache_dir) if cache_dir else Path.home() / ".cache" / "paperarena"
        )
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        data_dir = self._cache_dir / "qa"

        if not data_dir.exists():
            self._download()

        records = self._load_records(data_dir)

        if seed is not None:
            random.Random(seed).shuffle(records)
        if max_samples is not None:
            records = records[:max_samples]

        self._records = records

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _download(self) -> None:
        """Download PaperArena data from HuggingFace or GitHub."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ImportError(
                "huggingface_hub required for PaperArena. "
                "Install with: pip install huggingface_hub"
            ) from exc

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading PaperArena dataset...")
        snapshot_download(
            repo_id="Melmaphother/PaperArena-Data",
            repo_type="dataset",
            local_dir=str(self._cache_dir),
        )

    def _load_records(self, data_dir: Path) -> List[EvalRecord]:
        """Load QA records from JSON/JSONL files."""
        records: List[EvalRecord] = []

        for p in sorted(data_dir.rglob("*.json")):
            try:
                with open(p) as f:
                    data = json.load(f)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    rec = self._item_to_record(item)
                    if rec is not None:
                        records.append(rec)
            except (json.JSONDecodeError, OSError):
                logger.debug("Skipping: %s", p)

        for p in sorted(data_dir.rglob("*.jsonl")):
            try:
                with open(p) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            item = json.loads(line)
                            rec = self._item_to_record(item)
                            if rec is not None:
                                records.append(rec)
            except (json.JSONDecodeError, OSError):
                logger.debug("Skipping: %s", p)

        return records

    def _item_to_record(self, item: Dict[str, Any]) -> Optional[EvalRecord]:
        """Convert a raw QA item to an EvalRecord."""
        question_id = item.get("question_id", item.get("id", ""))
        question_type = item.get("question_type", item.get("type", "OA")).upper()
        difficulty = item.get("difficulty", "medium").lower()
        question = item.get("question", "")
        context = item.get("context", item.get("paper_context", ""))
        reference = item.get("answer", item.get("reference", ""))
        options = item.get("options", None)
        tool_chain = item.get("minimal_tool_chain", [])

        if not question:
            return None

        # Build problem prompt
        prompt = f"{_SYSTEM_PROMPT}\n\n"
        if context:
            prompt += f"## Paper Context\n{context}\n\n"
        prompt += f"## Question\n{question}"

        if options and question_type == "MC":
            options_text = (
                "\n".join(f"  {k}) {v}" for k, v in options.items())
                if isinstance(options, dict)
                else "\n".join(f"  {chr(65 + i)}) {o}" for i, o in enumerate(options))
            )
            prompt += f"\n\nOptions:\n{options_text}"

        subject = f"{difficulty}_{question_type.lower()}"

        return EvalRecord(
            record_id=f"paperarena-{question_id}",
            problem=prompt,
            reference=str(reference),
            category="agentic",
            subject=subject,
            metadata={
                "question_id": question_id,
                "question_type": question_type,
                "difficulty": difficulty,
                "minimal_tool_chain": tool_chain,
            },
        )


__all__ = ["PaperArenaDataset"]
