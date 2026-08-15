"""Tests for MonitorOperativeAgent."""

from typing import Any
from unittest.mock import MagicMock

from openjarvis.agents.monitor_operative import MonitorOperativeAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.sessions.session import SessionStore
from openjarvis.tools.storage._stubs import RetrievalResult
from openjarvis.tools.storage_tools import MemoryStoreTool


def _make_engine(content: str = "Hello") -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


class _NativeMemoryBackend:
    def __init__(self) -> None:
        self.documents: list[tuple[str, str, dict[str, Any]]] = []

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.documents.append((content, source, dict(metadata or {})))
        return f"doc-{len(self.documents)}"

    def retrieve(self, query: str, *, top_k: int = 5, **kwargs: Any) -> list:
        return [
            RetrievalResult(
                content=content,
                score=1.0,
                source=source,
                metadata=metadata,
            )
            for content, source, metadata in self.documents
            if source == query or metadata.get("state_key") == query
        ][-top_k:]


class TestMonitorOperativeAgent:
    def test_registration(self) -> None:
        # Import triggers registration; re-register after autouse fixture
        # clears the registry (same pattern as test_monitor.py)
        import openjarvis.agents.monitor_operative  # noqa: F401

        if not AgentRegistry.contains("monitor_operative"):
            AgentRegistry.register_value("monitor_operative", MonitorOperativeAgent)
        assert AgentRegistry.contains("monitor_operative")
        cls = AgentRegistry.get("monitor_operative")
        assert cls is MonitorOperativeAgent

    def test_instantiation(self) -> None:
        engine = _make_engine()
        agent = MonitorOperativeAgent(engine, "test-model")
        assert agent.agent_id == "monitor_operative"
        assert agent.accepts_tools is True

    def test_default_strategies(self) -> None:
        engine = _make_engine()
        agent = MonitorOperativeAgent(engine, "test-model")
        assert agent._memory_extraction == "causality_graph"
        assert agent._observation_compression == "summarize"
        assert agent._retrieval_strategy == "hybrid_with_self_eval"
        assert agent._task_decomposition == "phased"

    def test_custom_strategies(self) -> None:
        engine = _make_engine()
        agent = MonitorOperativeAgent(
            engine,
            "test-model",
            memory_extraction="scratchpad",
            observation_compression="none",
            retrieval_strategy="keyword",
            task_decomposition="monolithic",
        )
        assert agent._memory_extraction == "scratchpad"
        assert agent._observation_compression == "none"

    def test_simple_run(self) -> None:
        engine = _make_engine("The answer is 42.")
        agent = MonitorOperativeAgent(engine, "test-model")
        result = agent.run("What is the answer?")
        assert result.content == "The answer is 42."
        assert result.turns >= 1

    def test_scratchpad_extraction_uses_native_memory_store_contract(self) -> None:
        memory = _NativeMemoryBackend()
        agent = MonitorOperativeAgent(
            _make_engine(),
            "test-model",
            operator_id="monitor-1",
            memory_backend=memory,
        )

        agent._store_scratchpad("web_search", "finding")

        assert memory.documents == [
            (
                "finding",
                "monitor_operative:monitor-1:scratchpad:web_search",
                {},
            )
        ]

    def test_reloads_native_session_after_agent_reconstruction(self, tmp_path) -> None:
        db_path = tmp_path / "monitor-operative-sessions.db"
        session_store = SessionStore(db_path)
        first_agent = MonitorOperativeAgent(
            _make_engine("First response."),
            "test-model",
            operator_id="monitor-1",
            session_store=session_store,
        )
        first_agent.run("First tick")
        session_store.close()

        reopened_store = SessionStore(db_path)
        second_engine = _make_engine("Second response.")
        reconstructed = MonitorOperativeAgent(
            second_engine,
            "test-model",
            operator_id="monitor-1",
            session_store=reopened_store,
        )
        try:
            reconstructed.run("Second tick")
        finally:
            reopened_store.close()

        messages = second_engine.generate.call_args.args[0]
        history = [(message.role.value, message.content) for message in messages]
        assert ("user", "First tick") in history
        assert ("assistant", "First response.") in history

    def test_text_fallback_explicit_state_is_not_superseded_by_final_answer(
        self,
    ) -> None:
        memory = _NativeMemoryBackend()
        engine = _make_engine()
        engine.generate.side_effect = [
            {
                "content": (
                    "Action: memory_store\n"
                    'Action Input: {"content":"explicit text state",'
                    '"source":"monitor_operative:monitor-1:state"}'
                ),
                "usage": {},
                "tool_calls": [],
            },
            {
                "content": "final response",
                "usage": {},
                "tool_calls": [],
            },
        ]
        tool = MemoryStoreTool(memory)
        agent = MonitorOperativeAgent(
            engine,
            "test-model",
            tools=[tool],
            operator_id="monitor-1",
            memory_backend=memory,
            memory_extraction="none",
        )

        result = agent.run("tick")

        assert result.content == "final response"
        state_documents = [
            document
            for document in memory.documents
            if document[1] == "monitor_operative:monitor-1:state"
        ]
        assert len(state_documents) == 1
        reconstructed = MonitorOperativeAgent(
            _make_engine(),
            "test-model",
            operator_id="monitor-1",
            memory_backend=memory,
            memory_extraction="none",
        )
        assert reconstructed._recall_state() == "explicit text state"
