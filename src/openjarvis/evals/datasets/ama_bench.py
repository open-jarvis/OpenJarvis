"""AMA-Bench dataset loader.

Reference dataset:
https://huggingface.co/datasets/AMA-bench/AMA-bench

Paper: https://arxiv.org/abs/2602.22769

This implementation follows the published schema with fields like:
- episode_id
- task / task_type / domain / source / success / num_turns / total_tokens
- trajectory: list[{turn_idx, action, observation}]
- qa_pairs: list[{question, answer, question_uuid, type}]

Evaluation protocol follows the paper's long-context baseline: pack the
trajectory into the model input, reserving space for the question and answer.
When a trajectory exceeds the budget, truncation preserves the first 50% and
last 50% of the token budget (matching Appendix B of the paper).
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_HF_REPO_ID = "AMA-bench/AMA-bench"
_DEFAULT_SPLIT = "test"
# Token budget for trajectory context.
# Approximate chars ≈ tokens * 4.
# Budget is intentionally conservative: max_model_len (typically 32K) minus
# output tokens (4K), agent/system-prompt overhead (~4K for tools + instructions),
# and a safety margin.  This leaves 20K for the trajectory itself.
_DEFAULT_MAX_TRAJECTORY_TOKENS = 20_000
_CHARS_PER_TOKEN_ESTIMATE = 4

_QUESTION_TYPE_TO_SUBJECT = {
    "A": "recall",
    "B": "causal_inference",
    "C": "state_updating",
    "D": "state_abstraction",
}


class AMABenchDataset(DatasetProvider):
    """AMA-Bench agent memory assessment benchmark."""

    dataset_id = "ama-bench"
    dataset_name = "AMA-Bench"

    def __init__(
        self,
        subset: str = "default",
        cache_dir: Optional[str] = None,
        max_trajectory_tokens: Optional[int] = None,
    ) -> None:
        if subset not in ("default", ""):
            raise ValueError(
                f"AMA-Bench supports only subset='default', got {subset!r}",
            )
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._max_traj_tokens = max_trajectory_tokens or _DEFAULT_MAX_TRAJECTORY_TOKENS
        self._records: List[EvalRecord] = []
        self._episodes: List[List[EvalRecord]] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        rows = self._load_from_hf(split=split or _DEFAULT_SPLIT)

        if seed is not None:
            random.Random(seed).shuffle(rows)
        if max_samples is not None:
            rows = rows[:max_samples]

        self._episodes = []
        self._records = []
        for row in rows:
            episode = self._row_to_episode(row)
            self._episodes.append(episode)
            self._records.extend(episode)

        if not self._records:
            raise RuntimeError(
                "AMA-Bench loaded zero records. "
                "Check network access and dataset availability.",
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def iter_episodes(self) -> Iterable[List[EvalRecord]]:
        """Yield grouped QA pairs per trajectory for episode mode."""
        return iter(self._episodes)

    def size(self) -> int:
        return len(self._records)

    def _load_from_hf(self, *, split: str) -> List[Dict[str, Any]]:
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError(
                "The 'datasets' package is required for AMA-Bench. "
                "Install with: pip install datasets",
            ) from exc

        kwargs: Dict[str, Any] = {"split": split}
        if self._cache_dir is not None:
            kwargs["cache_dir"] = str(self._cache_dir)

        dataset = load_dataset(
            _HF_REPO_ID,
            **kwargs,
        )
        rows: Sequence[Dict[str, Any]]
        if hasattr(dataset, "to_list"):
            rows = dataset.to_list()
        else:
            rows = list(dataset)
        return [dict(row) for row in rows]

    def _row_to_episode(
        self,
        row: Dict[str, Any],
    ) -> List[EvalRecord]:
        """Convert one AMA-Bench episode row to EvalRecord(s)."""
        episode_id = str(row.get("episode_id", "")).strip()
        if not episode_id:
            raise ValueError("AMA-Bench row missing episode_id")

        trajectory = row.get("trajectory")
        if not isinstance(trajectory, list):
            raise ValueError(
                f"AMA-Bench episode {episode_id}: trajectory must be a list"
            )

        qa_pairs = row.get("qa_pairs")
        if not isinstance(qa_pairs, list) or not qa_pairs:
            raise ValueError(
                f"AMA-Bench episode {episode_id}: qa_pairs must be a non-empty list"
            )

        task = str(row.get("task", "")).strip()
        domain = str(row.get("domain", "")).strip() or "general"
        task_type = str(row.get("task_type", "")).strip()
        source = str(row.get("source", "")).strip()
        success = bool(row.get("success", False))
        num_turns = int(row.get("num_turns", 0) or 0)
        total_tokens = int(row.get("total_tokens", 0) or 0)

        trajectory_text = self._format_trajectory(trajectory)

        max_chars = self._max_traj_tokens * _CHARS_PER_TOKEN_ESTIMATE
        if len(trajectory_text) > max_chars:
            original_len = len(trajectory_text)
            trajectory_text = self._truncate_trajectory_text(
                trajectory_text,
                max_chars,
            )
            LOGGER.info(
                "AMA-Bench episode %s: trajectory truncated from %d to %d chars "
                "(first 50%% + last 50%% of budget kept per Appendix B)",
                episode_id,
                original_len,
                len(trajectory_text),
            )

        records: List[EvalRecord] = []
        for question_index, qa in enumerate(qa_pairs):
            if not isinstance(qa, dict):
                raise ValueError(
                    f"AMA-Bench episode {episode_id}: qa_pairs[{question_index}] must be a dict",
                )

            question = str(qa.get("question", "")).strip()
            answer = str(qa.get("answer", "")).strip()
            if not question or not answer:
                raise ValueError(
                    f"AMA-Bench episode {episode_id}: qa_pairs[{question_index}] "
                    "missing question or answer",
                )

            q_uuid = str(qa.get("question_uuid", "")).strip()
            q_type = str(qa.get("type", "")).strip()
            subject = _QUESTION_TYPE_TO_SUBJECT.get(q_type, "unknown")

            # Match the paper's long-context baseline: pack trajectory + question
            # into the model input without injecting eval-specific system prompts.
            problem = (
                f"## Task\n{task}\n\n"
                f"## Trajectory\n{trajectory_text}\n\n"
                f"## Question\n{question}"
            )

            records.append(
                EvalRecord(
                    record_id=(
                        f"ama-{episode_id}-{q_uuid}"
                        if q_uuid
                        else f"ama-{episode_id}-q{question_index}"
                    ),
                    problem=problem,
                    reference=answer,
                    category="agentic",
                    subject=subject,
                    metadata={
                        "episode_id": episode_id,
                        "task": task,
                        "task_type": task_type,
                        "source": source,
                        "domain": domain,
                        "success": success,
                        "num_turns": num_turns,
                        "total_tokens": total_tokens,
                        "question_index": question_index,
                        "question_uuid": q_uuid,
                        "question_type": q_type,
                        "capability": subject,
                    },
                )
            )

        return records

    @staticmethod
    def _format_trajectory(trajectory: Sequence[Any]) -> str:
        lines: List[str] = []
        for idx, turn in enumerate(trajectory):
            if not isinstance(turn, dict):
                raise ValueError(f"AMA-Bench trajectory turn {idx} is not a dict")
            turn_idx = turn.get("turn_idx", idx)
            action = str(turn.get("action", "")).strip()
            observation = str(turn.get("observation", "")).strip()
            lines.append(f"Turn {turn_idx}")
            lines.append(f"Action: {action}")
            lines.append("Observation:")
            lines.append(observation)
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _truncate_trajectory_text(
        trajectory_text: str,
        max_chars: int,
    ) -> str:
        """Truncate formatted trajectory text by keeping first 50% + last 50%
        of the character budget, discarding the middle.

        Follows Appendix B of the AMA-Bench paper: "we keep the first 50%
        and the last 50% budget length of the trajectory (by token count)
        and discard the middle portion to fit the context window."
        """
        separator = "\n\n[... middle portion truncated to fit context window ...]\n\n"
        budget_each = (max_chars - len(separator)) // 2
        if budget_each <= 0:
            return trajectory_text[:max_chars]
        return (
            trajectory_text[:budget_each] + separator + trajectory_text[-budget_each:]
        )


__all__ = ["AMABenchDataset"]
