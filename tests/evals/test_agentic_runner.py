"""Tests for AgenticRunner with mock agent and dataset."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from openjarvis.evals.core.agentic_runner import AgenticRunner, _extract_patch
from openjarvis.evals.core.environment import TaskEnvironmentError

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


class MockZeroContactAgent:
    """Agent that returns without ever contacting the model.

    Mirrors the downstream failure signature: a hung/dead in-container
    setup yields zero LM events and zero token usage, while run_tests
    still stamps is_resolved=False.
    """

    def ask(self, query: str) -> dict:
        return {"content": "setup log tail ...", "usage": {}}


class FailingTaskEnv:
    """Task env whose __enter__ fails like a tmux/compose breakage."""

    def __init__(self, metadata: Dict[str, Any]) -> None:
        self._metadata = metadata

    def __enter__(self) -> "FailingTaskEnv":
        message = (
            "Task 't1': required binary 'tmux' is not usable in task image "
            "'tb__t1__client'"
        )
        self._metadata["harness_error"] = message
        raise TaskEnvironmentError(message)

    def __exit__(self, *args: Any) -> None:
        return None


class ResolvingTaskEnv:
    """Task env that stamps is_resolved into metadata like run_tests does."""

    def __init__(self, metadata: Dict[str, Any], is_resolved: bool) -> None:
        self._metadata = metadata
        self._is_resolved = is_resolved

    def __enter__(self) -> "ResolvingTaskEnv":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def run_tests(self):
        self._metadata["is_resolved"] = self._is_resolved
        return self._is_resolved, {}


class EnvDataset(MockDataset):
    """Dataset whose create_task_env is configurable per record id."""

    def __init__(self, records: List[MockRecord], env_factories: Dict[str, Any]):
        super().__init__(records)
        self._env_factories = env_factories

    def create_task_env(self, record: MockRecord):
        factory = self._env_factories.get(record.record_id)
        return factory(record.metadata) if factory is not None else None


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
        assert traces[0].error_kind == "agent_error"
        assert "Agent error" in (traces[0].error or "")

    def test_harness_failure_recorded_and_run_continues(self):
        """(c) one task's env breakage doesn't kill the run."""
        records = [
            MockRecord(record_id="r1", problem="broken env"),
            MockRecord(record_id="r2", problem="healthy"),
        ]
        dataset = EnvDataset(records, {"r1": FailingTaskEnv})
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset)

        traces = self._run_async(runner.run())
        assert len(traces) == 2
        # Failed task: recorded distinctly as a harness error, not a miss.
        assert traces[0].error_kind == "harness_error"
        assert not traces[0].completed
        assert "tmux" in (traces[0].error or "")
        assert traces[0].is_resolved is None
        # Healthy task still ran to completion.
        assert traces[1].completed
        assert traces[1].error_kind is None
        assert "Response to: healthy" in traces[1].response_text

    def test_zero_model_contact_flagged_as_harness_error(self):
        """(e) zero model requests -> harness_error, not a model miss."""
        records = [MockRecord(record_id="r1", problem="task")]
        dataset = EnvDataset(
            records,
            {"r1": lambda meta: ResolvingTaskEnv(meta, is_resolved=False)},
        )
        runner = AgenticRunner(agent=MockZeroContactAgent(), dataset=dataset)

        traces = self._run_async(runner.run())
        assert traces[0].error_kind == "harness_error"
        assert "zero_model_requests" in (traces[0].error or "")
        assert traces[0].total_input_tokens == 0
        assert traces[0].total_output_tokens == 0

    def test_genuine_model_miss_not_flagged(self):
        """(e) control: tokens>0 + is_resolved=False is a model miss."""
        records = [MockRecord(record_id="r1", problem="task")]
        dataset = EnvDataset(
            records,
            {"r1": lambda meta: ResolvingTaskEnv(meta, is_resolved=False)},
        )
        runner = AgenticRunner(agent=MockAgent(), dataset=dataset)

        traces = self._run_async(runner.run())
        assert traces[0].is_resolved is False
        assert traces[0].error_kind is None
        assert traces[0].error is None
        assert traces[0].total_input_tokens > 0

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
