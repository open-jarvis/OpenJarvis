"""End-to-end integration tests for Phase 3 and Phase 4 components."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry, RouterPolicyRegistry, ToolRegistry
from openjarvis.core.types import (
    Conversation,
    Message,
    Role,
    TelemetryRecord,
    ToolCall,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_agents():
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.agents.simple import SimpleAgent

    if not AgentRegistry.contains("simple"):
        AgentRegistry.register_value("simple", SimpleAgent)
    if not AgentRegistry.contains("orchestrator"):
        AgentRegistry.register_value("orchestrator", OrchestratorAgent)


def _register_tools():
    from openjarvis.tools.calculator import CalculatorTool
    from openjarvis.tools.think import ThinkTool

    if not ToolRegistry.contains("calculator"):
        ToolRegistry.register_value("calculator", CalculatorTool)
    if not ToolRegistry.contains("think"):
        ToolRegistry.register_value("think", ThinkTool)


def _make_engine(content="Hello from engine"):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestSimpleAgentPipeline:
    """End-to-end: SimpleAgent with mocked engine."""

    def test_full_flow(self):
        _register_agents()
        engine = _make_engine("The answer is 42.")
        bus = EventBus(record_history=True)
        agent_cls = AgentRegistry.get("simple")
        agent = agent_cls(engine, "test-model", bus=bus)
        result = agent.run("What is the answer?")

        assert isinstance(result, AgentResult)
        assert result.content == "The answer is 42."
        assert result.turns == 1

        # Verify event chain — INFERENCE_START/END and TELEMETRY_RECORD
        # are now published by InstrumentedEngine, not by agents directly
        event_types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in event_types
        assert EventType.AGENT_TURN_END in event_types

    def test_with_context(self):
        _register_agents()
        engine = _make_engine("Contextualized response.")
        agent_cls = AgentRegistry.get("simple")
        agent = agent_cls(engine, "test-model")
        conv = Conversation()
        conv.add(Message(role=Role.SYSTEM, content="You are a helpful assistant."))
        ctx = AgentContext(conversation=conv)
        result = agent.run("Hello", context=ctx)
        assert result.content == "Contextualized response."


class TestOrchestratorWithCalculator:
    """End-to-end: OrchestratorAgent with calculator tool."""

    def test_calculator_tool_call(self):
        _register_agents()
        _register_tools()

        from openjarvis.tools.calculator import CalculatorTool

        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "calculator",
                        "arguments": '{"expression":"2+2"}',
                    },
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
                "model": "test-model",
                "finish_reason": "tool_calls",
            },
            {
                "content": "2+2 equals 4.",
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 5,
                    "total_tokens": 20,
                },
                "model": "test-model",
                "finish_reason": "stop",
            },
        ]

        bus = EventBus(record_history=True)
        agent_cls = AgentRegistry.get("orchestrator")
        agent = agent_cls(
            engine,
            "test-model",
            tools=[CalculatorTool()],
            bus=bus,
        )
        result = agent.run("What is 2+2?")

        assert result.content == "2+2 equals 4."
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].content == "4.0"
        assert result.tool_results[0].success is True

        # Verify tool call events
        event_types = [e.event_type for e in bus.history]
        assert EventType.TOOL_CALL_START in event_types
        assert EventType.TOOL_CALL_END in event_types


class TestAPIServerRoundtrip:
    """End-to-end: API server request/response cycle."""

    def test_roundtrip(self):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from openjarvis.server.app import create_app

        engine = _make_engine("API response!")
        app = create_app(engine, "test-model")
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "user", "content": "Hello"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        msg = data["choices"][0]["message"]["content"]
        assert msg == "API response!"
        assert data["object"] == "chat.completion"

    def test_models_endpoint(self):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from openjarvis.server.app import create_app

        engine = _make_engine()
        app = create_app(engine, "test-model")
        client = TestClient(app)

        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1


class TestEventBusFullFlow:
    """Verify the complete event chain through an agent run."""

    def test_all_events_recorded(self):
        """Agent-level events are recorded; INFERENCE_START/END and
        TELEMETRY_RECORD are now published by InstrumentedEngine."""
        _register_agents()
        bus = EventBus(record_history=True)
        engine = _make_engine()
        agent = AgentRegistry.get("simple")(engine, "test-model", bus=bus)
        agent.run("Hello")

        event_types = [e.event_type for e in bus.history]
        expected = [
            EventType.AGENT_TURN_START,
            EventType.AGENT_TURN_END,
        ]
        for et in expected:
            assert et in event_types, f"Missing event: {et}"

    def test_subscriber_receives_events(self):
        _register_agents()
        bus = EventBus(record_history=True)
        received = []
        bus.subscribe(EventType.AGENT_TURN_END, lambda e: received.append(e))

        engine = _make_engine()
        agent = AgentRegistry.get("simple")(engine, "test-model", bus=bus)
        agent.run("Hello")

        assert len(received) == 1
        assert received[0].data["agent"] == "simple"


class TestTelemetryThroughAgent:
    """Verify telemetry records are created through InstrumentedEngine."""

    def test_telemetry_record_created(self):
        """Telemetry records are now produced by InstrumentedEngine,
        not by agents directly."""
        from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

        _register_agents()
        bus = EventBus(record_history=True)
        raw_engine = _make_engine()
        engine = InstrumentedEngine(raw_engine, bus)
        agent = AgentRegistry.get("simple")(engine, "test-model", bus=bus)
        agent.run("Hello")

        telem_events = [
            e for e in bus.history if e.event_type == EventType.TELEMETRY_RECORD
        ]
        assert len(telem_events) == 1
        rec = telem_events[0].data["record"]
        assert rec.model_id == "test-model"
        assert rec.engine == "mock"


class TestToolExecutorIntegration:
    """Integration test for tool executor with real tools."""

    def test_calculator_and_think(self):
        _register_tools()
        from openjarvis.tools._stubs import ToolExecutor
        from openjarvis.tools.calculator import CalculatorTool
        from openjarvis.tools.think import ThinkTool

        bus = EventBus(record_history=True)
        executor = ToolExecutor([CalculatorTool(), ThinkTool()], bus=bus)

        # Calculator
        calc_result = executor.execute(
            ToolCall(id="1", name="calculator", arguments='{"expression":"3*7"}'),
        )
        assert calc_result.success is True
        assert calc_result.content == "21.0"

        # Think
        think_result = executor.execute(
            ToolCall(id="2", name="think", arguments='{"thought":"Step 1: solve"}'),
        )
        assert think_result.success is True
        assert think_result.content == "Step 1: solve"

        # Verify events
        starts = [e for e in bus.history if e.event_type == EventType.TOOL_CALL_START]
        ends = [e for e in bus.history if e.event_type == EventType.TOOL_CALL_END]
        assert len(starts) == 2
        assert len(ends) == 2


# ---------------------------------------------------------------------------
# Phase 4 integration tests
# ---------------------------------------------------------------------------


class TestHeuristicRewardWithTelemetry:
    """HeuristicRewardFunction scores using TelemetryRecord data."""

    def test_reward_from_telemetry_record(self):
        from openjarvis.learning._stubs import RoutingContext
        from openjarvis.learning.routing.heuristic_reward import HeuristicRewardFunction

        rec = TelemetryRecord(
            timestamp=0.0,
            model_id="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_seconds=2.0,
            cost_usd=0.002,
        )
        rf = HeuristicRewardFunction()
        score = rf.compute(
            RoutingContext(query="test"),
            rec.model_id,
            "response",
            latency_seconds=rec.latency_seconds,
            cost_usd=rec.cost_usd,
            prompt_tokens=rec.prompt_tokens,
            completion_tokens=rec.completion_tokens,
        )
        assert 0.0 <= score <= 1.0


class TestRouterPolicyRegistryDiscovery:
    """RouterPolicyRegistry discovers both heuristic and learned."""

    def test_both_policies_registered(self):
        from openjarvis.learning import ensure_registered

        ensure_registered()
        assert RouterPolicyRegistry.contains("heuristic")
        assert RouterPolicyRegistry.contains("learned")


class TestTelemetryPipeline:
    """TelemetryStore → TelemetryAggregator pipeline."""

    def test_store_then_aggregate(self, tmp_path):
        import time

        from openjarvis.telemetry.aggregator import TelemetryAggregator
        from openjarvis.telemetry.store import TelemetryStore

        db = tmp_path / "telemetry.db"
        store = TelemetryStore(db)
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="m1",
                engine="ollama",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                latency_seconds=1.0,
                cost_usd=0.001,
            )
        )
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="m2",
                engine="vllm",
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                latency_seconds=0.5,
                cost_usd=0.002,
            )
        )
        store.close()

        agg = TelemetryAggregator(db)
        summary = agg.summary()
        assert summary.total_calls == 2
        assert summary.total_tokens == 45
        assert len(summary.per_model) == 2
        assert len(summary.per_engine) == 2
        agg.close()


class TestEventBusTelemetryAggregator:
    """EventBus → TelemetryStore → TelemetryAggregator end-to-end."""

    def test_event_driven_pipeline(self, tmp_path):
        from openjarvis.telemetry.aggregator import TelemetryAggregator
        from openjarvis.telemetry.store import TelemetryStore

        db = tmp_path / "telemetry.db"
        store = TelemetryStore(db)
        bus = EventBus(record_history=True)
        store.subscribe_to_bus(bus)

        # Publish a telemetry event
        rec = TelemetryRecord(
            timestamp=1000.0,
            model_id="event-model",
            engine="test",
            prompt_tokens=5,
            completion_tokens=3,
            total_tokens=8,
            latency_seconds=0.1,
        )
        bus.publish(EventType.TELEMETRY_RECORD, {"record": rec})
        store.close()

        agg = TelemetryAggregator(db)
        assert agg.record_count() == 1
        stats = agg.per_model_stats()
        assert stats[0].model_id == "event-model"
        agg.close()


class TestAskFlowWithRouterPolicy:
    """Full ask flow with router policy (mocked)."""

    def test_mocked_ask_with_registry_router(self):
        from openjarvis.learning._stubs import RoutingContext
        from openjarvis.learning.routing.heuristic_policy import ensure_registered
        from openjarvis.learning.routing.router import HeuristicRouter

        ensure_registered()
        router_cls = RouterPolicyRegistry.get("heuristic")
        assert router_cls is HeuristicRouter

        router = router_cls(
            available_models=["small-model", "large-model"],
            default_model="small-model",
        )
        ctx = RoutingContext(query="Hello", query_length=5)
        model = router.select_model(ctx)
        assert model in ("small-model", "large-model")


class TestRewardTelemetryIntegration:
    """Reward function + telemetry integration."""

    def test_score_from_aggregated_stats(self, tmp_path):
        import time

        from openjarvis.learning._stubs import RoutingContext
        from openjarvis.learning.routing.heuristic_reward import HeuristicRewardFunction
        from openjarvis.telemetry.aggregator import TelemetryAggregator
        from openjarvis.telemetry.store import TelemetryStore

        db = tmp_path / "telemetry.db"
        store = TelemetryStore(db)
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="scored-model",
                engine="test",
                prompt_tokens=50,
                completion_tokens=25,
                total_tokens=75,
                latency_seconds=3.0,
                cost_usd=0.003,
            )
        )
        store.close()

        agg = TelemetryAggregator(db)
        stats = agg.per_model_stats()
        ms = stats[0]

        rf = HeuristicRewardFunction()
        score = rf.compute(
            RoutingContext(query="test"),
            ms.model_id,
            "response",
            latency_seconds=ms.avg_latency,
            cost_usd=ms.total_cost,
            prompt_tokens=ms.prompt_tokens,
            completion_tokens=ms.completion_tokens,
        )
        assert 0.0 <= score <= 1.0
        agg.close()


# ---------------------------------------------------------------------------
# Phase 5 integration tests
# ---------------------------------------------------------------------------


class TestSDKImport:
    """Verify Jarvis class is importable from openjarvis."""

    def test_jarvis_imports(self):
        from openjarvis import Jarvis

        assert Jarvis is not None


class TestSDKAskFlow:
    """SDK ask flow with mocked engine end-to-end."""

    def test_sdk_ask_e2e(self):
        from unittest.mock import patch

        from openjarvis.core.config import JarvisConfig
        from openjarvis.sdk import Jarvis

        engine = _make_engine("SDK response")
        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig(), model="test-model")
            result = j.ask("Hello from integration test")
            assert result == "SDK response"
            j.close()


class TestSDKMemoryHandle:
    """SDK memory handle with SQLite backend."""

    def test_index_and_search(self, tmp_path):
        from openjarvis.core.config import JarvisConfig
        from openjarvis.sdk import MemoryHandle

        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)

        mock_backend = MagicMock()
        mock_backend.store.return_value = "doc-1"
        mock_result = MagicMock()
        mock_result.content = "found content"
        mock_result.score = 0.9
        mock_result.source = "test.txt"
        mock_result.metadata = {}
        mock_backend.retrieve.return_value = [mock_result]
        handle._backend = mock_backend

        # Create a test file with enough content to produce chunks
        test_file = tmp_path / "test.txt"
        words = " ".join(f"word{i}" for i in range(100))
        test_file.write_text(words)

        result = handle.index(str(test_file))
        assert result["chunks"] > 0

        results = handle.search("test")
        assert len(results) == 1
        assert results[0]["content"] == "found content"
        handle.close()


class TestBenchmarkRegistryDiscovery:
    """BenchmarkRegistry discovers latency + throughput."""

    def test_discovers_benchmarks(self):
        from openjarvis.bench import ensure_registered
        from openjarvis.core.registry import BenchmarkRegistry

        ensure_registered()
        assert BenchmarkRegistry.contains("latency")
        assert BenchmarkRegistry.contains("throughput")


class TestBenchmarkSuiteRunAll:
    """BenchmarkSuite runs all and produces JSONL."""

    def test_suite_produces_jsonl(self):
        import json

        from openjarvis.bench import ensure_registered
        from openjarvis.bench._stubs import BenchmarkSuite
        from openjarvis.core.registry import BenchmarkRegistry

        ensure_registered()
        benchmarks = [cls() for _, cls in BenchmarkRegistry.items()]
        suite = BenchmarkSuite(benchmarks)

        engine = _make_engine("benchmark response")
        results = suite.run_all(engine, "test-model", num_samples=2)
        assert len(results) >= 2

        jsonl = suite.to_jsonl(results)
        for line in jsonl.strip().split("\n"):
            obj = json.loads(line)
            assert "benchmark_name" in obj


class TestFullPipeline:
    """Full pipeline: SDK → agent → engine → telemetry."""

    def test_full_pipeline(self, tmp_path):
        from unittest.mock import patch

        from openjarvis.agents._stubs import AgentResult
        from openjarvis.core.config import JarvisConfig
        from openjarvis.core.registry import AgentRegistry
        from openjarvis.sdk import Jarvis

        engine = _make_engine("Pipeline response")

        class PipelineAgent:
            agent_id = "pipeline-test"

            def __init__(self, eng, model, **kwargs):
                self.engine = eng
                self.model = model

            def run(self, input, context=None, **kwargs):
                result = self.engine.generate(
                    [],
                    model=self.model,
                )
                return AgentResult(content=result["content"], turns=1)

        AgentRegistry.register_value("pipeline-test", PipelineAgent)

        cfg = JarvisConfig()
        cfg.telemetry.db_path = str(tmp_path / "telemetry.db")

        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=cfg, model="test-model")
            result = j.ask("Full pipeline test", agent="pipeline-test")
            assert result == "Pipeline response"
            j.close()
