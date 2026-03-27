"""FRAMES benchmark dataset (google/frames-benchmark).

Adapted from IPW's frames.py dataset loader.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_DEFAULT_INPUT_PROMPT = """Please answer the question below. You should:

- Return only your answer, which should be a number, or a short phrase with as few words as possible, or a comma separated list of numbers and/or strings.
- If the answer is a number, return only the number without any units unless specified otherwise.
- If the answer is a string, don't include articles, and don't use abbreviations (e.g. for states).
- If the answer is a comma separated list, apply the above rules to each element in the list.
- This question may require multi-hop reasoning across multiple Wikipedia articles.
{wiki_context}

Here is the question:

{question}"""


class FRAMESDataset(DatasetProvider):
    """FRAMES multi-hop factual retrieval benchmark."""

    dataset_id = "frames"
    dataset_name = "FRAMES"

    _hf_path = "google/frames-benchmark"
    _default_split = "test"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        from datasets import load_dataset

        use_split = split or self._default_split
        dataset = load_dataset(self._hf_path, split=use_split)

        rows: Sequence[MutableMapping[str, object]]
        if hasattr(dataset, "to_list"):
            rows = dataset.to_list()
        else:
            rows = list(dataset)

        if seed is not None:
            rng = random.Random(seed)
            rows = list(rows)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, raw in enumerate(rows):
            record = self._convert_row(raw, idx)
            if record is not None:
                self._records.append(record)

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _convert_row(
        self,
        raw: MutableMapping[str, object],
        idx: int,
    ) -> Optional[EvalRecord]:
        question = str(
            raw.get("Prompt") or raw.get("prompt") or raw.get("question") or ""
        ).strip()
        answer = str(
            raw.get("Answer") or raw.get("answer") or raw.get("gold_answer") or ""
        ).strip()

        if not question or not answer:
            return None

        # Extract reasoning types
        reasoning = raw.get("reasoning_types", raw.get("reasoning_type", ""))
        if isinstance(reasoning, list):
            reasoning = ", ".join(str(r) for r in reasoning)
        reasoning = str(reasoning)

        # Extract wiki links
        wiki_links_raw = raw.get("wiki_links", raw.get("wikipedia_links", []))
        if isinstance(wiki_links_raw, str):
            wiki_links = [
                link.strip() for link in wiki_links_raw.split(",") if link.strip()
            ]
        elif isinstance(wiki_links_raw, list):
            wiki_links = [str(link) for link in wiki_links_raw]
        else:
            wiki_links = []

        # Build wiki context
        wiki_context = ""
        if wiki_links:
            wiki_context = (
                "\n\nRelevant Wikipedia articles that may help answer this question:\n"
                + "\n".join(f"- {link}" for link in wiki_links)
            )

        problem = _DEFAULT_INPUT_PROMPT.format(
            question=question,
            wiki_context=wiki_context,
        )

        subject = reasoning if reasoning else "general"

        metadata = {
            "index": idx,
            "reasoning_types": reasoning,
            "wiki_links": wiki_links,
        }

        return EvalRecord(
            record_id=f"frames-{idx}",
            problem=problem,
            reference=answer,
            category="rag",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["FRAMESDataset"]
