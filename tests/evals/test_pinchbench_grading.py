"""Tests for PinchBench grading functions."""

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.pinchbench import (
    _grade_automated,
    _parse_judge_response,
    _summarize_transcript,
    grade_pinchbench_task,
)


def _make_record(**meta_overrides) -> EvalRecord:
    meta = {
        "grading_type": "automated",
        "automated_checks": None,
        "llm_judge_rubric": None,
        "grading_weights": None,
    }
    meta.update(meta_overrides)
    return EvalRecord(
        record_id="test_task",
        problem="Do the thing",
        reference="Expected behavior",
        category="test",
        subject="Test Task",
        metadata=meta,
    )


class TestGradeAutomated:
    def test_simple_pass(self, tmp_path):
        code = """
def grade(transcript, workspace_path):
    from pathlib import Path
    f = Path(workspace_path) / "output.txt"
    return {"file_exists": 1.0 if f.exists() else 0.0}
"""
        (tmp_path / "output.txt").write_text("hello")
        record = _make_record(automated_checks=code)
        result = _grade_automated(record, [], str(tmp_path))
        assert result["score"] == 1.0
        assert result["breakdown"]["file_exists"] == 1.0

    def test_simple_fail(self, tmp_path):
        code = """
def grade(transcript, workspace_path):
    from pathlib import Path
    f = Path(workspace_path) / "output.txt"
    return {"file_exists": 1.0 if f.exists() else 0.0}
"""
        record = _make_record(automated_checks=code)
        result = _grade_automated(record, [], str(tmp_path))
        assert result["score"] == 0.0

    def test_transcript_inspection(self, tmp_path):
        code = """
def grade(transcript, workspace_path):
    used_read = False
    for entry in transcript:
        if entry.get("type") == "message":
            msg = entry.get("message", {})
            if msg.get("role") == "assistant":
                for item in msg.get("content", []):
                    name = item.get("name")
                    if item.get("type") == "toolCall" and name == "read_file":
                        used_read = True
    return {"used_read_file": 1.0 if used_read else 0.0}
"""
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "read_file",
                            "params": {"path": "a.txt"},
                        }
                    ],
                },
            }
        ]
        record = _make_record(automated_checks=code)
        result = _grade_automated(record, transcript, str(tmp_path))
        assert result["score"] == 1.0

    def test_no_checks_returns_zero(self, tmp_path):
        record = _make_record(automated_checks=None)
        result = _grade_automated(record, [], str(tmp_path))
        assert result["score"] == 0.0


class TestParseJudgeResponse:
    def test_json_code_block(self):
        raw = (
            '```json\n{"scores": {"quality": 0.8}, "total": 0.8, "notes": "good"}\n```'
        )
        parsed = _parse_judge_response(raw)
        assert parsed["total"] == 0.8
        assert parsed["scores"]["quality"] == 0.8

    def test_bare_json(self):
        raw = 'The agent did well. {"scores": {"a": 0.9}, "total": 0.9, "notes": ""}'
        parsed = _parse_judge_response(raw)
        assert parsed["total"] == 0.9

    def test_regex_fallback(self):
        raw = "The agent performed reasonably. Overall score: 0.65"
        parsed = _parse_judge_response(raw)
        assert parsed["total"] == 0.65

    def test_empty_response(self):
        parsed = _parse_judge_response("")
        assert parsed["total"] == 0.0


class TestSummarizeTranscript:
    def test_tool_call_and_result(self):
        transcript = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "read_file",
                            "params": {"path": "a.txt"},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "content": [{"text": "file contents"}],
                },
            },
        ]
        summary = _summarize_transcript(transcript)
        assert 'Tool: read_file({"path": "a.txt"})' in summary
        assert "Result:" in summary


class TestGradeRouter:
    def test_routes_automated(self, tmp_path):
        code = 'def grade(t, w): return {"ok": 1.0}'
        record = _make_record(grading_type="automated", automated_checks=code)
        result = grade_pinchbench_task(
            record=record, transcript=[], workspace_path=str(tmp_path)
        )
        assert result["score"] == 1.0

    def test_unknown_type(self, tmp_path):
        record = _make_record(grading_type="unknown")
        result = grade_pinchbench_task(
            record=record, transcript=[], workspace_path=str(tmp_path)
        )
        assert result["score"] == 0.0
