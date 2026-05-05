"""Tests for continuous-score reporting and judge-response reparsing.

Covers the ``mean_continuous_score`` family of fields in summary.json,
the ``_safe_json_loads`` parser tolerating multi-line ``notes``, and
the ``evals reparse-judge`` CLI.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from openjarvis.evals.cli import main as cli_main
from openjarvis.evals.core.runner import EvalRunner, _extract_continuous_score
from openjarvis.evals.core.types import EvalRecord, RunConfig
from openjarvis.evals.scorers.liveresearch import (
    _escape_newlines_inside_strings,
    _parse_judge_response,
    _safe_json_loads,
    rescore_from_metadata,
)


def _make_dataset(records):
    """Build a minimal MagicMock dataset that yields the given records."""
    ds = MagicMock(spec=["load", "iter_records"])
    ds.load = MagicMock()
    ds.iter_records = MagicMock(return_value=list(records))
    return ds


def _make_backend(content="answer"):
    backend = MagicMock()
    backend.generate_full = MagicMock(return_value={
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        "latency_seconds": 0.1,
    })
    return backend


class _ContinuousScorer:
    """A scorer that returns a fixed continuous score in scoring_meta."""

    def __init__(self, scores):
        self._scores = list(scores)
        self._idx = 0

    def score(self, record, model_answer):
        v = self._scores[self._idx]
        self._idx += 1
        return v >= 0.5, {"score": float(v)}


# ---------------------------------------------------------------------------
# Part A: continuous-score fields in summary.json
# ---------------------------------------------------------------------------


def test_continuous_score_fields_present_in_summary(tmp_path):
    """End-to-end: runner exposes the continuous-score family in summary.json."""
    records = [
        EvalRecord(record_id=f"r{i}", problem="q", reference="a", category="chat")
        for i in range(5)
    ]
    dataset = _make_dataset(records)
    backend = _make_backend()
    # Mix of scores spanning the > 0.5 / 0.7 / 0.8 / 0.9 thresholds.
    scorer = _ContinuousScorer([0.10, 0.55, 0.72, 0.85, 0.95])

    out = tmp_path / "out.jsonl"
    cfg = RunConfig(
        benchmark="test",
        backend="jarvis-direct",
        model="test-model",
        output_path=str(out),
    )
    runner = EvalRunner(cfg, dataset, backend, scorer)
    summary = runner.run()

    summary_path = out.with_suffix(".summary.json")
    payload = json.loads(summary_path.read_text())

    for key in (
        "mean_continuous_score",
        "median_continuous_score",
        "pct_above_0.5",
        "pct_above_0.7",
        "pct_above_0.8",
        "pct_above_0.9",
    ):
        assert key in payload, f"missing {key}"
        assert isinstance(payload[key], (int, float))

    assert payload["mean_continuous_score"] == pytest.approx(
        sum([0.10, 0.55, 0.72, 0.85, 0.95]) / 5, abs=1e-6
    )
    assert payload["pct_above_0.5"] == pytest.approx(4 / 5)
    assert payload["pct_above_0.7"] == pytest.approx(3 / 5)
    assert payload["pct_above_0.8"] == pytest.approx(2 / 5)
    assert payload["pct_above_0.9"] == pytest.approx(1 / 5)

    # Existing accuracy field still present (binary, score >= 0.5)
    assert payload["accuracy"] == pytest.approx(4 / 5)
    # Continuous score also reflected on the in-memory summary.
    assert summary.mean_continuous_score is not None
    assert summary.pct_above_0_5 == pytest.approx(4 / 5)


# Part B: parser handles multi-line notes and non-JSON quirks

MULTILINE_RAW_PART1 = """{
  "scores": {
    "comprehensiveness": 6,
    "insight": 5,
    "instruction_following": 6,
    "readability": 7
  },"""

MULTILINE_RAW_PART2 = """
  "weighted_total": 6.0,
  "notes": "Comprehensiveness (6): covers many topics
but omits recent developments.

Insight (5): Mostly descriptive analysis,
limited original perspectives."
}"""

MULTILINE_RAW = MULTILINE_RAW_PART1 + MULTILINE_RAW_PART2

def test_judge_parser_handles_multiline_notes():
    """Multi-line notes strings (invalid JSON) are still recoverable."""
    parsed = _parse_judge_response(MULTILINE_RAW)
    scores = parsed["scores"]
    assert scores["comprehensiveness"] == 6
    assert scores["insight"] == 5
    assert scores["instruction_following"] == 6
    assert scores["readability"] == 7
    assert parsed["weighted_total"] == pytest.approx(6.0)


def test_safe_json_loads_strict_first():
    """Strict JSON still parses through the permissive helper."""
    payload = chr(123) + chr(34) + "a" + chr(34) + ": 1" + chr(125)
    assert _safe_json_loads(payload) == {"a": 1}


def test_escape_newlines_only_inside_strings():
    """Newlines outside string spans are preserved (structure-preserving)."""
    txt = (
        chr(123) + "\n  " + chr(34) + "a" + chr(34) + ": "
        + chr(34) + "x\ny" + chr(34) + "\n" + chr(125)
    )
    out = _escape_newlines_inside_strings(txt)
    assert out.startswith(chr(123) + "\n")
    assert "\\n" in out
    assert json.loads(out) == {"a": "x\ny"}


# ---------------------------------------------------------------------------
# Part C: reparse-judge CLI
# ---------------------------------------------------------------------------


def _make_jsonl(path, recs):
    with open(path, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + chr(10))


def test_reparse_judge_idempotent(tmp_path):
    """A clean JSONL is unchanged when re-parsed."""
    rec = {
        "record_id": "r1",
        "benchmark": "liveresearch",
        "model": "test",
        "is_correct": True,
        "score": 0.7,
        "scoring_metadata": {
            "score": 0.7,
            "dimension_scores": {
                "comprehensiveness": 7,
                "insight": 7,
                "instruction_following": 7,
                "readability": 7,
            },
        },
    }
    in_path = tmp_path / "in.jsonl"
    _make_jsonl(in_path, [rec])

    runner = CliRunner()
    out_path = tmp_path / "out.jsonl"
    result = runner.invoke(
        cli_main,
        ["reparse-judge", "--jsonl", str(in_path), "--out", str(out_path)],
    )
    assert result.exit_code == 0, result.output
    out_recs = [json.loads(line) for line in out_path.read_text().splitlines() if line]
    assert len(out_recs) == 1
    assert out_recs[0]["score"] == pytest.approx(0.7)
    assert out_recs[0]["is_correct"] is True
    # The accuracy in summary is unchanged.
    summary_path = out_path.with_suffix(out_path.suffix + ".summary.json")
    summary = json.loads(summary_path.read_text())
    assert summary["accuracy"] == 1.0
    assert summary["reparse_records_recovered"] == 0


def test_reparse_judge_recovers_failed_record(tmp_path):
    """A record with score=0 + parseable raw_judge_output is recovered."""
    raw = MULTILINE_RAW
    rec = {
        "record_id": "r1",
        "benchmark": "liveresearch",
        "model": "test",
        "is_correct": False,
        "score": 0.0,
        "scoring_metadata": {
            "score": 0.0,
            "dimension_scores": {},
            "raw_judge_output": raw,
        },
    }
    in_path = tmp_path / "in.jsonl"
    _make_jsonl(in_path, [rec])

    runner = CliRunner()
    out_path = tmp_path / "out.jsonl"
    result = runner.invoke(
        cli_main,
        ["reparse-judge", "--jsonl", str(in_path), "--out", str(out_path)],
    )
    assert result.exit_code == 0, result.output
    out_recs = [json.loads(line) for line in out_path.read_text().splitlines() if line]
    assert len(out_recs) == 1
    rescued = out_recs[0]
    assert rescued["score"] > 0.0
    assert rescued["is_correct"] is True
    assert rescued["scoring_metadata"]["dimension_scores"] == {
        "comprehensiveness": 6.0,
        "insight": 5.0,
        "instruction_following": 6.0,
        "readability": 7.0,
    }
    summary_path = out_path.with_suffix(out_path.suffix + ".summary.json")
    summary = json.loads(summary_path.read_text())
    assert summary["reparse_records_recovered"] == 1
    assert summary["mean_continuous_score"] is not None


# ---------------------------------------------------------------------------
# extract_continuous_score helper unit tests
# ---------------------------------------------------------------------------


def test_extract_continuous_score_prefers_meta_score():
    assert _extract_continuous_score({"score": 0.42}, True) == pytest.approx(0.42)
    assert _extract_continuous_score({"score": 0.42}, False) == pytest.approx(0.42)


def test_extract_continuous_score_falls_back_to_binary():
    assert _extract_continuous_score({}, True) == 1.0
    assert _extract_continuous_score({}, False) == 0.0
    assert _extract_continuous_score({}, None) is None


def test_extract_continuous_score_clamps_out_of_range():
    assert _extract_continuous_score({"score": 1.5}, True) == 1.0
    assert _extract_continuous_score({"score": -0.1}, False) == 0.0


def test_rescore_from_metadata_returns_none_when_unparseable():
    assert rescore_from_metadata({"raw_judge_output": "totally not json"}) is None
    assert rescore_from_metadata({}) is None


