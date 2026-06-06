"""Smoke test: each external-corpus provider loads and iterates records.

All three providers (ADP, ToolOrchestra, GeneralThoughts) are live and
point at their confirmed HF ids:
- adp            → neulab/agent-data-collection
- toolorchestra  → nvidia/ToolScale
- generalthoughts → natolambert/GeneralThought-430K-filtered

These tests download each dataset once to ~/.cache/huggingface and
verify the provider loads, iterates, and honours the split kwarg.
The ModuleNotFoundError skip branch is defensive — currently
unreachable since all three provider modules exist.

Marked ``hub``: they hit the live HuggingFace Hub, so they are excluded
from the default CI lane (which runs ``-m "not live and not cloud and not
hub"``) — a transient Hub outage or rate-limit must not redden ``main``.
Run them on demand with ``pytest -m hub``. The ADP provider swallows
per-config download errors and returns 0 records on a network failure
(see ``adp.py``), so a Hub outage surfaces here as ``assert 1 <= 0``
rather than an exception — another reason these can't run unguarded in CI.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.hub

PROVIDERS = [
    ("openjarvis.evals.datasets.adp", "ADPDataset"),
    ("openjarvis.evals.datasets.toolorchestra", "ToolOrchestraDataset"),
    ("openjarvis.evals.datasets.generalthoughts", "GeneralThoughtsDataset"),
]


@pytest.mark.slow
@pytest.mark.parametrize("mod_name,cls_name", PROVIDERS)
def test_external_provider_loads_and_iterates(mod_name, cls_name):
    """Download, load 5 records, assert they have record_id + non-empty problem."""
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError:
        pytest.skip(f"{mod_name} not implemented (HF id not found)")
    ds_cls = getattr(mod, cls_name)
    ds = ds_cls()
    ds.load(max_samples=5)
    records = list(ds.iter_records())
    assert 1 <= len(records) <= 5
    for r in records:
        assert r.record_id
        assert r.problem


@pytest.mark.slow
@pytest.mark.parametrize("mod_name,cls_name", PROVIDERS)
def test_external_provider_respects_split(mod_name, cls_name):
    """Train and test splits are disjoint when seed is held constant."""
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError:
        pytest.skip(f"{mod_name} not implemented (HF id not found)")
    ds_cls = getattr(mod, cls_name)
    train = ds_cls()
    train.load(split="train", seed=42, max_samples=20)
    test = ds_cls()
    test.load(split="test", seed=42, max_samples=20)
    train_ids = {r.record_id for r in train.iter_records()}
    test_ids = {r.record_id for r in test.iter_records()}
    if len(train_ids) + len(test_ids) < 10:
        pytest.skip("sample too small to verify disjointness meaningfully")
    assert train_ids.isdisjoint(test_ids)
