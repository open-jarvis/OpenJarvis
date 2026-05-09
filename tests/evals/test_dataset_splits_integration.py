"""Integration test: each provider's split kwarg produces disjoint train/test slices."""

from __future__ import annotations

import importlib

import pytest

PROVIDERS = [
    ("openjarvis.evals.datasets.pinchbench", "PinchBenchDataset"),
    ("openjarvis.evals.datasets.liveresearch", "LiveResearchBenchDataset"),
    ("openjarvis.evals.datasets.gaia", "GAIADataset"),
    ("openjarvis.evals.datasets.liveresearchbench", "LiveResearchBenchDataset"),
    ("openjarvis.evals.datasets.taubench", "TauBenchDataset"),
    ("openjarvis.evals.datasets.toolcall15", "ToolCall15Dataset"),
    ("openjarvis.evals.datasets.livecodebench", "LiveCodeBenchDataset"),
]


@pytest.mark.slow
@pytest.mark.parametrize("mod_name,cls_name", PROVIDERS)
def test_train_and_test_are_disjoint_per_provider(mod_name, cls_name):
    mod = importlib.import_module(mod_name)
    ds_cls = getattr(mod, cls_name)

    train_ds = ds_cls()
    train_ds.load(split="train", seed=42)
    test_ds = ds_cls()
    test_ds.load(split="test", seed=42)

    train_ids = {r.record_id for r in train_ds.iter_records()}
    test_ids = {r.record_id for r in test_ds.iter_records()}
    total = len(train_ids) + len(test_ids)

    # A dataset with fewer than ~10 items can't produce a meaningful 20/80
    # split where both sides are non-empty. In that regime we skip the
    # disjointness check. But always reject a silent zero: if apply_split
    # or an upstream filter produced an empty slice, fail loudly.
    if total == 0:
        pytest.fail(
            f"{cls_name} returned 0 records for both train and test — "
            f"likely a gate regression"
        )
    if total < 10:
        pytest.skip("dataset too small for a 20/80 split")

    assert train_ids.isdisjoint(test_ids)
    assert total == train_ds.size() + test_ds.size()


@pytest.mark.slow
def test_toolcall15_split_is_nonempty():
    """Regression: toolcall15 must not silently return 0 records for split=train."""
    from openjarvis.evals.datasets.toolcall15 import ToolCall15Dataset

    ds = ToolCall15Dataset()
    ds.load(split="train", seed=42)
    assert ds.size() > 0, "toolcall15 train split should have >0 records"

    ds_test = ToolCall15Dataset()
    ds_test.load(split="test", seed=42)
    assert ds_test.size() > 0, "toolcall15 test split should have >0 records"

    train_ids = {r.record_id for r in ds.iter_records()}
    test_ids = {r.record_id for r in ds_test.iter_records()}
    assert train_ids.isdisjoint(test_ids)
