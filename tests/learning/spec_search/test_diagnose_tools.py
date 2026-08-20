"""Tests for openjarvis.learning.spec_search.diagnose.tools module.

All tests use fixture stubs — no live TraceStore, CloudEngine, or ToolRegistry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stubs for dependencies
# ---------------------------------------------------------------------------


@dataclass
class _StubTrace:
    """Minimal stub matching the Trace fields that tools access."""

    trace_id: str = "trace-001"
    query: str = "What is 2+2?"
    agent: str = "simple"
    model: str = "qwen2.5-coder:7b"
    outcome: Optional[str] = "success"
    feedback: Optional[float] = 0.8
    started_at: float = 1712534400.0
    result: str = "4"
    steps: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    total_tokens: int = 100
    total_latency_seconds: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    ended_at: float = 1712534401.0
    engine: str = "ollama"


def _make_stub_trace_store(traces: list[_StubTrace] | None = None) -> MagicMock:
    """Create a mock TraceStore with canned responses."""
    store = MagicMock()
    traces = traces or [_StubTrace()]
    store.list_traces.return_value = traces
    store.get.side_effect = lambda tid: next(
        (t for t in traces if t.trace_id == tid), None
    )
    store.search.return_value = [
        {"trace_id": t.trace_id, "query": t.query, "score": 1.0} for t in traces
    ]
    return store


def _make_stub_benchmark_samples() -> list:
    """Return a list of stub PersonalBenchmarkSample objects."""
    sample = MagicMock()
    sample.trace_id = "task-001"
    sample.query = "What is quantum computing?"
    sample.reference_answer = "Quantum computing uses qubits..."
    sample.category = "reasoning"
    sample.feedback_score = 0.9
    return [sample]


def _make_stub_config(tmp_path: Path) -> dict:
    """Create a minimal config dict and on-disk files."""
    agents_dir = tmp_path / "agents" / "simple"
    agents_dir.mkdir(parents=True)
    (agents_dir / "system_prompt.md").write_text("You are a helpful assistant.\n")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "descriptions.toml").write_text(
        '[web_search]\ndescription = "Search the web"\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text("[learning]\nenabled = true\n")
    return {
        "config_path": config_path,
        "openjarvis_home": tmp_path,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildDiagnosticTools:
    """Tests for the build_diagnostic_tools factory."""

    def test_returns_expected_tool_names(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=_make_stub_benchmark_samples(),
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        names = {t.name for t in tools}
        assert "list_traces" in names
        assert "get_trace" in names
        assert "search_traces" in names
        assert "get_current_config" in names
        assert "get_agent_prompt" in names
        assert "get_tool_description" in names
        assert "list_available_tools" in names
        assert "list_personal_benchmark" in names
        assert "run_student_on_task" in names
        assert "run_self_on_task" in names
        assert "compare_outputs" in names

    def test_all_tools_have_openai_format(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=_make_stub_benchmark_samples(),
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        for tool in tools:
            spec = tool.to_openai_function()
            assert spec["type"] == "function"
            assert "name" in spec["function"]
            assert "parameters" in spec["function"]


class TestListTraces:
    """Tests for the list_traces diagnostic tool."""

    def test_returns_trace_metas(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        traces = [
            _StubTrace(trace_id="t1", feedback=0.3),
            _StubTrace(trace_id="t2", feedback=0.9),
        ]
        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(traces),
            config=_make_stub_config(tmp_path),
            benchmark_samples=[],
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        list_traces = next(t for t in tools if t.name == "list_traces")
        result = list_traces.fn(limit=10)
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["trace_id"] == "t1"


class TestGetTrace:
    """Tests for the get_trace diagnostic tool."""

    def test_returns_trace_details(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=[],
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        get_trace = next(t for t in tools if t.name == "get_trace")
        result = get_trace.fn(trace_id="trace-001")
        parsed = json.loads(result)
        assert parsed["trace_id"] == "trace-001"
        assert parsed["query"] == "What is 2+2?"

    def test_returns_error_for_unknown_trace(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=[],
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        get_trace = next(t for t in tools if t.name == "get_trace")
        result = get_trace.fn(trace_id="nonexistent")
        assert "not found" in result.lower()


class TestGetCurrentConfig:
    """Tests for the get_current_config diagnostic tool."""

    def test_returns_config_content(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=[],
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        get_config = next(t for t in tools if t.name == "get_current_config")
        result = get_config.fn()
        assert "learning" in result


class TestGetAgentPrompt:
    """Tests for the get_agent_prompt diagnostic tool."""

    def test_returns_prompt_content(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=[],
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        get_prompt = next(t for t in tools if t.name == "get_agent_prompt")
        result = get_prompt.fn(agent_name="simple")
        assert "helpful assistant" in result


class TestListPersonalBenchmark:
    """Tests for the list_personal_benchmark diagnostic tool."""

    def test_returns_benchmark_tasks(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.diagnose.tools import (
            build_diagnostic_tools,
        )

        tools = build_diagnostic_tools(
            trace_store=_make_stub_trace_store(),
            config=_make_stub_config(tmp_path),
            benchmark_samples=_make_stub_benchmark_samples(),
            student_runner=MagicMock(),
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            judge=MagicMock(),
            session_id="session-001",
        )
        list_bench = next(t for t in tools if t.name == "list_personal_benchmark")
        result = list_bench.fn(limit=10)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["task_id"] == "task-001"
