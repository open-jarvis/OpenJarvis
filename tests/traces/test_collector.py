"""Tests for the TraceCollector."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

import pytest

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    AgentRunCompleted,
    AgentTextDelta,
    AgentToolFinished,
    AgentToolStarted,
    BaseAgent,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import StepType
from openjarvis.traces.collector import TraceCollector
from openjarvis.traces.store import TraceStore


class _FakeAgent(BaseAgent):
    """Minimal agent that returns a fixed response."""

    agent_id = "fake"

    def __init__(
        self,
        response: str = "test response",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._response = response
        self._bus = bus

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        # Simulate an inference step via event bus
        if self._bus:
            self._bus.publish(
                EventType.INFERENCE_START,
                {
                    "model": "qwen3:8b",
                    "engine": "ollama",
                },
            )
            self._bus.publish(
                EventType.INFERENCE_END,
                {
                    "total_tokens": 50,
                },
            )
        return AgentResult(content=self._response, turns=1)


class _ToolAgent(BaseAgent):
    """Agent that simulates a tool call during execution."""

    agent_id = "tool_agent"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        # Simulate inference + tool call + inference
        inf = {"model": "qwen3:8b", "engine": "ollama"}
        self._bus.publish(EventType.INFERENCE_START, inf)
        self._bus.publish(EventType.INFERENCE_END, {"total_tokens": 30})
        self._bus.publish(
            EventType.TOOL_CALL_START,
            {
                "tool": "calculator",
                "arguments": {"expr": "2+2"},
            },
        )
        self._bus.publish(
            EventType.TOOL_CALL_END,
            {
                "tool": "calculator",
                "success": True,
                "latency": 0.01,
            },
        )
        self._bus.publish(EventType.INFERENCE_START, inf)
        self._bus.publish(EventType.INFERENCE_END, {"total_tokens": 20})
        return AgentResult(content="4", turns=2)


class _InterleavedToolAgent(BaseAgent):
    """Simulate two parallel calls whose start/end events interleave."""

    agent_id = "parallel_tool_agent"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        first = {"method": "GET", "url": "https://shop.example/menu/food"}
        second = {"method": "GET", "url": "https://shop.example/menu/drinks"}
        self._bus.publish(
            EventType.TOOL_CALL_START,
            {"tool": "http_request", "arguments": first},
        )
        self._bus.publish(
            EventType.TOOL_CALL_START,
            {"tool": "http_request", "arguments": second},
        )
        self._bus.publish(
            EventType.TOOL_CALL_END,
            {
                "tool": "http_request",
                "success": True,
                "latency": 0.01,
                "result": '{"items": ["food"]}',
                "metadata": {"arguments": first},
            },
        )
        self._bus.publish(
            EventType.TOOL_CALL_END,
            {
                "tool": "http_request",
                "success": True,
                "latency": 0.01,
                "result": '{"items": ["drinks"]}',
                "metadata": {"arguments": second},
            },
        )
        return AgentResult(content="menus displayed", turns=1)


class _StreamingAgent(BaseAgent):
    """Small local stream fixture covering every native stream event."""

    agent_id = "streaming"

    def __init__(self) -> None:
        pass

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        return AgentResult(content="completed", turns=1)

    async def run_stream(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ):
        yield AgentTextDelta("partial")
        yield AgentToolStarted("local_tool")
        yield AgentToolFinished("local_tool", ok=True)
        yield AgentRunCompleted(AgentResult(content="completed", turns=1))


class _BlockingStreamingAgent(_StreamingAgent):
    """Stream fixture whose completion is never reached after cancellation."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_stream(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ):
        yield AgentTextDelta("partial")
        self.started.set()
        await self.release.wait()
        yield AgentRunCompleted(AgentResult(content="completed", turns=1))


