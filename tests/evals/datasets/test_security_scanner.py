"""Tests for the security_scanner dataset."""

from friday_ai.evals.datasets.security_scanner import SecurityScannerDataset


def test_dataset_loads():
    ds = SecurityScannerDataset()
    ds.load(max_samples=5, seed=42)
    assert ds.size() == 5


def test_dataset_full_size():
    ds = SecurityScannerDataset()
    ds.load()
    assert ds.size() == 30


def test_record_structure():
    ds = SecurityScannerDataset()
    ds.load(max_samples=1, seed=42)
    record = next(ds.iter_records())
    assert record.record_id.startswith("security-scanner-")
    assert record.category == "agentic"
    assert "security" in record.problem.lower() or "scan" in record.problem.lower()
    assert record.metadata.get("project_files")
    assert record.metadata.get("vulnerabilities")
    assert isinstance(record.metadata["vulnerabilities"], list)
    assert record.metadata.get("safe_patterns") is not None


def test_difficulty_tiers():
    ds = SecurityScannerDataset()
    ds.load()
    subjects = {r.subject for r in ds.iter_records()}
    assert "easy" in subjects
    assert "medium" in subjects
    assert "hard" in subjects


def test_vulnerability_structure():
    ds = SecurityScannerDataset()
    ds.load(max_samples=1, seed=0)
    record = next(ds.iter_records())
    vuln = record.metadata["vulnerabilities"][0]
    assert "file" in vuln
    assert "type" in vuln
    assert "severity" in vuln
    assert "description" in vuln
