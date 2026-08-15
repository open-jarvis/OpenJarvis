"""Tests for the OrchestratorAgent."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    AgentRunCompleted,
    AgentTextDelta,
)
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Conversation, Message, Role, ToolResult
from openjarvis.engine._stubs import StreamChunk
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CalculatorStub(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="Math calculator.",
            parameters={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        )

    def execute(self, **params) -> ToolResult:
        expr = params.get("expression", "0")
        try:
            val = eval(expr)  # noqa: S307 — safe in tests
        except Exception as e:
            return ToolResult(tool_name="calculator", content=str(e), success=False)
        return ToolResult(tool_name="calculator", content=str(val), success=True)


class _ThinkStub(BaseTool):
    tool_id = "think"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="think",
            description="Thinking tool.",
            parameters={
                "type": "object",
                "properties": {"thought": {"type": "string"}},
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(
            tool_name="think",
            content=params.get("thought", ""),
            success=True,
        )


class _CountingClickStub(BaseTool):
    tool_id = "browser_click"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browser_click",
            description="Click one browser element.",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params: Any) -> ToolResult:
        del params
        with self._lock:
            self.calls += 1
        return ToolResult(
            tool_name="browser_click",
            content="clicked",
            success=True,
        )


class _ExternalToolStub(BaseTool):
    tool_id = "external"

    def __init__(
        self,
        name: str,
        *,
        read_only: bool,
        outcomes: list[bool],
        server: str = "playwright",
    ) -> None:
        self._name = name
        self._read_only = read_only
        self._outcomes = list(outcomes)
        self._server = server

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description=self._name,
            parameters={"type": "object", "properties": {}},
            metadata={
                "mcp": {
                    "server": self._server,
                    "annotations": {
                        "readOnlyHint": self._read_only,
                        "openWorldHint": True,
                    },
                }
            },
        )

    def execute(self, **params: Any) -> ToolResult:
        del params
        success = self._outcomes.pop(0)
        return ToolResult(
            tool_name=self._name,
            content="ok" if success else "blocked",
            success=success,
        )


def _stream_tool_round(name: str, index: int) -> list[StreamChunk]:
    return [
        StreamChunk(
            tool_calls=[
                {
                    "index": 0,
                    "id": f"call-{index}",
                    "function": {"name": name, "arguments": "{}"},
                }
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


def _stream_final_round(content: str) -> list[StreamChunk]:
    return [
        StreamChunk(content=content),
        StreamChunk(finish_reason="stop"),
    ]


class _PendingApprovalStub(_ThinkStub):
    tool_id = "approval"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="approval",
            description="Requires an approval.",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params) -> ToolResult:
        del params
        return ToolResult(
            tool_name="approval",
            content="Approval required.",
            metadata={"pending_approval": 1},
        )


class StreamingEngine:
    def __init__(
        self,
        output: list[str] | list[list[StreamChunk]],
    ) -> None:
        if not output or isinstance(output[0], str):
            self._rounds = [
                [
                    *(StreamChunk(content=content) for content in output),
                    StreamChunk(finish_reason="stop"),
                ]
            ]
        else:
            self._rounds = list(output)
        self.calls: list[tuple[Sequence[Message], dict[str, Any]]] = []

    def generate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("run_stream must consume stream_full")

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        del model
        return True

    async def stream_full(
        self,
        messages: Sequence[Message],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append((messages, kwargs))
        for chunk in self._rounds.pop(0):
            yield chunk


class EventPublishingStreamingEngine(StreamingEngine):
    _publishes_stream_events = True

    def __init__(self, output: list[str], bus: EventBus) -> None:
        super().__init__(output)
        self._bus = bus

    async def stream_full(
        self,
        messages: Sequence[Message],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self._bus.publish(EventType.INFERENCE_START, {"source": "engine"})
        async for chunk in super().stream_full(messages, **kwargs):
            yield chunk
        self._bus.publish(EventType.INFERENCE_END, {"source": "engine"})


class PausingSemanticStreamingEngine:
    def __init__(self, reasoning_chunks: int = 20) -> None:
        self._reasoning_chunks = reasoning_chunks
        self.release = asyncio.Event()

    def generate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("run_stream must consume stream_full")

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        del model
        return True

    async def stream_full(
        self,
        messages: Sequence[Message],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        del messages, kwargs
        for index in range(self._reasoning_chunks):
            yield StreamChunk(reasoning_content=f"private {index}")
        yield StreamChunk(content="Visible")
        await self.release.wait()
        yield StreamChunk(finish_reason="stop")


class RepeatableToolStreamingEngine:
    """Emit the same tool call once per independent top-level run."""

    def generate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("run_stream must consume stream_full")

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        del model
        return True

    async def stream_full(
        self,
        messages: Sequence[Message],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        del kwargs
        if any(message.role == Role.TOOL for message in messages):
            yield StreamChunk(content="Đã xong.")
            yield StreamChunk(finish_reason="stop")
            return
        yield StreamChunk(
            tool_calls=[
                {
                    "index": 0,
                    "id": "same-call",
                    "function": {
                        "name": "browser_click",
                        "arguments": '{"target":"menu"}',
                    },
                }
            ]
        )
        yield StreamChunk(finish_reason="tool_calls")


async def _collect_agent_stream(
    agent: OrchestratorAgent, input: str
) -> list[AgentTextDelta | AgentRunCompleted]:
    return [event async for event in agent.run_stream(input)]


def _make_engine_no_tools(content: str = "Final answer.") -> MagicMock:
    """Engine that never returns tool calls."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _make_engine_with_tool_call(
    tool_name: str = "calculator",
    arguments: str = '{"expression":"2+2"}',
    tool_call_id: str = "call_1",
    final_content: str = "The answer is 4.",
) -> MagicMock:
    """Engine that returns one tool call then a final answer."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.side_effect = [
        # First call: tool call
        {
            "content": "",
            "tool_calls": [
                {"id": tool_call_id, "name": tool_name, "arguments": arguments}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        },
        # Second call: final answer
        {
            "content": final_content,
            "usage": {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20},
            "model": "test-model",
            "finish_reason": "stop",
        },
    ]
    return engine


def _make_engine_multi_tool() -> MagicMock:
    """Engine that calls multiple tools in one turn."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.side_effect = [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "calculator",
                    "arguments": '{"expression":"2+2"}',
                },
                {
                    "id": "call_2",
                    "name": "think",
                    "arguments": '{"thought":"thinking..."}',
                },
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        },
        {
            "content": "Done.",
            "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
            "model": "test-model",
            "finish_reason": "stop",
        },
    ]
    return engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOrchestratorAgent:
    @pytest.mark.asyncio
    async def test_loop_guard_state_is_fresh_for_each_sequential_run(self) -> None:
        tool = _CountingClickStub()
        agent = OrchestratorAgent(
            RepeatableToolStreamingEngine(),
            "deepseek-v4-flash",
            tools=[tool],
            loop_guard_config={
                "max_identical_calls": 1,
                "warn_before_block": False,
            },
        )

        results = []
        for _ in range(2):
            events = [event async for event in agent.run_stream("bấm menu")]
            results.append(events[-1].result)

        assert tool.calls == 2
        assert all(result.tool_results[0].success for result in results)

    @pytest.mark.asyncio
    async def test_loop_guard_state_is_isolated_between_concurrent_runs(self) -> None:
        tool = _CountingClickStub()
        agent = OrchestratorAgent(
            RepeatableToolStreamingEngine(),
            "deepseek-v4-flash",
            tools=[tool],
            loop_guard_config={
                "max_identical_calls": 1,
                "warn_before_block": False,
            },
        )

        results = await asyncio.gather(
            *(_collect_agent_stream(agent, "bấm menu") for _ in range(2))
        )

        assert tool.calls == 2
        assert all(events[-1].result.tool_results[0].success for events in results)

    @pytest.mark.asyncio
    async def test_orchestrator_streams_visible_function_calling_text(self) -> None:
        agent = OrchestratorAgent(
            StreamingEngine(["Xin chào, ", "bạn cần gì?"]),
            "deepseek-v4-flash",
        )

        events = [event async for event in agent.run_stream("chào")]

        assert events[0] == AgentTextDelta("Xin chào, ")
        assert events[1] == AgentTextDelta("bạn cần gì?")
        assert isinstance(events[2], AgentRunCompleted)
        assert events[2].result.content == "Xin chào, bạn cần gì?"

    @pytest.mark.asyncio
    async def test_orchestrator_stream_never_emits_think_or_tool_arguments(
        self,
    ) -> None:
        agent = OrchestratorAgent(
            StreamingEngine(["<thi", "nk>private", "</thi", "nk>", "Câu trả lời."]),
            "deepseek-v4-flash",
        )

        texts = [
            event.content
            async for event in agent.run_stream("help")
            if isinstance(event, AgentTextDelta)
        ]

        assert texts == ["Câu trả lời."]

    @pytest.mark.asyncio
    async def test_visible_text_streams_before_generation_ends(self) -> None:
        """Voice cannot start speaking until the agent hands text over.

        The engine pauses after its one visible chunk, so a run that collects
        deltas and replays them at the end streams nothing here.
        """
        engine = PausingSemanticStreamingEngine()
        agent = OrchestratorAgent(engine, "deepseek-v4-flash")
        deltas: list[str] = []

        async def collect() -> None:
            async for event in agent.run_stream("kể chuyện"):
                if isinstance(event, AgentTextDelta):
                    deltas.append(event.content)

        task = asyncio.create_task(collect())
        try:
            await asyncio.sleep(0.05)
            streamed_early = list(deltas)
            engine.release.set()
            await asyncio.wait_for(task, timeout=2)
        finally:
            engine.release.set()

        assert streamed_early, "no visible text left the agent before generation ended"

    @pytest.mark.asyncio
    async def test_orchestrator_stream_completes_the_round_after_the_delta(
        self,
    ) -> None:
        engine = PausingSemanticStreamingEngine()
        agent = OrchestratorAgent(engine, "deepseek-v4-flash")
        stream = agent.run_stream("help")

        first_event = asyncio.create_task(anext(stream))
        try:
            first = await asyncio.wait_for(first_event, timeout=0.5)
            engine.release.set()
            remaining = [event async for event in stream]
        finally:
            engine.release.set()

        assert first == AgentTextDelta("Visible")
        assert remaining == [
            AgentRunCompleted(
                AgentResult(
                    content="Visible",
                    turns=1,
                    metadata={
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                )
            ),
        ]

    @pytest.mark.asyncio
    async def test_ambiguous_stream_uses_compatibility_before_bare_closing_think_tag(
        self,
    ) -> None:
        class AmbiguousLegacyEngine:
            def __init__(self) -> None:
                self.generate_calls = 0
                self.stream_calls = 0

            def generate(
                self,
                _messages: Sequence[Message],
                **_kwargs: Any,
            ) -> dict[str, Any]:
                self.generate_calls += 1
                return {
                    "content": "private reasoning </think>Visible",
                    "finish_reason": "stop",
                    "usage": {},
                }

            async def stream_full(
                self,
                _messages: Sequence[Message],
                **_kwargs: Any,
            ) -> AsyncIterator[StreamChunk]:
                self.stream_calls += 1
                yield StreamChunk(content="private reasoning ")
                yield StreamChunk(content="</think>Visible")
                yield StreamChunk(finish_reason="stop")

        engine = AmbiguousLegacyEngine()
        events = [
            event
            async for event in OrchestratorAgent(
                engine,  # type: ignore[arg-type]
                "legacy-reasoner",
            ).run_stream("help")
        ]

        assert events[0] == AgentTextDelta("Visible")
        assert isinstance(events[1], AgentRunCompleted)
        assert events[1].result.content == "Visible"
        assert engine.generate_calls == 1
        assert engine.stream_calls == 0

    @pytest.mark.asyncio
    async def test_orchestrator_stream_continues_after_length_finish(self) -> None:
        engine = StreamingEngine(
            [
                [
                    StreamChunk(
                        content="Phần đầu ",
                        finish_reason="length",
                        usage={"prompt_tokens": 2, "completion_tokens": 2},
                    )
                ],
                [
                    StreamChunk(
                        content="phần cuối.",
                        finish_reason="stop",
                        usage={"prompt_tokens": 3, "completion_tokens": 2},
                    )
                ],
            ]
        )

        events = [
            event
            async for event in OrchestratorAgent(
                engine,
                "deepseek-v4-flash",
            ).run_stream("Viết câu đầy đủ")
        ]

        assert [
            event.content for event in events if isinstance(event, AgentTextDelta)
        ] == ["Phần đầu ", "phần cuối."]
        assert len(engine.calls) == 2
        second_messages = engine.calls[1][0]
        assert second_messages[-2:] == [
            Message(role=Role.ASSISTANT, content="Phần đầu "),
            Message(role=Role.USER, content="Continue from where you left off."),
        ]
        assert events[-1] == AgentRunCompleted(
            AgentResult(
                content="Phần đầu phần cuối.",
                turns=1,
                metadata={
                    "prompt_tokens": 5,
                    "completion_tokens": 4,
                    "total_tokens": 9,
                },
            )
        )

    @pytest.mark.asyncio
    async def test_orchestrator_stream_executes_fragmented_tool_call_before_answer(
        self,
    ) -> None:
        class RecordingCalculator(_CalculatorStub):
            def __init__(self) -> None:
                self.arguments: list[dict[str, Any]] = []

            def execute(self, **params: Any) -> ToolResult:
                self.arguments.append(params)
                return super().execute(**params)

        argument = '{"expression":"2+2"}'
        engine = StreamingEngine(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":',
                                },
                            }
                        ]
                    ),
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "function": {
                                    "arguments": '"2+2"}',
                                },
                            }
                        ]
                    ),
                    StreamChunk(
                        finish_reason="tool_calls",
                        usage={"prompt_tokens": 5, "completion_tokens": 3},
                    ),
                ],
                [
                    StreamChunk(content="Kết quả là 4."),
                    StreamChunk(
                        finish_reason="stop",
                        usage={"prompt_tokens": 15, "completion_tokens": 5},
                    ),
                ],
            ]
        )
        tool = RecordingCalculator()
        agent = OrchestratorAgent(
            engine,
            "deepseek-v4-flash",
            tools=[tool],
        )

        events = [event async for event in agent.run_stream("Tính 2+2")]

        deltas = [
            event.content for event in events if isinstance(event, AgentTextDelta)
        ]
        assert tool.arguments == [{"expression": "2+2"}]
        assert len(engine.calls) == 2
        assert all(call[1]["model"] == "deepseek-v4-flash" for call in engine.calls)
        assert len(engine.calls[0][1]["tools"]) == 1
        assert all(argument not in text for text in deltas)
        assert deltas == ["Kết quả là 4."]
        assert isinstance(events[-1], AgentRunCompleted)
        assert sum(isinstance(event, AgentRunCompleted) for event in events) == 1
        assert events[-1].result.content == "Kết quả là 4."
        assert events[-1].result.metadata == {
            "prompt_tokens": 20,
            "completion_tokens": 8,
            "total_tokens": 28,
        }

    @pytest.mark.asyncio
    async def test_orchestrator_stream_keeps_event_loop_live_during_tool_execution(
        self,
    ) -> None:
        tool_started = threading.Event()
        release_tool = threading.Event()

        class BlockingCalculator(_CalculatorStub):
            def __init__(self) -> None:
                self.released_by_heartbeat = False

            def execute(self, **params: Any) -> ToolResult:
                tool_started.set()
                self.released_by_heartbeat = release_tool.wait(timeout=0.2)
                return super().execute(**params)

        engine = StreamingEngine(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":"2+2"}',
                                },
                            }
                        ]
                    ),
                    StreamChunk(finish_reason="tool_calls"),
                ],
                [
                    StreamChunk(content="Kết quả là 4."),
                    StreamChunk(finish_reason="stop"),
                ],
            ]
        )
        tool = BlockingCalculator()
        task = asyncio.create_task(
            _collect_agent_stream(
                OrchestratorAgent(
                    engine,
                    "deepseek-v4-flash",
                    tools=[tool],
                ),
                "Tính 2+2",
            )
        )

        while not tool_started.is_set():
            await asyncio.sleep(0)
        release_tool.set()
        events = await asyncio.wait_for(task, timeout=0.5)

        assert tool.released_by_heartbeat is True
        assert events[-1].result.content == "Kết quả là 4."

    @pytest.mark.asyncio
    async def test_orchestrator_stream_pending_approval_emits_only_completion(
        self,
    ) -> None:
        engine = StreamingEngine(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "approval",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    ),
                    StreamChunk(finish_reason="tool_calls"),
                ]
            ]
        )
        agent = OrchestratorAgent(
            engine,
            "deepseek-v4-flash",
            tools=[_PendingApprovalStub()],
        )

        events = [event async for event in agent.run_stream("Transfer money")]

        # Tool lifecycle events are allowed through — they carry no content.
        # What must never leak before an approval is answer text.
        assert not any(isinstance(event, AgentTextDelta) for event in events)
        assert events[-1] == AgentRunCompleted(
            AgentResult(content="", metadata={"pending_approval": True})
        )

    @pytest.mark.asyncio
    async def test_orchestrator_stream_emits_max_turn_text_as_delta(self) -> None:
        engine = StreamingEngine(
            [
                [
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":"2+2"}',
                                },
                            }
                        ]
                    ),
                    StreamChunk(finish_reason="tool_calls"),
                ]
            ]
        )
        agent = OrchestratorAgent(
            engine,
            "deepseek-v4-flash",
            tools=[_CalculatorStub()],
            max_turns=1,
        )

        events = [event async for event in agent.run_stream("Tính 2+2")]

        text = "Maximum turns reached without a final answer."
        assert events[-2] == AgentTextDelta(text)
        assert events[-1].result.content == text
        assert events[-1].result.metadata["max_turns_exceeded"] is True

    @pytest.mark.asyncio
    async def test_orchestrator_stream_keeps_tool_call_arguments_out_of_the_text(
        self,
    ) -> None:
        """Prose from a tool-call round is streamed, tool arguments are not.

        Withholding that prose used to come free with the end-of-run replay
        that `fix: verify external actions before completion` introduced so it
        could swap the whole answer for a refusal. That feature was reverted;
        the replay it left behind is what kept TTS silent until generation
        ended, so the deltas stream again and this round's prose is spoken.
        The answer itself still excludes it — visible_parts resets per turn.
        """

        class RecordingCalculator(_CalculatorStub):
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, **params: Any) -> ToolResult:
                self.calls += 1
                return super().execute(**params)

        engine = StreamingEngine(
            [
                [
                    StreamChunk(content="Do not mix"),
                    StreamChunk(content=" this answer."),
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":"2+2"}',
                                },
                            }
                        ]
                    ),
                    StreamChunk(finish_reason="tool_calls"),
                ],
                [
                    StreamChunk(content="Result is 4."),
                    StreamChunk(finish_reason="stop"),
                ]
            ]
        )
        tool = RecordingCalculator()
        agent = OrchestratorAgent(
            engine,
            "deepseek-v4-flash",
            tools=[tool],
        )

        events = [event async for event in agent.run_stream("Tính 2+2")]

        deltas = [
            event.content for event in events if isinstance(event, AgentTextDelta)
        ]
        completions = [
            event for event in events if isinstance(event, AgentRunCompleted)
        ]
        assert deltas == ["Do not mix", " this answer.", "Result is 4."]
        assert len(completions) == 1
        assert completions[0].result.content == "Result is 4."
        assert '{"expression":"2+2"}' not in "".join(deltas)
        assert tool.calls == 1

    @pytest.mark.asyncio
    async def test_device_request_without_tool_call_is_no_longer_gated(self) -> None:
        """A claim made without calling any tool is passed through.

        Gating it needed a verifier round trip on every answer, including
        ordinary conversation, which the verifier misjudged often enough to
        reject greetings outright. Claims are now checked only once a mutation
        tool has actually run.
        """
        navigate = _ExternalToolStub(
            "browser_navigate",
            read_only=False,
            outcomes=[True],
        )
        engine = StreamingEngine([_stream_final_round("Mình đã mở YouTube.")])

        events = [
            event
            async for event in OrchestratorAgent(
                engine,
                "deepseek-v4-flash",
                tools=[navigate],
                max_turns=1,
            ).run_stream("mở YouTube")
        ]

        assert [
            event.content for event in events if isinstance(event, AgentTextDelta)
        ] == ["Mình đã mở YouTube."]
        assert "external_action" not in events[-1].result.metadata

    @pytest.mark.asyncio
    async def test_answer_without_tool_calls_skips_the_outcome_verifier(self) -> None:
        navigate = _ExternalToolStub(
            "browser_navigate",
            read_only=False,
            outcomes=[True],
        )
        # One round only: a verifier call would exhaust the engine and raise.
        engine = StreamingEngine([_stream_final_round("Chào bạn.")])

        events = [
            event
            async for event in OrchestratorAgent(
                engine,
                "deepseek-v4-flash",
                tools=[navigate],
            ).run_stream("xin chào")
        ]

        assert [
            event.content for event in events if isinstance(event, AgentTextDelta)
        ] == ["Chào bạn."]

    def test_sync_answer_without_tool_calls_skips_the_outcome_verifier(self) -> None:
        navigate = _ExternalToolStub(
            "browser_navigate",
            read_only=False,
            outcomes=[True],
        )
        engine = MagicMock()
        engine.engine_id = "mock"
        # One round only: a verifier call would exhaust the engine and raise.
        engine.generate.side_effect = [{"content": "Chào bạn.", "tool_calls": []}]

        result = OrchestratorAgent(
            engine,
            "deepseek-v4-flash",
            tools=[navigate],
        ).run("xin chào")

        assert result.content == "Chào bạn."

    @pytest.mark.asyncio
    async def test_orchestrator_stream_instruments_mixed_text_and_tool_call(
        self,
    ) -> None:
        bus = EventBus(record_history=True)
        inner = StreamingEngine(
            [
                [
                    StreamChunk(content="Visible"),
                    StreamChunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "calculator",
                                    "arguments": '{"expression":"2+2"}',
                                },
                            }
                        ]
                    ),
                    StreamChunk(finish_reason="tool_calls"),
                ],
                [
                    StreamChunk(content="Result is 4."),
                    StreamChunk(finish_reason="stop"),
                ]
            ]
        )
        engine = InstrumentedEngine(inner, bus)
        agent = OrchestratorAgent(
            engine,
            "deepseek-v4-flash",
            tools=[_CalculatorStub()],
            bus=bus,
        )

        events = [event async for event in agent.run_stream("Tính 2+2")]

        completions = [
            event for event in events if isinstance(event, AgentRunCompleted)
        ]
        assert len(completions) == 1
        event_types = [event.event_type for event in bus.history]
        assert event_types.count(EventType.INFERENCE_START) == 2
        assert event_types.count(EventType.INFERENCE_END) == 2
        assert event_types.count(EventType.TELEMETRY_RECORD) == 2

    @pytest.mark.asyncio
    async def test_orchestrator_stream_restores_events_for_instrumented_engine(
        self,
    ) -> None:
        bus = EventBus(record_history=True)
        engine = InstrumentedEngine(StreamingEngine(["Visible"]), bus)
        agent = OrchestratorAgent(engine, "deepseek-v4-flash", bus=bus)

        events = [event async for event in agent.run_stream("help")]

        assert isinstance(events[-1], AgentRunCompleted)
        event_types = [event.event_type for event in bus.history]
        assert event_types.count(EventType.INFERENCE_START) == 1
        assert event_types.count(EventType.INFERENCE_END) == 1

    @pytest.mark.asyncio
    async def test_orchestrator_stream_does_not_duplicate_native_stream_events(
        self,
    ) -> None:
        bus = EventBus(record_history=True)
        engine = EventPublishingStreamingEngine(["Visible"], bus)
        agent = OrchestratorAgent(engine, "deepseek-v4-flash", bus=bus)

        events = [event async for event in agent.run_stream("help")]

        assert isinstance(events[-1], AgentRunCompleted)
        event_types = [event.event_type for event in bus.history]
        assert event_types.count(EventType.INFERENCE_START) == 1
        assert event_types.count(EventType.INFERENCE_END) == 1

    def test_agent_id(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model")
        assert agent.agent_id == "orchestrator"

    def test_no_tools_single_turn(self):
        engine = _make_engine_no_tools("Hello!")
        agent = OrchestratorAgent(engine, "test-model")
        result = agent.run("Hello")
        assert result.content == "Hello!"
        assert result.turns == 1
        assert result.tool_results == []

    def test_single_tool_call(self):
        engine = _make_engine_with_tool_call()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        result = agent.run("What is 2+2?")
        assert result.content == "The answer is 4."
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_name == "calculator"
        assert result.tool_results[0].content == "4"

    def test_multiple_tool_calls_same_turn(self):
        engine = _make_engine_multi_tool()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub(), _ThinkStub()],
        )
        result = agent.run("Think and calculate.")
        assert result.content == "Done."
        assert result.turns == 2
        assert len(result.tool_results) == 2

    def test_with_context_conversation(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model")
        conv = Conversation()
        conv.add(Message(role=Role.SYSTEM, content="Be helpful."))
        ctx = AgentContext(conversation=conv)
        agent.run("Hi", context=ctx)
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        assert len(messages) == 2
        assert messages[0].role == Role.SYSTEM

    def test_tools_passed_to_engine(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert "tools" in call_kwargs
        assert len(call_kwargs["tools"]) == 1

    def test_no_tools_no_tools_kwarg(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model")
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert "tools" not in call_kwargs

    def test_max_turns_exceeded(self):
        """When the engine keeps returning tool calls, stop after max_turns."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "calculator", "arguments": '{"expression":"1+1"}'}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        }
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            max_turns=3,
        )
        result = agent.run("Loop forever")
        assert result.turns == 3
        assert result.metadata.get("max_turns_exceeded") is True

    def test_unknown_tool_in_response(self):
        engine = _make_engine_with_tool_call(
            tool_name="unknown_tool",
            arguments="{}",
            final_content="Handled.",
        )
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        result = agent.run("Use unknown tool")
        assert result.content == "Handled."
        assert len(result.tool_results) == 1
        assert result.tool_results[0].success is False

    def test_temperature_passthrough(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model", temperature=0.1)
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["temperature"] == 0.1

    def test_max_tokens_passthrough(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model", max_tokens=256)
        agent.run("Hello")
        call_kwargs = engine.generate.call_args[1]
        assert call_kwargs["max_tokens"] == 256

    def test_event_bus_agent_events(self):
        bus = EventBus(record_history=True)
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model", bus=bus)
        agent.run("Hello")
        event_types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in event_types
        assert EventType.AGENT_TURN_END in event_types

    def test_event_bus_inference_events(self):
        """INFERENCE_START/END are now published by InstrumentedEngine,
        not by agents directly.  Agent tests verify agent-level events."""
        bus = EventBus(record_history=True)
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model", bus=bus)
        agent.run("Hello")
        event_types = [e.event_type for e in bus.history]
        assert EventType.AGENT_TURN_START in event_types
        assert EventType.AGENT_TURN_END in event_types

    def test_event_bus_tool_events(self):
        bus = EventBus(record_history=True)
        engine = _make_engine_with_tool_call()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            bus=bus,
        )
        agent.run("Calc 2+2")
        event_types = [e.event_type for e in bus.history]
        assert EventType.TOOL_CALL_START in event_types
        assert EventType.TOOL_CALL_END in event_types

    def test_messages_accumulate(self):
        """After tool call, messages include assistant + tool messages."""
        engine = _make_engine_with_tool_call()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        agent.run("What is 2+2?")
        # Second call should include accumulated messages
        second_call = engine.generate.call_args_list[1]
        messages = second_call[0][0]
        roles = [m.role for m in messages]
        assert Role.ASSISTANT in roles
        assert Role.TOOL in roles

    def test_tool_message_has_tool_call_id(self):
        engine = _make_engine_with_tool_call(tool_call_id="abc123")
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        agent.run("What is 2+2?")
        second_call = engine.generate.call_args_list[1]
        messages = second_call[0][0]
        tool_msgs = [m for m in messages if m.role == Role.TOOL]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "abc123"

    def test_no_bus_works(self):
        engine = _make_engine_with_tool_call()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        result = agent.run("What is 2+2?")
        assert result.content == "The answer is 4."

    def test_empty_tools_list(self):
        engine = _make_engine_no_tools()
        agent = OrchestratorAgent(engine, "test-model", tools=[])
        result = agent.run("Hello")
        assert result.content == "Final answer."

    def test_three_turn_conversation(self):
        """Engine calls a tool twice before answering."""
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
                    }
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
                "content": "",
                "tool_calls": [
                    {
                        "id": "c2",
                        "name": "calculator",
                        "arguments": '{"expression":"4*3"}',
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 3,
                    "total_tokens": 18,
                },
                "model": "test-model",
                "finish_reason": "tool_calls",
            },
            {
                "content": "2+2=4, 4*3=12",
                "usage": {
                    "prompt_tokens": 25,
                    "completion_tokens": 5,
                    "total_tokens": 30,
                },
                "model": "test-model",
                "finish_reason": "stop",
            },
        ]
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        result = agent.run("Calculate")
        assert result.turns == 3
        assert len(result.tool_results) == 2
        assert result.tool_results[0].content == "4"
        assert result.tool_results[1].content == "12"

    def test_tool_result_latency_tracked(self):
        engine = _make_engine_with_tool_call()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
        )
        result = agent.run("What is 2+2?")
        assert result.tool_results[0].latency_seconds >= 0

    def test_max_turns_1(self):
        """With max_turns=1 and a tool call, should stop after 1 turn."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "calculator", "arguments": '{"expression":"1"}'}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        }
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            max_turns=1,
        )
        result = agent.run("Calc")
        assert result.turns == 1
        assert result.metadata.get("max_turns_exceeded") is True

    def test_agent_turn_end_data_no_tools(self):
        bus = EventBus(record_history=True)
        engine = _make_engine_no_tools("reply")
        agent = OrchestratorAgent(engine, "test-model", bus=bus)
        agent.run("Hi")
        end = [e for e in bus.history if e.event_type == EventType.AGENT_TURN_END][0]
        assert end.data["turns"] == 1
        assert end.data["content_length"] == 5

    def test_result_content_on_max_turns(self):
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {
            "content": "partial",
            "tool_calls": [
                {"id": "c1", "name": "calculator", "arguments": '{"expression":"1"}'}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        }
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            max_turns=2,
        )
        result = agent.run("Calc")
        # Should use the partial content if available
        assert result.content == "partial"


class TestOrchestratorStructuredMode:
    """Tests for the structured (THOUGHT/TOOL/INPUT/FINAL_ANSWER) mode."""

    def test_structured_mode_final_answer(self):
        """Structured mode should parse FINAL_ANSWER: correctly."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {
            "content": "THOUGHT: Easy question.\nFINAL_ANSWER: Paris",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
            "finish_reason": "stop",
        }
        agent = OrchestratorAgent(
            engine,
            "test-model",
            mode="structured",
        )
        result = agent.run("What is the capital of France?")
        assert result.content == "Paris"
        assert result.turns == 1
        assert result.tool_results == []

    def test_structured_mode_tool_call(self):
        """Parse TOOL:/INPUT:, execute tool, return final answer."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            {
                "content": (
                    "THOUGHT: Need to calculate.\n"
                    "TOOL: calculator\n"
                    'INPUT: {"expression":"2+2"}'
                ),
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
                "model": "test-model",
                "finish_reason": "stop",
            },
            {
                "content": ("THOUGHT: Got 4.\nFINAL_ANSWER: The answer is 4."),
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
                "model": "test-model",
                "finish_reason": "stop",
            },
        ]
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            mode="structured",
        )
        result = agent.run("What is 2+2?")
        assert result.content == "The answer is 4."
        assert result.turns == 2
        assert len(result.tool_results) == 1
        assert result.tool_results[0].tool_name == "calculator"
        assert result.tool_results[0].content == "4"

    def test_structured_mode_enriched_descriptions(self):
        """Structured mode system prompt should contain enriched tool descriptions."""
        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.return_value = {
            "content": "FINAL_ANSWER: ok",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "test-model",
            "finish_reason": "stop",
        }
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            mode="structured",
        )
        agent.run("Hello")
        call_args = engine.generate.call_args
        messages = call_args[0][0]
        system_msg = messages[0].content
        assert "### calculator" in system_msg
        assert "expression" in system_msg


