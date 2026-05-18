"""Live integration tests for the spec-search subsystem.

These tests use REAL API calls (CloudEngine with Anthropic) and real
TraceStore data. They are gated on the ``cloud`` marker — skip them
with ``pytest -m "not cloud"``.

Requires:
- ANTHROPIC_API_KEY environment variable set
- TraceStore at ~/.openjarvis/traces.db with some traces
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Skip entire module if no API key
pytestmark = pytest.mark.cloud


@pytest.fixture
def anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return key


@pytest.fixture
def cloud_engine(anthropic_key):
    from openjarvis.engine.cloud import CloudEngine

    return CloudEngine()


@pytest.fixture
def real_trace_store():
    from openjarvis.traces.store import TraceStore

    db_path = Path.home() / ".openjarvis" / "traces.db"
    if not db_path.exists():
        pytest.skip("No traces.db found at ~/.openjarvis/")
    store = TraceStore(db_path)
    if store.count() < 5:
        pytest.skip("Need at least 5 traces for live test")
    return store


class TestCloudEngineDirectCall:
    """Verify CloudEngine works with real API."""

    def test_generate_produces_content(self, cloud_engine) -> None:
        from openjarvis.core.types import Message, Role

        result = cloud_engine.generate(
            messages=[
                Message(
                    role=Role.USER,
                    content="What is 2+2? Answer with just the number.",
                )
            ],
            model="claude-sonnet-4-6",
            max_tokens=10,
        )
        assert "content" in result
        assert "4" in result["content"]
        assert result.get("cost_usd", 0) > 0


class TestTeacherAgentLive:
    """Test TeacherAgent with a real CloudEngine."""

    def test_teacher_agent_single_turn(self, cloud_engine) -> None:
        from openjarvis.learning.spec_search.diagnose.teacher_agent import (
            TeacherAgent,
        )

        agent = TeacherAgent(
            engine=cloud_engine,
            model="claude-sonnet-4-6",
            tools=[],
            max_turns=2,
            max_cost_usd=0.50,
        )
        result = agent.run(
            "You are being tested. Simply respond with: 'TeacherAgent works.'",
            system_prompt="You are a test assistant. Follow instructions exactly.",
        )
        assert result.content
        assert result.turns >= 1
        assert result.total_cost_usd > 0
        print(f"  Teacher response: {result.content[:100]}")
        print(f"  Cost: ${result.total_cost_usd:.4f}, Turns: {result.turns}")


class TestDiagnosisRunnerLive:
    """Test DiagnosisRunner with real CloudEngine + real traces."""

    def test_diagnosis_produces_output(
        self, cloud_engine, real_trace_store, tmp_path
    ) -> None:
        from openjarvis.learning.spec_search.diagnose.runner import (
            DiagnosisRunner,
        )

        # Create minimal config
        config_dir = tmp_path / "oj_home"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text("[learning]\nenabled = true\n")

        session_dir = tmp_path / "session"
        runner = DiagnosisRunner(
            teacher_engine=cloud_engine,
            teacher_model="claude-sonnet-4-6",
            trace_store=real_trace_store,
            benchmark_samples=[],
            student_runner=lambda q, **kw: type(
                "R", (), {"content": "mock", "score": 0.5}
            )(),
            judge=type("J", (), {"score_trace": lambda self, t: (0.5, "mock")})(),
            session_dir=session_dir,
            session_id="live-test-001",
            config={
                "config_path": config_dir / "config.toml",
                "openjarvis_home": config_dir,
            },
            max_turns=5,  # Keep it cheap
            max_cost_usd=1.0,
        )

        result = runner.run()

        # Diagnosis should produce output
        assert result.diagnosis_md, "Diagnosis produced no markdown"
        assert len(result.diagnosis_md) > 50, "Diagnosis too short"
        print(f"  Diagnosis length: {len(result.diagnosis_md)} chars")
        print(f"  Clusters found: {len(result.clusters)}")
        print(f"  Cost: ${result.cost_usd:.4f}")
        print(f"  Tool calls: {len(result.tool_call_records)}")

        # Artifacts should exist
        assert (session_dir / "diagnosis.md").exists()
        assert (session_dir / "teacher_traces" / "diagnose.jsonl").exists()

        # Print first 200 chars of diagnosis
        print(f"  Diagnosis preview: {result.diagnosis_md[:200]}...")


class TestColdStartLive:
    """Test cold start behavior with real trace store."""

    def test_orchestrator_cold_start_with_no_feedback(
        self, cloud_engine, real_trace_store, tmp_path
    ) -> None:
        """With 373 traces but 0 feedback, the orchestrator should handle
        this gracefully — either by running (traces > 20) or by giving
        a clear message about what's missing."""
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_benchmark_ready,
            check_readiness,
        )

        # Check trace readiness
        trace_ready = check_readiness(real_trace_store, min_traces=20)
        print(f"  Trace readiness: {trace_ready.ready} ({trace_ready.message})")

        # Check benchmark readiness
        bench_ready = check_benchmark_ready(
            real_trace_store, min_feedback=0.7, min_samples=10
        )
        print(f"  Benchmark readiness: {bench_ready.ready} ({bench_ready.message})")

        # With 373 traces but 0 feedback: traces ready, benchmark not ready
        assert trace_ready.ready, "Should have enough traces"
        assert not bench_ready.ready, "Should not have enough high-feedback traces"
