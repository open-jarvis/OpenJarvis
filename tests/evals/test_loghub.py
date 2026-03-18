"""Tests for LogHub dataset provider."""

import csv
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.datasets.loghub import LogHubDataset
from openjarvis.evals.scorers.loghub_scorer import LogHubScorer


class TestLogHubDataset:
    def test_instantiation(self) -> None:
        ds = LogHubDataset()
        assert ds.dataset_id == "loghub"
        assert ds.dataset_name == "LogHub"

    def test_has_required_methods(self) -> None:
        ds = LogHubDataset()
        assert hasattr(ds, "load")
        assert hasattr(ds, "iter_records")
        assert hasattr(ds, "size")


class TestLogHubDatasetDetails:
    def test_invalid_subset_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown LogHub subset"):
            LogHubDataset(subset="nonexistent")

    def test_session_mode_parsing(self, tmp_path: Path) -> None:
        log_file = tmp_path / "HDFS.log"
        label_file = tmp_path / "anomaly_label.csv"

        log_file.write_text(
            "081109 event blk_123 info\n"
            "081109 event blk_123 detail\n"
            "081109 event blk_456 info\n"
        )
        with open(label_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["BlockId", "Label"])
            writer.writeheader()
            writer.writerow({"BlockId": "blk_123", "Label": "Anomaly"})
            writer.writerow({"BlockId": "blk_456", "Label": "Normal"})

        ds = LogHubDataset()
        meta = {
            "log_file": "HDFS.log",
            "label_file": "anomaly_label.csv",
            "mode": "session",
        }
        records = ds._load_session_mode(tmp_path, meta)

        assert len(records) == 2
        by_id = {r.metadata["block_id"]: r for r in records}
        assert by_id["blk_123"].reference == "anomaly"
        assert by_id["blk_456"].reference == "normal"
        assert by_id["blk_123"].category == "agentic"

    def test_window_mode_parsing(self, tmp_path: Path) -> None:
        log_file = tmp_path / "BGL.log"
        # 5 lines: 3 normal (start with -), 2 anomalous.
        # Window size 3 = 1 full + 1 partial
        lines = [
            "- normal line 1\n",
            "- normal line 2\n",
            "FATAL error line\n",
            "- normal line 3\n",
            "WARN warning line\n",
        ]
        log_file.write_text("".join(lines))

        ds = LogHubDataset(subset="bgl")
        meta = {"log_file": "BGL.log", "mode": "window", "window_size": 3}
        records = ds._load_window_mode(tmp_path, meta)

        assert len(records) == 2  # 1 full window + 1 partial
        assert records[0].reference == "anomaly"  # window 0 has "FATAL" line
        assert records[0].metadata["window_idx"] == 0
        # Window 1 has "WARN" line
        assert records[1].reference == "anomaly"
        assert records[1].metadata["num_lines"] == 2

    def test_size_before_load(self) -> None:
        ds = LogHubDataset()
        assert ds.size() == 0


def _mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.generate.return_value = "A"
    return backend


class TestLogHubScorer:
    def test_instantiation(self) -> None:
        s = LogHubScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "loghub"

    def test_exact_match_anomaly(self) -> None:
        s = LogHubScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="test-1",
            problem="analyze logs",
            reference="anomaly",
            category="agentic",
        )
        is_correct, meta = s.score(record, "ANOMALY\nThe logs show errors.")
        assert is_correct is True
        assert meta["match_type"] == "exact"

    def test_exact_match_normal(self) -> None:
        s = LogHubScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="test-2",
            problem="analyze logs",
            reference="normal",
            category="agentic",
        )
        is_correct, meta = s.score(record, "NORMAL - no issues detected")
        assert is_correct is True

    def test_empty_response(self) -> None:
        s = LogHubScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="test-3",
            problem="analyze logs",
            reference="anomaly",
            category="agentic",
        )
        is_correct, meta = s.score(record, "")
        assert is_correct is False
        assert meta["reason"] == "empty_response"

    def test_wrong_classification(self) -> None:
        s = LogHubScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="test-4",
            problem="analyze logs",
            reference="anomaly",
            category="agentic",
        )
        is_correct, meta = s.score(record, "NORMAL - everything looks fine")
        assert is_correct is False


class TestLogHubCLI:
    def test_in_benchmarks_dict(self) -> None:
        from openjarvis.evals.cli import BENCHMARKS

        assert "loghub" in BENCHMARKS
        assert BENCHMARKS["loghub"]["category"] == "agentic"

    def test_build_dataset(self) -> None:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset("loghub")
        assert ds is not None
        assert ds.dataset_id == "loghub"

    def test_build_scorer(self) -> None:
        from openjarvis.evals.cli import _build_scorer

        s = _build_scorer("loghub", _mock_backend(), "test-model")
        assert s is not None
        assert s.scorer_id == "loghub"
