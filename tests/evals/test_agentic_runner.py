"""Tests for AgenticRunner with mock agent and dataset."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from openjarvis.evals.core.agentic_runner import AgenticRunner, _extract_patch

# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class MockRecord:
    record_id: str
    problem: str
    expected: str = ""
    category: str = "test"
    metadata: Dict[str, Any] = field(default_factory=dict)


class MockDataset:
    def __init__(self, records: List[MockRecord]):
        self._records = records

    def iter_records(self):
        return iter(self._records)


class MockAgent:
    """Agent that echoes the query."""

    def ask(self, query: str) -> dict:
        return {
            "content": f"Response to: {query}",
            "usage": {"prompt_tokens": 50, "completion_tokens": 25},
            "cost_usd": 0.001,
        }


class MockFailingAgent:
    """Agent that always raises."""

    def ask(self, query: str) -> dict:
        raise RuntimeError("Agent error")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgenticRunner:
    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    @pytest.fixture(autouse=True)
    def _setup_loop(self):
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

    def test_basic_run(self):
        records = [
            MockRecord(record_id="r1", problem="What is 2+2?"),
            MockRecord(record_id="r2", problem="What is 3+3?"),
        ]
        dataset = MockDataset(records)
        agent = MockAgent()
        runner = AgenticRunner(agent=agent, dataset=dataset)

        traces = self._run_async(runner.run())
        assert len(traces) == 2
        assert all(t.completed for t in traces)
        assert traces[0].query_id == "q0000"
        assert traces[1].query_id == "q0001"
        assert "Response to: What is 2+2?" in traces[0].response_text

    def test_max_queries(self):
        records = [MockRecord(record_id=f"r{i}", problem=f"Q{i}") for i in range(10)]
        dataset = MockDataset(records)
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset)

        traces = self._run_async(runner.run(max_queries=3))
        assert len(traces) == 3

    def test_agent_failure(self):
        records = [MockRecord(record_id="r1", problem="test")]
        dataset = MockDataset(records)
        runner = AgenticRunner(agent=MockFailingAgent(), dataset=dataset)

        traces = self._run_async(runner.run())
        assert len(traces) == 1
        assert not traces[0].completed
        assert "Agent error" in traces[0].response_text

    def test_synthetic_turn_created(self):
        records = [MockRecord(record_id="r1", problem="test")]
        dataset = MockDataset(records)
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset)

        traces = self._run_async(runner.run())
        assert traces[0].num_turns == 1
        assert traces[0].turns[0].input_tokens == 50
        assert traces[0].turns[0].output_tokens == 25

    def test_traces_property(self):
        records = [MockRecord(record_id="r1", problem="test")]
        dataset = MockDataset(records)
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset)

        self._run_async(runner.run())
        assert len(runner.traces) == 1

    def test_artifacts_saved(self, tmp_path):
        records = [MockRecord(record_id="r1", problem="test")]
        dataset = MockDataset(records)
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset, run_dir=tmp_path)

        self._run_async(runner.run())
        arts = tmp_path / "artifacts"
        assert arts.exists()
        subdirs = list(arts.iterdir())
        assert len(subdirs) == 1
        assert (subdirs[0] / "response.txt").exists()
        assert (subdirs[0] / "metadata.json").exists()

    def test_query_timeout_configured(self):
        """Verify timeout is stored and runner accepts the parameter."""
        records = [MockRecord(record_id="r1", problem="test")]
        dataset = MockDataset(records)
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset, query_timeout=30.0)
        assert runner._query_timeout == 30.0


class TestExtractPatch:
    def test_fenced_diff(self):
        text = (
            "Here's the fix:\n```diff\n"
            "--- a/foo.py\n+++ b/foo.py\n"
            "@@ -1 +1 @@\n-old\n+new\n```\n"
        )
        patch = _extract_patch(text)
        assert patch is not None
        assert "--- a/foo.py" in patch

    def test_unfenced_diff(self):
        text = (
            "Some explanation\n"
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n+++ b/x.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        patch = _extract_patch(text)
        assert patch is not None
        assert "diff --git" in patch

    def test_no_patch(self):
        text = "This is just a regular response with no code changes."
        patch = _extract_patch(text)
        assert patch is None
