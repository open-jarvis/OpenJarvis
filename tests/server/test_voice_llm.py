"""Voice-only projection of native Agent stream events."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pipecat", reason="openjarvis[voice] not installed")

from pipecat.frames.frames import (
    EndFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.workers.runner import WorkerRunner

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    AgentRunCompleted,
    AgentTextDelta,
    AgentToolFinished,
    AgentToolStarted,
)
from openjarvis.server.voice.audio import RealtimeTtsChunk
from openjarvis.server.voice.llm import OpenJarvisLLMService, agent_input
from openjarvis.server.voice.tts import VieNeuTTSService

# How long a step of a driven turn may take before the test calls it hung.
# Generous on purpose: pipecat 1.8.1 needs ~0.3 s longer than 1.7.0 to bring a
# pipeline up, which is enough to push a 0.5 s budget over on a loaded machine.
# These bound a hang, they do not assert latency — tighten only with a measured
# reason to.
_STEP_TIMEOUT_S = 2.0
_TURN_TIMEOUT_S = 10.0


def test_voice_recall_uses_current_skill_registry(tmp_path):
    from types import SimpleNamespace

    from openjarvis.core.events import EventBus
    from openjarvis.server.voice.runtime import _memory_recall
    from openjarvis.skills.manager import SkillManager
    from openjarvis.tools.skill_manage import SkillManageTool
    from openjarvis.tools.storage._stubs import RetrievalResult

    manager = SkillManager(EventBus(), overlay_dir=tmp_path / "overlays")
    skill = SkillManageTool(skills_dir=tmp_path / "skills", skill_manager=manager)
    memory = SimpleNamespace(retrieve=lambda *args, **kwargs: [
        RetrievalResult(
            content="Use known-read", source="openjarvis.skill_learning",
            metadata={"skill_name": "known-read"},
        ),
    ])
    config = SimpleNamespace(
        agent=SimpleNamespace(context_from_memory=True),
        memory=SimpleNamespace(
            context_top_k=5, context_min_score=0, context_max_tokens=2048,
        ),
    )
    recall = _memory_recall(memory, config, agent=SimpleNamespace(_tools=[skill]))
    pipecat_context = LLMContext([{"role": "user", "content": "menu"}])
    _, before = agent_input(pipecat_context, recall)
    assert not any("known-read" in m.text for m in before.conversation.messages)
    assert skill.execute(
        action="create", name="known-read", steps=[{"tool_name": "http_request"}],
    ).success
    # The same active session sees newly registered skills, not a stale snapshot.
    _, after = agent_input(pipecat_context, recall)
    assert any("known-read" in m.text for m in after.conversation.messages)


class _Binding:
    model = "test-model"

    def __init__(self, events, *, first_event_after: float = 0.0):
        self._events = events
        self._first_event_after = first_event_after
        self.closed = False

    async def run_stream(self, prompt, context):
        del prompt, context
        try:
            if self._first_event_after:
                await asyncio.sleep(self._first_event_after)
            for event in self._events:
                yield event
        finally:
            self.closed = True


class _BlockingBinding:
    model = "test-model"

    def __init__(self):
        self.waiting = asyncio.Event()
        self.closed = False

    async def run_stream(self, prompt, context):
        del context
        if prompt != "turn cũ":
            yield AgentTextDelta("fresh response.")
            return
        try:
            yield AgentTextDelta("stale partial ")
            self.waiting.set()
            await asyncio.Event().wait()
        finally:
            self.closed = True


class _ErrorThenSuccessBinding:
    model = "test-model"

    def __init__(self):
        self.failed = asyncio.Event()

    async def run_stream(self, prompt, context):
        del context
        if prompt == "turn lỗi":
            yield AgentTextDelta("stale partial ")
            self.failed.set()
            raise RuntimeError("expected test failure")
        yield AgentTextDelta("fresh response.")


class _RecordingRenderer:
    def __init__(self):
        self.requests = []
        self.called = asyncio.Event()

    async def stream_tts(self, text):
        self.requests.append(text)
        self.called.set()
        yield RealtimeTtsChunk(
            audio=b"\x00\x00" * 480,
            provider="local",
            encoding="pcm_s16le",
            sample_rate_hz=48_000,
            channels=1,
        )


class _PipecatContext:
    def __init__(self, messages):
        self._messages = messages

    def get_messages(self):
        return self._messages


async def _speech(events, *, first_event_after: float = 0.0) -> str:
    service = OpenJarvisLLMService(
        _Binding(events, first_event_after=first_event_after)
    )
    frames = [
        frame
        async for frame in service.stream_agent("đặt món", AgentContext())
        if isinstance(frame, LLMTextFrame)
    ]
    return "".join(frame.text for frame in frames)


def test_agent_input_preserves_consecutive_user_turns():
    prompt, context = agent_input(
        _PipecatContext(
            [
                {"role": "user", "content": "xin chào"},
                {"role": "assistant", "content": "xin chào bạn"},
                {"role": "user", "content": "quay lại menu"},
                {"role": "user", "content": "bạn có nghe không"},
                {"role": "user", "content": "tìm món liên quan tới trứng"},
            ]
        )
    )

    assert prompt == "tìm món liên quan tới trứng"
    assert [
        (message.role.value, message.text)
        for message in context.conversation.messages[1:]
    ] == [
        ("user", "xin chào"),
        ("assistant", "xin chào bạn"),
        ("user", "quay lại menu"),
        ("user", "bạn có nghe không"),
    ]


@pytest.mark.anyio
async def test_interruption_does_not_flush_cancelled_response_into_tts():
    binding = _BlockingBinding()
    renderer = _RecordingRenderer()
    llm = OpenJarvisLLMService(binding)
    pipeline = Pipeline([llm, VieNeuTTSService(renderer, sample_rate=48_000)])
    worker = PipelineWorker(
        pipeline,
        cancel_on_idle_timeout=False,
        enable_rtvi=False,
        enable_turn_tracking=False,
    )
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)

    async def drive_turn():
        await asyncio.sleep(0.01)
        await worker.queue_frame(
            LLMContextFrame(
                LLMContext(messages=[{"role": "user", "content": "turn cũ"}])
            )
        )
        await asyncio.wait_for(binding.waiting.wait(), timeout=_STEP_TIMEOUT_S)
        await worker.queue_frame(InterruptionFrame())
        await worker.queue_frame(
            LLMContextFrame(
                LLMContext(messages=[{"role": "user", "content": "turn mới"}])
            )
        )
        await asyncio.wait_for(renderer.called.wait(), timeout=_STEP_TIMEOUT_S)
        await worker.queue_frame(EndFrame())

    await runner.add_workers(worker)
    await asyncio.wait_for(
        asyncio.gather(runner.run(), drive_turn()),
        timeout=_TURN_TIMEOUT_S,
    )

    assert binding.closed
    assert renderer.requests == ["fresh response."]


@pytest.mark.anyio
async def test_completed_response_still_flushes_into_tts():
    renderer = _RecordingRenderer()
    llm = OpenJarvisLLMService(_Binding([AgentTextDelta("fresh response.")]))
    pipeline = Pipeline([llm, VieNeuTTSService(renderer, sample_rate=48_000)])
    worker = PipelineWorker(
        pipeline,
        cancel_on_idle_timeout=False,
        enable_rtvi=False,
        enable_turn_tracking=False,
    )
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)

    async def drive_turn():
        await asyncio.sleep(0.01)
        await worker.queue_frame(
            LLMContextFrame(
                LLMContext(messages=[{"role": "user", "content": "turn mới"}])
            )
        )
        await asyncio.wait_for(renderer.called.wait(), timeout=_STEP_TIMEOUT_S)
        await worker.queue_frame(EndFrame())

    await runner.add_workers(worker)
    await asyncio.wait_for(
        asyncio.gather(runner.run(), drive_turn()),
        timeout=_TURN_TIMEOUT_S,
    )

    assert renderer.requests == ["fresh response."]


@pytest.mark.anyio
async def test_failed_response_discards_partial_text_before_the_next_turn():
    binding = _ErrorThenSuccessBinding()
    renderer = _RecordingRenderer()
    llm = OpenJarvisLLMService(binding)
    pipeline = Pipeline([llm, VieNeuTTSService(renderer, sample_rate=48_000)])
    worker = PipelineWorker(
        pipeline,
        cancel_on_idle_timeout=False,
        enable_rtvi=False,
        enable_turn_tracking=False,
    )
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)

    async def drive_turns():
        await asyncio.sleep(0.01)
        await worker.queue_frame(
            LLMContextFrame(
                LLMContext(messages=[{"role": "user", "content": "turn lỗi"}])
            )
        )
        await asyncio.wait_for(binding.failed.wait(), timeout=_STEP_TIMEOUT_S)
        await worker.queue_frame(
            LLMContextFrame(
                LLMContext(messages=[{"role": "user", "content": "turn mới"}])
            )
        )
        await asyncio.wait_for(renderer.called.wait(), timeout=_STEP_TIMEOUT_S)
        await worker.queue_frame(EndFrame())

    await runner.add_workers(worker)
    await asyncio.wait_for(
        asyncio.gather(runner.run(), drive_turns()),
        timeout=_TURN_TIMEOUT_S,
    )

    assert renderer.requests == ["fresh response."]


@pytest.mark.anyio
async def test_voice_speaks_the_first_tool_round_and_final_answer_only():
    speech = await _speech(
        [
            AgentTextDelta("Dạ, em đang tạo đơn. "),
            AgentToolStarted("http_request"),
            AgentToolFinished("http_request", ok=True),
            AgentTextDelta("Đơn đã tạo xong. "),
            AgentToolStarted("http_request"),
            AgentToolFinished("http_request", ok=True),
            AgentTextDelta("Đơn đã được xác minh. "),
            AgentToolStarted("display_bill"),
            AgentToolFinished("display_bill", ok=True),
            AgentTextDelta("Đơn của bạn đã sẵn sàng."),
            AgentRunCompleted(AgentResult(content="Đơn của bạn đã sẵn sàng.", turns=4)),
        ]
    )

    assert speech == "Dạ, em đang tạo đơn. Đơn của bạn đã sẵn sàng."


@pytest.mark.anyio
async def test_voice_keeps_streaming_a_turn_that_does_not_use_tools():
    speech = await _speech(
        [
            AgentTextDelta("Xin chào "),
            AgentTextDelta("bạn."),
            AgentRunCompleted(AgentResult(content="Xin chào bạn.", turns=1)),
        ]
    )

    assert speech == "Xin chào bạn."


@pytest.mark.anyio
async def test_voice_does_not_repeat_a_terminal_display_round():
    speech = await _speech(
        [
            AgentTextDelta("Menu đang ở trên màn hình."),
            AgentToolStarted("display_menu"),
            AgentToolFinished("display_menu", ok=True),
            AgentRunCompleted(
                AgentResult(content="Menu đang ở trên màn hình.", turns=1)
            ),
        ]
    )

    assert speech.strip() == "Menu đang ở trên màn hình."


@pytest.mark.anyio
async def test_voice_does_not_inject_a_hardcoded_reply_into_a_slow_turn():
    speech = await _speech(
        [
            AgentToolStarted("http_request"),
            AgentToolFinished("http_request", ok=True),
            AgentTextDelta("Dạ, em nghe bạn nói rõ ạ."),
            AgentRunCompleted(
                AgentResult(content="Dạ, em nghe bạn nói rõ ạ.", turns=2)
            ),
        ],
        first_event_after=1.6,
    )

    assert speech == "Dạ, em nghe bạn nói rõ ạ."


@pytest.mark.anyio
async def test_voice_stays_quiet_when_the_turn_speaks_straight_away():
    speech = await _speech(
        [
            AgentTextDelta("Xin chào bạn."),
            AgentRunCompleted(AgentResult(content="Xin chào bạn.", turns=1)),
        ]
    )

    assert speech == "Xin chào bạn."


@pytest.mark.anyio
async def test_cancellation_during_frame_delivery_closes_binding(monkeypatch):
    binding = _Binding([AgentTextDelta("hello there "), AgentTextDelta("later")])
    service = OpenJarvisLLMService(binding)
    delivering = asyncio.Event()

    async def blocked_delivery(frame, *args, **kwargs):
        if isinstance(frame, LLMTextFrame):
            delivering.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(service, "push_frame", blocked_delivery)
    task = asyncio.create_task(
        service.process_frame(
            LLMContextFrame(
                LLMContext(messages=[{"role": "user", "content": "hello"}])
            ),
            FrameDirection.DOWNSTREAM,
        )
    )
    await asyncio.wait_for(delivering.wait(), 0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert binding.closed


@pytest.mark.anyio
async def test_voice_consumer_close_immediately_closes_suspended_binding():
    binding = _Binding([AgentTextDelta("xin chào. "), AgentTextDelta("later")])
    service = OpenJarvisLLMService(binding)
    stream = service.stream_agent("hello", AgentContext())
    while True:
        frame = await anext(stream)
        if isinstance(frame, LLMTextFrame):
            break
    await stream.aclose()
    assert binding.closed


@pytest.mark.anyio
async def test_voice_barge_in_mid_round_releases_the_agent_stream():
    """Interruption cancels the consumer; the parked round must not be left running."""
    binding = _Binding([AgentTextDelta("quá muộn")], first_event_after=30.0)
    service = OpenJarvisLLMService(binding)
    stream = service.stream_agent("dừng lại", AgentContext())

    async def consume():
        async for _ in stream:
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    await asyncio.sleep(0)
    assert binding.closed