class TestTraceCollector:
    @pytest.mark.asyncio
    async def test_failed_admission_journal_does_not_execute_agent(self, tmp_path):
        class RejectingStore(TraceStore):
            def submit_write(self, method, /, *args, **kwargs):
                raise RuntimeError("trace_writer_capacity_exhausted")

        calls = []

        class Recording(_StreamingAgent):
            async def run_stream(self, input, context=None, **kwargs):
                calls.append(input)
                yield AgentRunCompleted(AgentResult(content="should not execute"))

        store = RejectingStore(tmp_path / "full.db")
        collector = TraceCollector(Recording(), store=store)
        try:
            with pytest.raises(RuntimeError, match="trace_admission_not_durable"):
                async for _ in collector.run_stream("must be traceable"):
                    pass
            assert calls == []
        finally:
            store.close()

    @pytest.mark.asyncio
    async def test_sqlite_writer_contention_does_not_block_voice_event_loop(
        self, tmp_path
    ):
        db = tmp_path / "busy.db"
        store = TraceStore(db)
        blocker = sqlite3.connect(db, check_same_thread=False)
        blocker.execute("BEGIN IMMEDIATE")
        released = threading.Event()

        def release():
            blocker.rollback()
            blocker.close()
            released.set()

        timer = threading.Timer(0.3, release)
        timer.start()
        loop = asyncio.get_running_loop()
        started = loop.time()
        ticks = []
        loop.call_later(0.02, lambda: ticks.append(loop.time() - started))
        collector = TraceCollector(_StreamingAgent(), store=store)
        try:
            async for _ in collector.run_stream("keep VAD responsive"):
                pass
            await asyncio.sleep(0.01)
            assert ticks and ticks[0] < 0.15
        finally:
            assert await asyncio.to_thread(released.wait, 1)
            store.close()

    @pytest.mark.asyncio
    async def test_interrupted_inference_keeps_its_unfinished_step(self, tmp_path):
        bus = EventBus()
        store = TraceStore(tmp_path / "trace.db")

        class Pending(_StreamingAgent):
            async def run_stream(self, input, context=None, **kwargs):
                bus.publish(EventType.INFERENCE_START, {"model": "luna"})
                yield AgentTextDelta("partial")
                await asyncio.Event().wait()

        collector = TraceCollector(Pending(), store=store, bus=bus)
        stream = collector.run_stream("cancel me")
        await anext(stream)
        await stream.aclose()
        trace = store.list_traces()[0]
        assert len(trace.steps) == 1
        assert trace.steps[0].step_type == StepType.GENERATE
        assert trace.steps[0].metadata["status"] == "interrupted"
        assert trace.steps[0].metadata["ttft"] is None
        store.close()

    def test_interleaved_tool_events_match_invocation_identity(self, tmp_path):
        bus = EventBus()
        store = TraceStore(tmp_path / "trace.db")
        starts = []

        class Interleaved(_FakeAgent):
            def run(self, input, context=None, **kwargs):
                for identity in ("a", "b"):
                    starts.append(
                        bus.publish(
                            EventType.TOOL_CALL_START,
                            {
                                "tool": "http_request",
                                "invocation_id": identity,
                                "arguments": {"id": identity},
                            },
                        )
                    )
                for identity in ("a", "b"):
                    bus.publish(
                        EventType.TOOL_CALL_END,
                        {
                            "tool": "http_request",
                            "invocation_id": identity,
                            "success": True,
                        },
                    )
                return AgentResult(content="done")

        TraceCollector(Interleaved(), store=store, bus=bus).run("parallel")
        steps = store.list_traces()[0].steps[:2]
        assert [s.input["arguments"] for s in steps] == [{"id": "a"}, {"id": "b"}]
        assert [s.timestamp for s in steps] == [e.timestamp for e in starts]
        store.close()

    @pytest.mark.asyncio
    async def test_concurrent_streams_keep_their_own_inference_steps(self, tmp_path):
        bus = EventBus()
        store = TraceStore(tmp_path / "runs.db")
        both_started = asyncio.Event()
        started = 0

        class Interleaved(_StreamingAgent):
            async def run_stream(self, input, context=None, **kwargs):
                nonlocal started
                bus.publish(EventType.INFERENCE_START, {"model": input})
                started += 1
                if started == 2:
                    both_started.set()
                await both_started.wait()
                bus.publish(EventType.INFERENCE_END, {"content": input})
                yield AgentRunCompleted(AgentResult(content=input))

        collector = TraceCollector(Interleaved(), store=store, bus=bus)

        async def drain(prompt):
            return [item async for item in collector.run_stream(prompt)]

        await asyncio.gather(drain("first"), drain("second"))
        traces = store.list_traces()
        assert len({trace.trace_id for trace in traces}) == 2
        for trace in traces:
            steps = [s for s in trace.steps if s.step_type == StepType.GENERATE]
            assert [(s.input["model"], s.output["content"]) for s in steps] == [
                (trace.query, trace.query)
            ]
        store.close()

    @pytest.mark.asyncio
    async def test_admission_is_journaled_before_a_stream_finishes(self, tmp_path):
        store = TraceStore(tmp_path / "runs.db")
        collector = TraceCollector(_StreamingAgent(), store=store)
        stream = collector.run_stream("retain me")
        try:
            await anext(stream)
            events = store.run_events()
            assert events[0]["event_type"] == "run_admitted"
            assert events[0]["data"]["query"] == "retain me"
        finally:
            await stream.aclose()
        events = store.run_events()
        assert events[-1]["event_type"] == "run_interrupted"
        assert {e["run_id"] for e in events} == {store.list_traces()[0].trace_id}
        store.close()

    def test_basic_collection(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(response="hello", bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        result = collector.run("say hello")

        assert result.content == "hello"
        assert store.count() == 1

        traces = store.list_traces()
        trace = traces[0]
        assert trace.query == "say hello"
        assert trace.agent == "fake"
        assert trace.model == "qwen3:8b"
        assert trace.engine == "ollama"
        assert trace.result == "hello"
        store.close()

    def test_records_generate_steps(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("test")

        trace = store.list_traces()[0]
        generate_steps = [s for s in trace.steps if s.step_type == StepType.GENERATE]
        assert len(generate_steps) == 1
        assert generate_steps[0].output.get("tokens") == 50
        store.close()

    def test_records_tool_steps(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _ToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        tool_steps = [s for s in trace.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) == 1
        assert tool_steps[0].input["tool"] == "calculator"
        assert tool_steps[0].output["success"] is True
        store.close()

    def test_parallel_tool_steps_keep_their_own_arguments(self, tmp_path: Path) -> None:
        """End metadata identifies each call even when starts overlap."""
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        collector = TraceCollector(_InterleavedToolAgent(bus), store=store, bus=bus)

        collector.run("show food and drinks")

        steps = [
            step
            for step in store.list_traces()[0].steps
            if step.step_type == StepType.TOOL_CALL
        ]
        assert [step.input["arguments"]["url"] for step in steps] == [
            "https://shop.example/menu/food",
            "https://shop.example/menu/drinks",
        ]
        store.close()

    def test_records_respond_step(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(response="final answer", bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("test")

        trace = store.list_traces()[0]
        respond_steps = [s for s in trace.steps if s.step_type == StepType.RESPOND]
        assert len(respond_steps) == 1
        assert respond_steps[0].output["content"] == "final answer"
        store.close()

    def test_records_memory_retrieve(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        # Monkey-patch agent to emit memory event
        original_run = agent.run

        def run_with_memory(input, context=None, **kwargs):
            bus.publish(
                EventType.MEMORY_RETRIEVE,
                {
                    "query": "meeting notes",
                    "num_results": 3,
                    "latency": 0.2,
                },
            )
            return original_run(input, context=context, **kwargs)

        agent.run = run_with_memory
        collector.run("find my meeting notes")

        trace = store.list_traces()[0]
        retrieve_steps = [s for s in trace.steps if s.step_type == StepType.RETRIEVE]
        assert len(retrieve_steps) == 1
        assert retrieve_steps[0].input["query"] == "meeting notes"
        store.close()

    def test_publishes_trace_complete(self, tmp_path: Path) -> None:
        bus = EventBus(record_history=True)
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("test")

        trace_events = [
            e for e in bus.history if e.event_type == EventType.TRACE_COMPLETE
        ]
        assert len(trace_events) == 1
        assert trace_events[0].data["trace"].query == "test"
        store.close()

    def test_no_store(self) -> None:
        """Collector works without a store (just collects, doesn't persist)."""
        bus = EventBus()
        agent = _FakeAgent(response="ok", bus=bus)
        collector = TraceCollector(agent, bus=bus)  # no store

        result = collector.run("test")
        assert result.content == "ok"

    def test_no_bus(self, tmp_path: Path) -> None:
        """Collector works without a bus (no event-based step collection)."""
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(response="ok")
        collector = TraceCollector(agent, store=store)  # no bus

        result = collector.run("test")
        assert result.content == "ok"
        assert store.count() == 1
        # Only the RESPOND step (no events to capture)
        trace = store.list_traces()[0]
        assert len(trace.steps) == 1
        assert trace.steps[0].step_type == StepType.RESPOND
        store.close()

    def test_a_store_save_failure_does_not_lose_the_completed_answer(self) -> None:
        """The agent has already produced a result by the time save() runs --
        a persistence bug (e.g. an unserializable field the json.dumps
        default= fallback doesn't catch) must not turn that into a 500 for
        the caller."""

        class _ExplodingStore:
            def save(self, trace: Any) -> None:
                raise TypeError("boom")

        bus = EventBus()
        agent = _FakeAgent(response="ok", bus=bus)
        collector = TraceCollector(agent, store=_ExplodingStore(), bus=bus)

        result = collector.run("test")  # must not raise

        assert result.content == "ok"

    def test_timing(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        before = time.time()
        collector.run("test")
        after = time.time()

        trace = store.list_traces()[0]
        assert trace.started_at >= before
        assert trace.ended_at <= after
        assert trace.ended_at >= trace.started_at
        store.close()

    def test_unsubscribes_after_run(self, tmp_path: Path) -> None:
        """Events after run() completes should NOT affect the next trace."""
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("first")

        # Emit events after run — should not affect stored trace
        bus.publish(EventType.INFERENCE_START, {"model": "stray"})
        bus.publish(EventType.INFERENCE_END, {"total_tokens": 999})

        assert store.count() == 1
        trace = store.list_traces()[0]
        # No step with model="stray"
        for s in trace.steps:
            assert s.input.get("model") != "stray"
        store.close()

    @pytest.mark.asyncio
    async def test_run_stream_forwards_events_and_records_one_completed_trace(
        self, tmp_path: Path
    ) -> None:
        """Dropping a native event or terminal trace side effect is a bug."""
        bus = EventBus(record_history=True)
        store = TraceStore(tmp_path / "test.db")
        collector = TraceCollector(_StreamingAgent(), store=store, bus=bus)

        events = [event async for event in collector.run_stream("stream this")]

        assert events == [
            AgentTextDelta("partial"),
            AgentToolStarted("local_tool"),
            AgentToolFinished("local_tool", ok=True),
            AgentRunCompleted(AgentResult(content="completed", turns=1)),
        ]
        assert store.count() == 1
        assert store.list_traces()[0].result == "completed"
        assert [event.event_type for event in bus.history].count(
            EventType.TRACE_COMPLETE
        ) == 1
        store.close()

    @pytest.mark.asyncio
    async def test_run_stream_records_abandonment_without_publishing_success(
        self, tmp_path: Path
    ) -> None:
        """Diagnostic retention must not teach an unobserved answer."""
        bus = EventBus(record_history=True)
        store = TraceStore(tmp_path / "test.db")
        collector = TraceCollector(_StreamingAgent(), store=store, bus=bus)

        stream = collector.run_stream("stream this")
        assert await stream.__anext__() == AgentTextDelta("partial")
        await stream.aclose()

        assert store.count() == 1
        trace = store.list_traces()[0]
        assert trace.metadata["status"] == "interrupted"
        assert trace.result == ""
        assert not any(
            event.event_type == EventType.TRACE_COMPLETE for event in bus.history
        )
        store.close()

    @pytest.mark.asyncio
    async def test_run_stream_records_cancellation_without_publishing_success(
        self, tmp_path: Path
    ) -> None:
        """Cancellation must remain observable without a completed answer."""
        bus = EventBus(record_history=True)
        store = TraceStore(tmp_path / "test.db")
        agent = _BlockingStreamingAgent()
        collector = TraceCollector(agent, store=store, bus=bus)

        async def drain() -> None:
            async for _event in collector.run_stream("stream this"):
                pass

        task = asyncio.create_task(drain())
        await agent.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert store.count() == 1
        trace = store.list_traces()[0]
        assert trace.metadata["status"] == "interrupted"
        assert trace.metadata["ttft_seconds"] is None
        assert not any(
            event.event_type == EventType.TRACE_COMPLETE for event in bus.history
        )
        store.close()


class _RichToolAgent(BaseAgent):
    """Agent that emits content-enriched events for testing."""

    agent_id = "rich_tool_agent"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        from openjarvis.core.types import ToolResult

        # Turn 1: inference with tool call request
        self._bus.publish(
            EventType.INFERENCE_START,
            {
                "model": "test-model",
                "engine": "test",
            },
        )
        self._bus.publish(
            EventType.INFERENCE_END,
            {
                "total_tokens": 30,
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                "content": "I'll calculate that for you.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "calculator",
                        "arguments": '{"expr": "2+2"}',
                    },
                ],
                "finish_reason": "tool_calls",
            },
        )
        # Tool execution
        self._bus.publish(
            EventType.TOOL_CALL_START,
            {
                "tool": "calculator",
                "arguments": {"expr": "2+2"},
            },
        )
        self._bus.publish(
            EventType.TOOL_CALL_END,
            {
                "tool": "calculator",
                "success": True,
                "latency": 0.01,
                "result": "4",
            },
        )
        # Turn 2: final answer
        self._bus.publish(
            EventType.INFERENCE_START,
            {
                "model": "test-model",
                "engine": "test",
            },
        )
        self._bus.publish(
            EventType.INFERENCE_END,
            {
                "total_tokens": 15,
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "content": "The answer is 4.",
                "tool_calls": [],
                "finish_reason": "stop",
            },
        )

        # Return result with messages in metadata
        messages = [
            {"role": "user", "content": input},
            {"role": "assistant", "content": "I'll calculate that for you."},
            {"role": "tool", "content": "4", "name": "calculator"},
            {"role": "assistant", "content": "The answer is 4."},
        ]
        return AgentResult(
            content="The answer is 4.",
            tool_results=[
                ToolResult(tool_name="calculator", content="4", success=True),
            ],
            turns=2,
            metadata={"messages": messages},
        )


class TestRichTraceCollector:
    def test_captures_content_in_generate_steps(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        gen_steps = [s for s in trace.steps if s.step_type == StepType.GENERATE]
        assert len(gen_steps) == 2
        assert gen_steps[0].output["content"] == "I'll calculate that for you."
        expected_tc = [
            {"id": "call_1", "name": "calculator", "arguments": '{"expr": "2+2"}'},
        ]
        assert gen_steps[0].output["tool_calls"] == expected_tc
        assert gen_steps[0].output["finish_reason"] == "tool_calls"
        assert gen_steps[1].output["content"] == "The answer is 4."
        assert gen_steps[1].output["finish_reason"] == "stop"
        store.close()

    def test_captures_tool_arguments_and_result(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        tool_steps = [s for s in trace.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) == 1
        assert tool_steps[0].input["tool"] == "calculator"
        assert tool_steps[0].input["arguments"] == {"expr": "2+2"}
        assert tool_steps[0].output["result"] == "4"
        assert tool_steps[0].output["success"] is True
        store.close()

    def test_captures_messages_in_trace(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        assert len(trace.messages) == 4
        assert trace.messages[0]["role"] == "user"
        assert trace.messages[3]["role"] == "assistant"
        store.close()

    def test_last_trace_property(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = collector.last_trace
        assert trace is not None
        assert trace.query == "What is 2+2?"
        assert len(trace.messages) == 4
        store.close()
