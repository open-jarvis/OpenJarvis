"""Tests for the browser_assistant dataset."""

from friday_ai.evals.datasets.browser_assistant import (
    BrowserAssistantDataset,
)


def test_dataset_loads():
    ds = BrowserAssistantDataset()
    ds.load(max_samples=5, seed=42)
    assert ds.size() == 5


def test_dataset_full_size():
    ds = BrowserAssistantDataset()
    ds.load()
    assert ds.size() == 30


def test_record_structure():
    ds = BrowserAssistantDataset()
    ds.load(max_samples=1, seed=42)
    record = next(ds.iter_records())
    assert record.record_id.startswith("browser-assistant-")
    assert record.category == "agentic"
    assert record.metadata.get("question")
    assert record.metadata.get("expected_facts")
    assert isinstance(record.metadata["expected_facts"], list)


def test_fact_types():
    ds = BrowserAssistantDataset()
    ds.load(max_samples=1, seed=0)
    record = next(ds.iter_records())
    fact = record.metadata["expected_facts"][0]
    assert "fact" in fact
    assert "type" in fact
    assert fact["type"] in ("exact", "semantic")


def test_exact_semantic_split():
    ds = BrowserAssistantDataset()
    ds.load()
    has_exact = False
    has_semantic = False
    for r in ds.iter_records():
        if r.metadata.get("exact_facts"):
            has_exact = True
        if r.metadata.get("semantic_facts"):
            has_semantic = True
    assert has_exact
    assert has_semantic


def test_difficulty_tiers():
    ds = BrowserAssistantDataset()
    ds.load()
    subjects = {r.subject for r in ds.iter_records()}
    assert "easy" in subjects
    assert "medium" in subjects
    assert "hard" in subjects
