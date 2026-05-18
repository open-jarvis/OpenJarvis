"""Tests for openjarvis.learning.spec_search.diagnose.runner module.

All tests use mocked dependencies — no live API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


def _make_engine_response(content: str, tool_calls: list | None = None) -> dict:
    """Create a mock engine.generate() response."""
    resp = {
        "content": content,
        "finish_reason": "stop" if not tool_calls else "tool_calls",
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
        "cost_usd": 0.02,
    }
    if tool_calls:
        resp["tool_calls"] = tool_calls
    return resp


def _make_diagnosis_content() -> str:
    """A plausible teacher diagnosis output with embedded cluster JSON."""
    return (
        "## Diagnosis\n\n"
        "The student has two main failure patterns:\n\n"
        "### Cluster 1: Math Routing\n"
        "Math queries are being routed to qwen-3b which lacks chain-of-thought.\n\n"
        "### Cluster 2: Tool Selection\n"
        "The student frequently fails to use the calculator tool for arithmetic.\n\n"
        "```json\n"
        + json.dumps(
            [
                {
                    "id": "cluster-001",
                    "description": "Math queries routed to qwen-3b",
                    "sample_trace_ids": ["t1", "t2", "t3"],
                    "student_failure_rate": 0.8,
                    "teacher_success_rate": 0.95,
                    "skill_gap": "Student lacks chain-of-thought on multi-step math",
                },
                {
                    "id": "cluster-002",
                    "description": "Calculator tool not used for arithmetic",
                    "sample_trace_ids": ["t4", "t5", "t6"],
                    "student_failure_rate": 0.6,
                    "teacher_success_rate": 0.9,
                    "skill_gap": "Student does not invoke calculator tool",
                },
            ]
        )
        + "\n```\n"
    )


class TestDiagnosisRunner:
    """Tests for DiagnosisRunner."""

    def test_produces_diagnosis_artifact(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.runner import (
            DiagnosisRunner,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content=_make_diagnosis_content()
        )

        runner = DiagnosisRunner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_dir=tmp_path / "session-001",
            session_id="session-001",
            config={
                "config_path": tmp_path / "config.toml",
                "openjarvis_home": tmp_path,
            },
        )
        # Create minimal config file
        (tmp_path / "config.toml").write_text("[learning]\n")

        runner.run()

        # Diagnosis artifact written
        diagnosis_path = tmp_path / "session-001" / "diagnosis.md"
        assert diagnosis_path.exists()
        assert "Math" in diagnosis_path.read_text()

    def test_returns_failure_clusters(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.runner import (
            DiagnosisRunner,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content=_make_diagnosis_content()
        )

        runner = DiagnosisRunner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_dir=tmp_path / "session-001",
            session_id="session-001",
            config={
                "config_path": tmp_path / "config.toml",
                "openjarvis_home": tmp_path,
            },
        )
        (tmp_path / "config.toml").write_text("[learning]\n")

        result = runner.run()

        assert len(result.clusters) == 2
        assert result.clusters[0].id == "cluster-001"
        assert result.clusters[0].student_failure_rate == 0.8
        assert result.clusters[1].id == "cluster-002"

    def test_persists_teacher_traces_jsonl(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.runner import (
            DiagnosisRunner,
        )

        engine = MagicMock()
        # Turn 1: tool call
        engine.generate.side_effect = [
            _make_engine_response(
                content="",
                tool_calls=[
                    {
                        "id": "c1",
                        "name": "get_current_config",
                        "arguments": "{}",
                    }
                ],
            ),
            _make_engine_response(content=_make_diagnosis_content()),
        ]

        runner = DiagnosisRunner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_dir=tmp_path / "session-001",
            session_id="session-001",
            config={
                "config_path": tmp_path / "config.toml",
                "openjarvis_home": tmp_path,
            },
        )
        (tmp_path / "config.toml").write_text("[learning]\n")

        runner.run()

        jsonl_path = tmp_path / "session-001" / "teacher_traces" / "diagnose.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text().strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert "tool" in record

    def test_returns_cost(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.runner import (
            DiagnosisRunner,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content=_make_diagnosis_content()
        )

        runner = DiagnosisRunner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_dir=tmp_path / "session-001",
            session_id="session-001",
            config={
                "config_path": tmp_path / "config.toml",
                "openjarvis_home": tmp_path,
            },
        )
        (tmp_path / "config.toml").write_text("[learning]\n")

        result = runner.run()
        assert result.cost_usd >= 0.0

    def test_handles_no_clusters_in_output(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.runner import (
            DiagnosisRunner,
        )

        engine = MagicMock()
        engine.generate.return_value = _make_engine_response(
            content="## Diagnosis\nNo clear failure patterns found."
        )

        runner = DiagnosisRunner(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_dir=tmp_path / "session-001",
            session_id="session-001",
            config={
                "config_path": tmp_path / "config.toml",
                "openjarvis_home": tmp_path,
            },
        )
        (tmp_path / "config.toml").write_text("[learning]\n")

        result = runner.run()

        assert result.clusters == []
        # Diagnosis artifact is still written
        assert (tmp_path / "session-001" / "diagnosis.md").exists()
