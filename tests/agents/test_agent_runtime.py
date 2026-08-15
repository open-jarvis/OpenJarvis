from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    AgentRunCompleted,
    AgentTextDelta,
    AgentToolFinished,
    BaseAgent,
    register_agent_worker_cancellation,
)
from openjarvis.agents.monitor_operative import MonitorOperativeAgent
from openjarvis.agents.operative import OperativeAgent
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.agents.runtime import NativeAgentRuntime
from openjarvis.core.types import Message, Role, ToolResult
from openjarvis.engine._stubs import StreamChunk
from openjarvis.sessions.session import SessionStore
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.storage._stubs import RetrievalResult


class GeneratingAgent(BaseAgent):
    agent_id = "test-agent"

    def run(self, input: str, context: AgentContext | None = None, **kwargs):
        result = self._generate(self._build_messages(input, context))
        return AgentResult(content=result["content"])


class RecordingEngine:
    def __init__(self) -> None:
        self.models: list[str] = []

    def generate(self, messages, *, model, **kwargs):
        self.models.append(model)
        return {"content": f"answer:{model}"}

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_binding_pins_model_without_mutating_agent() -> None:
    engine = RecordingEngine()
    agent = GeneratingAgent(engine, "server-default")
    binding = NativeAgentRuntime(agent).bind(model="voice-pinned")

    result = await binding.run("hello", AgentContext())

    assert result.content == "answer:voice-pinned"
    assert engine.models == ["voice-pinned"]
    assert agent._model == "server-default"
    assert binding.snapshot.agent_id == "test-agent"
    assert binding.snapshot.model == "voice-pinned"


@pytest.mark.asyncio
async def test_runtime_serializes_two_bindings_for_one_agent() -> None:
    active = 0
    maximum = 0

    class SlowAgent(BaseAgent):
        agent_id = "slow"

        def run(self, input, context=None, **kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            import time

            time.sleep(0.02)
            active -= 1
            return AgentResult(content=input)

    agent = SlowAgent(RecordingEngine(), "default")
    runtime = NativeAgentRuntime(agent)

    await asyncio.gather(
        runtime.bind(model="a").run("one", AgentContext()),
        runtime.bind(model="b").run("two", AgentContext()),
    )

    assert maximum == 1


@pytest.mark.asyncio
async def test_cancelled_compatibility_run_still_serializes_later_turn() -> None:
    active = 0
    maximum = 0
    state_lock = threading.Lock()
    first_started = threading.Event()
    release_first = threading.Event()

    class BlockingAgent(BaseAgent):
        agent_id = "blocking"

        def run(self, input, context=None, **kwargs):
            nonlocal active, maximum
            with state_lock:
                active += 1
                maximum = max(maximum, active)
            try:
                if input == "first":
                    first_started.set()
                    assert release_first.wait(timeout=1)
                return AgentResult(content=input)
            finally:
                with state_lock:
                    active -= 1

    runtime = NativeAgentRuntime(BlockingAgent(RecordingEngine(), "default"))
    binding = runtime.bind(model="voice-pinned")
    first = asyncio.create_task(binding.run("first", AgentContext()))
    assert await asyncio.to_thread(first_started.wait, 1)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(binding.run("second", AgentContext()))
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), timeout=0.05)
    finally:
        release_first.set()

    assert (await second).content == "second"
    assert maximum == 1


@pytest.mark.asyncio
async def test_runtime_pins_model_for_orchestrator_nonsemantic_fallback() -> None:
    engine = RecordingEngine()
    agent = OrchestratorAgent(engine, "server-default")

    result = await NativeAgentRuntime(agent).bind(model="voice-pinned").run(
        "hello", AgentContext()
    )

    assert result.content == "answer:voice-pinned"
    assert engine.models == ["voice-pinned"]
    assert agent._model == "server-default"


@pytest.mark.asyncio
async def test_cancelled_orchestrator_fallback_retains_worker_lease() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    class BlockingFallbackEngine(RecordingEngine):
        def generate(self, messages, *, model, **kwargs):
            del model, kwargs
            input_text = messages[-1].content
            if input_text == "first":
                first_started.set()
                assert release_first.wait(timeout=1)
            else:
                second_started.set()
            return {"content": input_text}

    runtime = NativeAgentRuntime(
        OrchestratorAgent(BlockingFallbackEngine(), "server-default")
    )
    binding = runtime.bind(model="voice-pinned")
    first = asyncio.create_task(binding.run("first", AgentContext()))
    assert await asyncio.to_thread(first_started.wait, 1)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(binding.run("second", AgentContext()))
    try:
        assert not await asyncio.to_thread(second_started.wait, 0.05)
    finally:
        release_first.set()

    assert (await second).content == "second"


class _BlockingStreamingTool(BaseTool):
    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self.second_started = threading.Event()
        self.calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="blocking_tool",
            description="Block the first sync worker",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params) -> ToolResult:
        del params
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            assert self.release_first.wait(timeout=1)
        else:
            self.second_started.set()
        return ToolResult(tool_name="blocking_tool", content="ok", success=True)