class TestOrchestratorParallelTools:
    """Tests for parallel tool execution."""

    def test_parallel_tool_execution(self):
        """Multiple tool calls execute in parallel and return in correct order."""
        import time

        class _SlowTool(BaseTool):
            tool_id = "slow"

            @property
            def spec(self) -> ToolSpec:
                return ToolSpec(
                    name="slow",
                    description="Slow tool.",
                    parameters={
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                    },
                )

            def execute(self, **params) -> ToolResult:
                time.sleep(0.1)  # Simulate slow operation
                return ToolResult(
                    tool_name="slow",
                    content=f"result_{params.get('id', '')}",
                    success=True,
                )

        engine = MagicMock()
        engine.engine_id = "mock"
        engine.generate.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "slow", "arguments": '{"id":"1"}'},
                    {"id": "c2", "name": "slow", "arguments": '{"id":"2"}'},
                    {"id": "c3", "name": "slow", "arguments": '{"id":"3"}'},
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
                "content": "All done.",
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 3,
                    "total_tokens": 23,
                },
                "model": "test-model",
                "finish_reason": "stop",
            },
        ]

        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_SlowTool()],
            parallel_tools=True,
        )
        t0 = time.time()
        result = agent.run("Do things")
        elapsed = time.time() - t0

        assert result.content == "All done."
        assert len(result.tool_results) == 3
        # Results should be in original order
        assert result.tool_results[0].content == "result_1"
        assert result.tool_results[1].content == "result_2"
        assert result.tool_results[2].content == "result_3"
        # Should be parallel — 3 tools at 0.1s each should take < 0.25s, not 0.3s+
        assert elapsed < 0.25

    def test_sequential_tool_execution(self):
        """parallel_tools=False runs tools sequentially."""
        engine = _make_engine_multi_tool()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub(), _ThinkStub()],
            parallel_tools=False,
        )
        result = agent.run("Do things")
        assert result.content == "Done."
        assert len(result.tool_results) == 2

    def test_single_tool_call_no_parallel(self):
        """Single tool call should not use parallel path even if parallel_tools=True."""
        engine = _make_engine_with_tool_call()
        agent = OrchestratorAgent(
            engine,
            "test-model",
            tools=[_CalculatorStub()],
            parallel_tools=True,
        )
        result = agent.run("What is 2+2?")
        assert result.content == "The answer is 4."


