"""Tests for the coding_assistant dataset."""

from friday_ai.evals.datasets.coding_assistant import CodingAssistantDataset


def test_dataset_loads():
    ds = CodingAssistantDataset()
    ds.load(max_samples=5, seed=42)
    assert ds.size() == 5


def test_dataset_full_size():
    ds = CodingAssistantDataset()
    ds.load()
    assert ds.size() == 30


def test_record_structure():
    ds = CodingAssistantDataset()
    ds.load(max_samples=1, seed=42)
    record = next(ds.iter_records())
    assert record.record_id.startswith("coding-assistant-")
    assert record.category == "agentic"
    assert "Bug Report" in record.problem
    assert record.metadata.get("buggy_code")
    assert record.metadata.get("test_code")
    assert record.metadata.get("bugs")  # list of planted bugs
    assert record.metadata.get("originally_failing_tests")
    assert record.metadata.get("originally_passing_tests")


def test_difficulty_tiers():
    ds = CodingAssistantDataset()
    ds.load()
    subjects = {r.subject for r in ds.iter_records()}
    assert "easy" in subjects
    assert "medium" in subjects
    assert "hard" in subjects
