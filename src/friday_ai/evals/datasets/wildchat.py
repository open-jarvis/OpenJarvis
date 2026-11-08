"""WildChat dataset provider (allenai/WildChat-1M).

Filters to English single-turn conversations for chat quality evaluation.
"""

from __future__ import annotations

import random
from typing import Iterable, List, MutableMapping, Optional, Sequence

from friday_ai.evals.core.dataset import DatasetProvider
from friday_ai.evals.core.types import EvalRecord


class WildChatDataset(DatasetProvider):
    """WildChat conversation quality benchmark."""

    dataset_id = "wildchat"
    dataset_name = "WildChat"

    _hf_path = "allenai/WildChat-1M"
    _default_split = "train"

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

        # Filter to English single-turn conversations
        filtered: List[MutableMapping[str, object]] = []
        for row in rows:
            if not isinstance(row, MutableMapping):
                row = dict(row)

            language = str(row.get("language") or "").lower()
            if language != "english":
                continue

            conversation = row.get("conversation")
            if not isinstance(conversation, list):
                continue

            # Single-turn: exactly one user message and one assistant message
            if len(conversation) != 2:
                continue

            user_msg = conversation[0]
            asst_msg = conversation[1]
            if (
                str(user_msg.get("role", "")) != "user"
                or str(asst_msg.get("role", "")) != "assistant"
            ):
                continue

            user_content = str(user_msg.get("content", "")).strip()
            asst_content = str(asst_msg.get("content", "")).strip()
            if not user_content or not asst_content:
                continue

            row["_user_content"] = user_content
            row["_asst_content"] = asst_content
            filtered.append(row)

        # Shuffle with seed
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(filtered)

        if max_samples is not None:
            filtered = filtered[:max_samples]

        self._records = []
        for idx, raw in enumerate(filtered):
            self._records.append(
                EvalRecord(
                    record_id=f"wildchat-{idx}",
                    problem=raw["_user_content"],
                    reference=raw["_asst_content"],
                    category="chat",
                    subject="conversation",
                    metadata={
                        "model": str(raw.get("model", "")),
                        "language": "english",
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["WildChatDataset"]
