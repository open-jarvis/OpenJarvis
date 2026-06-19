"""Loader + answer verifier for HotpotQA (``hotpotqa/hotpot_qa``).

HotpotQA is multi-hop Wikipedia QA: each task is a question with a short
factoid ``answer`` and a difficulty ``level`` (easy/medium/hard). We use it as
the orchestrator SFT cold-start source because (a) answers are exact-match
verifiable, so rejection sampling needs **no LLM judge**, and (b) solving a
question requires ``web_search`` + multi-step reasoning, which is exactly the
local↔cloud routing signal we want to teach.

We load the ``fullwiki`` config (the agent must retrieve from all of Wikipedia
rather than being handed the gold paragraphs); we only keep ``question`` /
``answer`` / ``level`` / ``type`` since the orchestrator does its own retrieval.

``load_hotpotqa`` streams via the HuggingFace ``datasets`` library; tests pass
``source=`` an iterable of raw row dicts so normalization is exercised offline.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional

DATASET_ID = "hotpotqa/hotpot_qa"
CONFIG = "fullwiki"
SPLIT = "validation"  # train/validation carry gold answers; test does not


@dataclass
class HotpotTask:
    task_id: str
    question: str
    answer: str
    level: str = ""   # easy | medium | hard
    qtype: str = ""   # comparison | bridge

    # Parity with ToolScaleTask so the rejection-sampling loop is dataset-agnostic.
    @property
    def instruction(self) -> str:
        return self.question

    @property
    def domain(self) -> str:
        return f"hotpotqa/{self.level or 'unknown'}"


def normalize_row(row: Dict[str, Any], *, index: int = 0) -> Optional[HotpotTask]:
    """Turn one raw HotpotQA row into a :class:`HotpotTask` (pure)."""
    question = str(row.get("question") or "").strip()
    answer = str(row.get("answer") or "").strip()
    if not question or not answer:
        return None
    task_id = str(row.get("id") or row.get("_id") or f"hotpotqa-{index}")
    return HotpotTask(
        task_id=task_id,
        question=question,
        answer=answer,
        level=str(row.get("level") or ""),
        qtype=str(row.get("type") or ""),
    )


def load_hotpotqa(
    *,
    max_tasks: Optional[int] = None,
    split: str = SPLIT,
    config: str = CONFIG,
    source: Optional[Iterable[Dict[str, Any]]] = None,
) -> Iterator[HotpotTask]:
    """Yield normalized HotpotQA tasks.

    ``source`` overrides the HF stream with an iterable of raw row dicts (tests).
    When ``source`` is None, streams ``hotpotqa/hotpot_qa`` via ``datasets``.
    """
    if source is None:
        from datasets import load_dataset  # lazy: optional dep / network

        source = load_dataset(DATASET_ID, config, split=split, streaming=True)

    n = 0
    for i, row in enumerate(source):
        if max_tasks is not None and n >= max_tasks:
            break
        task = normalize_row(dict(row), index=i)
        if task is None:
            continue
        yield task
        n += 1


# --- answer verification (official HotpotQA-style normalization) -------------


def _normalize_answer(s: str) -> str:
    """Lowercase, strip punctuation / articles / extra whitespace (SQuAD/HotpotQA)."""
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def _f1(pred: str, gold: str) -> float:
    pt, gt = _normalize_answer(pred).split(), _normalize_answer(gold).split()
    if not pt or not gt:
        return float(pt == gt)
    common: Dict[str, int] = {}
    for w in pt:
        if w in gt:
            common[w] = common.get(w, 0) + 1
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pt)
    recall = num_same / len(gt)
    return 2 * precision * recall / (precision + recall)


def answer_matches(prediction: str, gold: str, *, f1_threshold: float = 0.6) -> bool:
    """True if ``prediction`` (free-form) contains / matches the gold answer.

    The orchestrator answers in prose, so we accept (a) the normalized gold as a
    whole-word substring of the prediction, or (b) token-F1 >= threshold. This is
    the dependency-free, no-LLM verifier that makes rejection sampling automatic.
    """
    np, ng = _normalize_answer(prediction), _normalize_answer(gold)
    if not ng:
        return False
    if f" {ng} " in f" {np} ":
        return True
    return _f1(prediction, gold) >= f1_threshold


def make_verifier(f1_threshold: float = 0.6):
    """Return a ``verify_fn(task, rollout) -> bool`` for the rejection sampler."""

    def verify(task: HotpotTask, rollout: Any) -> bool:
        ans = getattr(rollout, "final_answer", "") or ""
        if not ans.strip():
            return False
        return answer_matches(ans, task.answer, f1_threshold=f1_threshold)

    return verify


__all__ = [
    "CONFIG",
    "DATASET_ID",
    "HotpotTask",
    "SPLIT",
    "answer_matches",
    "load_hotpotqa",
    "make_verifier",
    "normalize_row",
]
