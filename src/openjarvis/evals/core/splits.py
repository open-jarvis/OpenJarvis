"""Deterministic train/test split helper used by dataset providers."""

from __future__ import annotations

import random
from typing import List, Literal, TypeVar

SplitName = Literal["train", "test", "all"]

T = TypeVar("T")


def apply_split(
    items: List[T],
    *,
    split: SplitName,
    seed: int,
    train_frac: float,
) -> List[T]:
    """Return a deterministic slice of ``items`` according to ``split``.

    The underlying permutation is ``random.Random(seed).shuffle(items_copy)``.
    ``train`` is the first ``int(len(items) * train_frac)`` entries of the
    shuffle, ``test`` is the remainder, ``all`` is the whole shuffle.
    """
    if split not in ("train", "test", "all"):
        raise ValueError(f"split must be one of train/test/all, got {split!r}")
    if not 0.0 < train_frac < 1.0:
        raise ValueError(f"train_frac must be in (0, 1), got {train_frac}")
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    if split == "all":
        return shuffled
    cut = int(len(shuffled) * train_frac)
    if split == "train":
        return shuffled[:cut]
    return shuffled[cut:]


__all__ = ["apply_split", "SplitName"]
