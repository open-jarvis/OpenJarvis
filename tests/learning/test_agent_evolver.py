"""Tests for AgentConfigEvolver — trace-driven agent config evolution."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.learning.agents.agent_evolver import AgentConfigEvolver
from openjarvis.traces.store import TraceStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    *,
    query: str = "hello",
    agent: str = "orchestrator",
    model: str = "qwen3:8b",
    tools: list[str] | None = None,
    outcome: str = "success",
    feedback: float = 0.9,
) -> Trace:
    """Build a Trace with TOOL_CALL steps for the given tool names."""
    steps: list[TraceStep] = []
    for tool_name in tools or []:
        steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=time.time(),
                duration_seconds=0.1,
                input={"tool": tool_name, "args": {}},
                output={"result": "ok"},
            )
        )
    # Add a GENERATE step so it looks realistic
    steps.append(
        TraceStep(
            step_type=StepType.GENERATE,
            timestamp=time.time(),
            duration_seconds=0.5,
            input={"prompt": query},
            output={"content": "answer", "tokens": 50},
        )
    )
    return Trace(
        query=query,
        agent=agent,
        model=model,
        steps=steps,
        result="answer",
        outcome=outcome,
        feedback=feedback,
        started_at=time.time(),
        ended_at=time.time() + 1.0,
        total_tokens=50,
        total_latency_seconds=0.6,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentConfigEvolver:
    def test_analyze_empty_store(self, tmp_path: Path) -> None:
        """Empty trace store returns empty recommendations."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        evolver = AgentConfigEvolver(store, config_dir=config_dir)
        recs = evolver.analyze()

        assert recs == []
        store.close()

    def test_evolve_recommends_tool_changes(self, tmp_path: Path) -> None:
        """Traces with different tools — best tools recommended for each query class."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        # Create traces where "calculator" and "think" are used in successful
        # math queries (short queries containing "calculate")
        for i in range(5):
            t = _make_trace(
                query=f"calculate {i + 1} + {i + 2}",
                agent="orchestrator",
                tools=["calculator", "think"],
                outcome="success",
                feedback=0.95,
            )
            store.save(t)

        # Create traces where "web_search" is used in general queries
        for i in range(5):
            t = _make_trace(
                query=f"Tell me a moderately long story about topic number {i} please",
                agent="orchestrator",
                tools=["web_search"],
                outcome="success",
                feedback=0.8,
            )
            store.save(t)

        # Create traces where "calculator" alone is used in math queries
        # but with lower feedback — so the combo (calculator+think) should win
        for i in range(3):
            t = _make_trace(
                query=f"compute the integral of x^{i}",
                agent="simple",
                tools=["calculator"],
                outcome="success",
                feedback=0.6,
            )
            store.save(t)

        evolver = AgentConfigEvolver(store, config_dir=config_dir)
        recs = evolver.analyze()

        assert len(recs) > 0

        # Each recommendation should have the expected keys
        for rec in recs:
            assert "query_class" in rec
            assert "recommended_tools" in rec
            assert "recommended_agent" in rec
            assert "recommended_max_turns" in rec
            assert "sample_count" in rec
            assert rec["sample_count"] > 0

        # Find the math recommendation — "calculator" should be in recommended tools
        math_recs = [r for r in recs if r["query_class"] == "math"]
        if math_recs:
            assert "calculator" in math_recs[0]["recommended_tools"]

        store.close()

    def test_write_config_creates_toml(self, tmp_path: Path) -> None:
        """write_config creates a valid TOML file with correct content."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        evolver = AgentConfigEvolver(store, config_dir=config_dir)
        path = evolver.write_config(
            "research_agent",
            tools=["web_search", "file_read", "think"],
            max_turns=15,
            temperature=0.4,
            system_prompt="You are a research assistant.",
        )

        # File should exist
        assert path.exists()
        assert path.suffix == ".toml"
        assert "research_agent" in path.name

        # Parse and verify content
        with open(path, "rb") as f:
            data = tomllib.load(f)

        assert "agent" in data
        agent_cfg = data["agent"]
        assert agent_cfg["name"] == "research_agent"
        assert agent_cfg["tools"] == ["web_search", "file_read", "think"]
        assert agent_cfg["max_turns"] == 15
        assert agent_cfg["temperature"] == 0.4
        assert agent_cfg["system_prompt"] == "You are a research assistant."

        store.close()

    def test_versioning_and_rollback(self, tmp_path: Path) -> None:
        """Write v1, write v2, list versions, rollback to v1."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        evolver = AgentConfigEvolver(store, config_dir=config_dir)

        # Write v1
        evolver.write_config(
            "my_agent",
            tools=["calculator"],
            max_turns=5,
            temperature=0.2,
            system_prompt="v1 prompt",
        )

        # Write v2 (overwrites v1, archives v1 to .history/)
        evolver.write_config(
            "my_agent",
            tools=["calculator", "web_search"],
            max_turns=10,
            temperature=0.5,
            system_prompt="v2 prompt",
        )

        # Current config should be v2
        config_path = config_dir / "my_agent.toml"
        with open(config_path, "rb") as f:
            current = tomllib.load(f)
        assert current["agent"]["tools"] == ["calculator", "web_search"]
        assert current["agent"]["system_prompt"] == "v2 prompt"

        # List versions — should have at least 2 entries
        versions = evolver.list_versions("my_agent")
        assert len(versions) >= 2
        for v in versions:
            assert "version" in v
            assert "path" in v
            assert "modified" in v
            assert isinstance(v["version"], int)
            assert os.path.exists(v["path"])

        # Rollback to v1 (version 1)
        evolver.rollback("my_agent", version=1)

        with open(config_path, "rb") as f:
            rolled_back = tomllib.load(f)
        assert rolled_back["agent"]["tools"] == ["calculator"]
        assert rolled_back["agent"]["system_prompt"] == "v1 prompt"

        # Verify ValueError on non-existent version
        with pytest.raises(ValueError, match="[Vv]ersion"):
            evolver.rollback("my_agent", version=999)

        store.close()