class _RecordingFunctionCallingEngine:
    """Records the messages of every function-calling request."""

    def __init__(self) -> None:
        self.requests: list[Sequence[Message]] = []

    def generate(self, messages: Sequence[Message], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self.requests.append(list(messages))
        return {"content": "Đã xác minh trạng thái Saved.", "usage": {}}

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        del model
        return False


class TestBrowserSystemPromptPlumbing:
    """``system_prompt`` must reach the model in both function-calling modes."""

    BROWSER_PROMPT = "Observe with browser_snapshot before acting."
    VOICE_SYSTEM_PROMPT = "Trả lời ngắn gọn để đọc thành tiếng."

    def _voice_context(self) -> AgentContext:
        conversation = Conversation()
        conversation.add(
            Message(role=Role.SYSTEM, content=self.VOICE_SYSTEM_PROMPT)
        )
        return AgentContext(conversation=conversation)

    def test_sync_run_prepends_the_agent_system_prompt(self) -> None:
        engine = _RecordingFunctionCallingEngine()
        agent = OrchestratorAgent(engine, "model", system_prompt=self.BROWSER_PROMPT)
        agent.run("mở trang nhân sự", self._voice_context())
        assert engine.requests[0][:2] == [
            Message(role=Role.SYSTEM, content=self.BROWSER_PROMPT),
            Message(role=Role.SYSTEM, content=self.VOICE_SYSTEM_PROMPT),
        ]

    def test_sync_run_without_voice_context_has_one_system_message(self) -> None:
        engine = _RecordingFunctionCallingEngine()
        agent = OrchestratorAgent(engine, "model", system_prompt=self.BROWSER_PROMPT)
        agent.run("mở trang nhân sự")
        systems = [m for m in engine.requests[0] if m.role == Role.SYSTEM]
        assert systems == [Message(role=Role.SYSTEM, content=self.BROWSER_PROMPT)]

    @pytest.mark.asyncio
    async def test_streaming_run_prepends_the_agent_system_prompt(self) -> None:
        engine = StreamingEngine(["ok"])
        agent = OrchestratorAgent(engine, "model", system_prompt=self.BROWSER_PROMPT)
        async for _ in agent.run_stream("mở trang nhân sự", self._voice_context()):
            pass
        messages = engine.calls[0][0]
        assert list(messages)[:2] == [
            Message(role=Role.SYSTEM, content=self.BROWSER_PROMPT),
            Message(role=Role.SYSTEM, content=self.VOICE_SYSTEM_PROMPT),
        ]

    @pytest.mark.asyncio
    async def test_streaming_run_without_prompt_keeps_voice_context_first(
        self,
    ) -> None:
        engine = StreamingEngine(["ok"])
        agent = OrchestratorAgent(engine, "model")
        async for _ in agent.run_stream("mở trang nhân sự", self._voice_context()):
            pass
        messages = list(engine.calls[0][0])
        assert messages[0] == Message(
            role=Role.SYSTEM, content=self.VOICE_SYSTEM_PROMPT
        )