class _StreamingToolEngine:
    def generate(self, *args, **kwargs):
        raise AssertionError("semantic run must use stream_full")

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        del model
        return True

    async def stream_full(self, messages: list[Message], **kwargs):
        del kwargs
        if any(message.role == Role.TOOL for message in messages):
            yield StreamChunk(content="done")
            yield StreamChunk(finish_reason="stop")
            return
        yield StreamChunk(
            tool_calls=[
                {
                    "index": 0,
                    "id": "call-1",
                    "function": {"name": "blocking_tool", "arguments": "{}"},
                }
            ]
        )
        yield StreamChunk(finish_reason="tool_calls")


@pytest.mark.asyncio
async def test_cancelled_streaming_tool_retains_worker_lease() -> None:
    tool = _BlockingStreamingTool()
    runtime = NativeAgentRuntime(
        OrchestratorAgent(
            _StreamingToolEngine(),
            "server-default",
            tools=[tool],
        )
    )
    binding = runtime.bind(model="voice-pinned")
    first = asyncio.create_task(binding.run("first", AgentContext()))
    assert await asyncio.to_thread(tool.first_started.wait, 1)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(binding.run("second", AgentContext()))
    try:
        assert not await asyncio.to_thread(tool.second_started.wait, 0.05)
    finally:
        tool.release_first.set()

    assert (await second).content == "done"


@pytest.mark.asyncio
async def test_stream_closed_by_another_task_still_releases_runtime() -> None:
    runtime = NativeAgentRuntime(GeneratingAgent(RecordingEngine(), "default"))
    binding = runtime.bind(model="voice-pinned")

    stream = binding.run_stream("first", AgentContext())
    await stream.__anext__()
    # asyncio finalizes an abandoned stream from its own Task, so the closing
    # Context is not the one that entered the run and set the worker lease.
    await asyncio.create_task(stream.aclose())

    second = await asyncio.wait_for(
        binding.run("second", AgentContext()), timeout=1
    )
    assert second.content == "answer:voice-pinned"


class _PersistentMemory:
    def __init__(self) -> None:
        self.documents: list[RetrievalResult] = []

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.documents.append(
            RetrievalResult(
                content=content,
                source=source,
                metadata=dict(metadata or {}),
            )
        )
        return f"doc-{len(self.documents)}"

    def retrieve(self, query: str, *, top_k: int = 5, **kwargs: Any):
        del kwargs
        return [
            document
            for document in self.documents
            if document.source == query
            or document.metadata.get("state_key") == query
        ][-top_k:]


class _BlockingPersistentEngine:
    def generate(self, messages, **kwargs):
        import time

        del kwargs
        input_text = messages[-1].content
        if input_text == "first":
            time.sleep(0.05)
        return {"content": f"answer:{input_text}", "usage": {}}


def _persistent_agent(
    agent_type,
    engine,
    session_store: SessionStore,
    memory: _PersistentMemory,
):
    kwargs: dict[str, Any] = {}
    if agent_type is MonitorOperativeAgent:
        kwargs["memory_extraction"] = "none"
    return agent_type(
        engine,
        "server-default",
        operator_id="voice-operator",
        session_store=session_store,
        memory_backend=memory,
        **kwargs,
    )


@pytest.mark.parametrize("agent_type", [OperativeAgent, MonitorOperativeAgent])
@pytest.mark.asyncio
async def test_cancelled_persistent_agent_discards_assistant_and_state(
    agent_type,
    tmp_path,
) -> None:
    sessions = SessionStore(tmp_path / f"{agent_type.agent_id}.db")
    memory = _PersistentMemory()
    engine = _BlockingPersistentEngine()
    binding = NativeAgentRuntime(
        _persistent_agent(agent_type, engine, sessions, memory)
    ).bind(model="voice-pinned")
    first = asyncio.create_task(binding.run("first", AgentContext()))
    await asyncio.sleep(0.01)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await binding.run("second", AgentContext())).content == "answer:second"
    persisted = sessions.get_or_create(
        f"{agent_type.agent_id}:voice-operator"
    ).messages
    try:
        assert ("user", "first") in [
            (message.role, message.content) for message in persisted
        ]
        assert ("assistant", "answer:first") not in [
            (message.role, message.content) for message in persisted
        ]
        assert all(document.content != "answer:first" for document in memory.documents)
    finally:
        sessions.close()


@pytest.mark.asyncio
async def test_discarded_persistence_key_never_reaches_durable_stores(
    tmp_path,
) -> None:
    sessions = SessionStore(tmp_path / "discarded.db")
    memory = _PersistentMemory()

    class Engine:
        def generate(self, messages, **kwargs):
            del kwargs
            return {"content": f"answer:{messages[-1].content}", "usage": {}}

    binding = NativeAgentRuntime(
        _persistent_agent(OperativeAgent, Engine(), sessions, memory)
    ).bind(model="voice-pinned")
    try:
        await binding.run("first", AgentContext(), persistence_key="barged-turn")
        # The browser never played this answer, so the turn is abandoned.
        await binding.discard_persistence("barged-turn")
        # A commit after a discard must stay a no-op, not resurrect the answer.
        await binding.commit_persistence("barged-turn")

        session = sessions.get_or_create(f"{OperativeAgent.agent_id}:voice-operator")
        assert [
            (message.role, message.content) for message in session.messages
        ] == [("user", "first")]
        assert memory.documents == []
    finally:
        sessions.close()


