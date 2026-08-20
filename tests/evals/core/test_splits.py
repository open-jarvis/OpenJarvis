# tests/evals/core/test_splits.py
from __future__ import annotations

import pytest

from openjarvis.evals.core.splits import apply_split


def test_train_is_first_20_percent():
    items = list(range(100))
    train = apply_split(items, split="train", seed=42, train_frac=0.2)
    assert len(train) == 20


def test_test_is_remaining_80_percent():
    items = list(range(100))
    test = apply_split(items, split="test", seed=42, train_frac=0.2)
    assert len(test) == 80


def test_train_and_test_are_disjoint():
    items = list(range(100))
    train = apply_split(items, split="train", seed=42, train_frac=0.2)
    test = apply_split(items, split="test", seed=42, train_frac=0.2)
    assert set(train).isdisjoint(set(test))


def test_train_union_test_equals_all_shuffled():
    items = list(range(100))
    train = apply_split(items, split="train", seed=42, train_frac=0.2)
    test = apply_split(items, split="test", seed=42, train_frac=0.2)
    allx = apply_split(items, split="all", seed=42, train_frac=0.2)
    assert sorted(train + test) == sorted(allx)


def test_all_returns_shuffled_copy():
    items = list(range(100))
    allx = apply_split(items, split="all", seed=42, train_frac=0.2)
    assert len(allx) == 100
    assert set(allx) == set(items)


def test_deterministic_across_calls():
    items = list(range(100))
    a = apply_split(items, split="train", seed=42, train_frac=0.2)
    b = apply_split(items, split="train", seed=42, train_frac=0.2)
    assert a == b


def test_different_seeds_give_different_order():
    items = list(range(100))
    a = apply_split(items, split="train", seed=42, train_frac=0.2)
    b = apply_split(items, split="train", seed=43, train_frac=0.2)
    assert a != b


def test_invalid_split_raises():
    with pytest.raises(ValueError, match=r"split must be one of train/test/all"):
        apply_split([1, 2, 3], split="foo", seed=42, train_frac=0.2)


@pytest.mark.parametrize("bad_frac", [0.0, 1.0, -0.5, 1.5])
def test_rejects_train_frac_out_of_range(bad_frac):
    with pytest.raises(ValueError, match=r"train_frac must be in \(0, 1\)"):
        apply_split([1, 2, 3], split="train", seed=42, train_frac=bad_frac)


def test_does_not_mutate_input():
    items = list(range(10))
    snapshot = items[:]
    apply_split(items, split="train", seed=42, train_frac=0.8)
    assert items == snapshot