@pytest.mark.parametrize("agent_type", [OperativeAgent, MonitorOperativeAgent])
@pytest.mark.asyncio
async def test_persistent_agent_commits_derived_state_only_on_explicit_boundary(
    agent_type,
    tmp_path,
) -> None:
    sessions = SessionStore(tmp_path / f"played-{agent_type.agent_id}.db")
    memory = _PersistentMemory()

    class Engine:
        def generate(self, messages, **kwargs):
            del kwargs
            return {"content": f"answer:{messages[-1].content}", "usage": {}}

    binding = NativeAgentRuntime(
        _persistent_agent(agent_type, Engine(), sessions, memory)
    ).bind(model="voice-pinned")
    persistence_key = "voice-turn-1"

    def persisted() -> list[tuple[str, str]]:
        # Re-read: Session.messages is a snapshot, not a live view.
        session = sessions.get_or_create(f"{agent_type.agent_id}:voice-operator")
        return [(message.role, message.content) for message in session.messages]

    try:
        result = await binding.run(
            "first",
            AgentContext(),
            persistence_key=persistence_key,
        )

        assert result.content == "answer:first"
        assert persisted() == [("user", "first")]
        assert memory.documents == []

        await binding.commit_persistence(persistence_key)

        assert persisted() == [
            ("user", "first"),
            ("assistant", "answer:first"),
        ]
        assert [document.content for document in memory.documents] == ["answer:first"]
    finally:
        sessions.close()


class _CancellableStreamingTool(BaseTool):
    """Stands in for an in-flight MCP ``tools/call`` that honors cancellation."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancel_signalled = threading.Event()
        self.settled = threading.Event()
        self.second_started = threading.Event()
        self.calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="blocking_tool",
            description="Block the first sync worker until it settles",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params) -> ToolResult:
        del params
        self.calls += 1
        if self.calls == 1:
            unregister = register_agent_worker_cancellation(self.cancel_signalled.set)
            try:
                self.started.set()
                assert self.settled.wait(timeout=2)
            finally:
                unregister()
        else:
            self.second_started.set()
        return ToolResult(tool_name="blocking_tool", content="ok", success=True)


@pytest.mark.asyncio
async def test_cancelled_stream_signals_worker_and_holds_turn_until_settled() -> None:
    tool = _CancellableStreamingTool()
    runtime = NativeAgentRuntime(
        OrchestratorAgent(_StreamingToolEngine(), "server-default", tools=[tool])
    )
    binding = runtime.bind(model="voice-pinned")

    first = asyncio.create_task(binding.run("first", AgentContext()))
    assert await asyncio.to_thread(tool.started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert tool.cancel_signalled.wait(timeout=1)

    second = asyncio.create_task(binding.run("second", AgentContext()))
    assert not await asyncio.to_thread(tool.second_started.wait, 0.05)
    tool.settled.set()
    assert (await second).content == "done"


@pytest.mark.asyncio
async def test_cancellation_registered_after_cancel_fires_immediately() -> None:
    """Closes the race between worker startup and caller interruption."""
    entered = threading.Event()
    release = threading.Event()
    signalled = threading.Event()

    class _LateRegisteringTool(_CancellableStreamingTool):
        def execute(self, **params) -> ToolResult:
            del params
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert release.wait(timeout=2)
                register_agent_worker_cancellation(signalled.set)
                assert self.settled.wait(timeout=2)
            else:
                self.second_started.set()
            return ToolResult(tool_name="blocking_tool", content="ok", success=True)

    tool = _LateRegisteringTool()
    runtime = NativeAgentRuntime(
        OrchestratorAgent(_StreamingToolEngine(), "server-default", tools=[tool])
    )
    binding = runtime.bind(model="voice-pinned")

    first = asyncio.create_task(binding.run("first", AgentContext()))
    assert await asyncio.to_thread(entered.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    assert await asyncio.to_thread(signalled.wait, 1)
    tool.settled.set()


@pytest.mark.asyncio
async def test_cancelled_stream_emits_no_stale_events_to_that_caller() -> None:
    tool = _CancellableStreamingTool()
    runtime = NativeAgentRuntime(
        OrchestratorAgent(_StreamingToolEngine(), "server-default", tools=[tool])
    )
    binding = runtime.bind(model="voice-pinned")
    events: list[Any] = []

    async def _drain() -> None:
        async for event in binding.run_stream("first", AgentContext()):
            events.append(event)

    first = asyncio.create_task(_drain())
    assert await asyncio.to_thread(tool.started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert tool.cancel_signalled.wait(timeout=1)

    tool.settled.set()
    await asyncio.sleep(0.1)
    assert not any(
        isinstance(event, (AgentToolFinished, AgentTextDelta, AgentRunCompleted))
        for event in events
    )
