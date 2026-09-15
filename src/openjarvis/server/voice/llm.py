"""The OpenJarvis native Agent, as a Pipecat LLM service."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any, Literal

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from openjarvis.agents._stubs import (
    AgentContext,
    AgentTextDelta,
    AgentToolFinished,
    AgentToolStarted,
)
from openjarvis.core.types import Conversation, Message, Role
from openjarvis.server.voice.runtime import VOICE_SYSTEM_PROMPT
from openjarvis.server.voice.text import normalize_speech_text

logger = logging.getLogger("openjarvis.server.voice")


class VoiceTurnState:
    """Session-local generation identity used to fence interrupted turns."""

    def __init__(self) -> None:
        self._active_turn_id: int | None = None
        self.turn_id = 0

    @property
    def active_turn_id(self) -> int | None:
        return self._active_turn_id

    def begin_turn(self) -> int:
        self.turn_id += 1
        self._active_turn_id = self.turn_id
        return self.turn_id

    def interrupt(self) -> None:
        self._active_turn_id = None

    def is_active(self, turn_id: int) -> bool:
        return self._active_turn_id == turn_id


def message_text(message: Any) -> str:
    """Read the text out of one Pipecat context message.

    Content is a plain string for text turns and a list of parts once images or
    audio are involved; only the text parts mean anything to the Agent.
    """
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


class _SpeechProjector:
    """Strip markdown from a stream while preserving word boundaries.

    normalize_speech_text removes presentation syntax but also trims each
    call's edges, so calling it per token would eat the spaces between words
    ("Xin chào" -> "Xinchào"). Instead the trailing word is held back and
    only emitted once the next token proves it is complete, so every emitted
    piece ends at a word boundary and the spaces survive. An unfinished
    delimiter can only leak if it spans several words unclosed, which the
    Agent does not do.
    """

    def __init__(self) -> None:
        self._raw = ""
        self._emitted = ""

    def push(self, text: str) -> str | None:
        self._raw += text
        normalized = normalize_speech_text(self._raw)
        if not normalized.startswith(self._emitted):
            # normalize_speech_text re-parses the whole buffer, so text already
            # spoken can change shape as the markdown around it completes —
            # markdown-it appends a "." to a heading or list item, and that "."
            # moves as the item grows. Resync to the same offset. Resetting to
            # zero instead re-emits the buffer from its first word, which in
            # one measured response spoke the same answer 13 times.
            self._emitted = normalized[: len(self._emitted)]
        candidate = normalized[len(self._emitted) :]
        last_space = candidate.rfind(" ")
        if last_space == -1:
            return None
        stable = candidate[: last_space + 1]
        self._emitted += stable
        return stable

    def finish(self) -> str | None:
        normalized = normalize_speech_text(self._raw)
        tail = normalized[len(self._emitted) :]
        self._raw = ""
        self._emitted = ""
        return tail or None


def agent_input(
    context: Any,
    recall: tuple[Any, Any] | None = None,
) -> tuple[str, AgentContext]:
    """Split a Pipecat context into the Agent's prompt and its history.

    The Agent takes the latest user turn as its input and everything before it
    as conversation history, which is how every other OpenJarvis caller invokes
    it. When ``recall`` is given it is ``(backend, ContextConfig)`` and the
    same passages the chat path retrieves are prepended to the history.
    """
    messages = list(context.get_messages())
    prompt = ""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            prompt = message_text(messages[index])
            messages = messages[:index]
            break

    history = [
        Message(role=Role(role), content=message_text(message))
        for message in messages
        if (role := message.get("role")) in Role._value2member_map_
    ]

    if recall is not None and prompt:
        backend, ctx_cfg = recall
        try:
            from openjarvis.tools.storage import context as context_module

            history = context_module.inject_context(
                prompt, history, backend, config=ctx_cfg
            )
        except Exception:
            # Recall is an enhancement; a dead memory backend must not cost
            # the user their answer.
            logger.warning("voice memory recall failed", exc_info=True)

    # The Agent answers screens by default: markdown, tables, numbered lists.
    # Spoken aloud that is syntax read out, and the projector has to strip it
    # after the fact. Telling the Agent it is speaking stops the markdown
    # being produced at all. inject_context prepends its own message, so this
    # must go on *after* recall runs — otherwise the recalled document lands
    # ahead of the instruction that says how to speak it.
    history = [Message(role=Role.SYSTEM, content=VOICE_SYSTEM_PROMPT), *history]

    return prompt, AgentContext(conversation=Conversation(messages=history))


def voice_activity_frame(
    phase: Literal["processing", "inference", "tool"],
    *,
    model: str | None = None,
    tool_name: str | None = None,
) -> OutputTransportMessageUrgentFrame:
    activity: dict[str, str] = {"type": "voice_activity", "phase": phase}
    if phase == "inference" and model:
        activity["model"] = model
    if phase == "tool" and tool_name:
        activity["tool_name"] = tool_name
    return OutputTransportMessageUrgentFrame(
        {"label": "rtvi-ai", "type": "server-message", "data": {"data": activity}}
    )


class OpenJarvisLLMService(LLMService):
    """Answer through the native Agent, which owns tools, memory, and policy.

    The first round streams immediately so TTS can acknowledge the turn early.
    After a tool starts, later rounds are buffered until they prove final; this
    keeps tool-loop drafts from being spoken as repeated answers.
    """

    def __init__(
        self,
        binding: Any,
        *,
        recall: tuple[Any, Any] | None = None,
        turn_state: VoiceTurnState | None = None,
        **kwargs: Any,
    ) -> None:
        # None, not unset: every field left NOT_GIVEN makes pipecat log an
        # ERROR at session start. The Agent owns every one of these knobs, so
        # the service itself has none to set.
        kwargs.setdefault(
            "settings",
            LLMSettings(
                model=None,
                system_instruction=None,
                temperature=None,
                max_tokens=None,
                top_p=None,
                top_k=None,
                frequency_penalty=None,
                presence_penalty=None,
                seed=None,
                filter_incomplete_user_turns=False,
                user_turn_completion_config=None,
            ),
        )
        super().__init__(**kwargs)
        self._binding = binding
        self._recall = recall
        self._turn_state = turn_state or VoiceTurnState()

    async def stream_agent(
        self,
        prompt: str,
        context: AgentContext,
        *,
        turn_id: int | None = None,
    ) -> AsyncGenerator[Frame, None]:
        """Yield the first round immediately and only the final later round.

        Each delta is projected into speech text before it leaves: the Agent
        answers the screen (markdown, bullet lists, emoji), and the VieNeu
        voice would read the syntax out loud. The projector holds back
        incomplete markdown so a partial ``**bo`` never reaches TTS, and
        flushes the remainder at a tool boundary or the end of the response.
        """
        projector = _SpeechProjector()
        tool_round_started = False
        later_round: list[str] = []
        if turn_id is None:
            turn_id = self._turn_state.begin_turn()
        yield voice_activity_frame("inference", model=self._binding.model)
        stream = self._binding.run_stream(prompt, context)
        # Consume in one Task so run/worker ContextVars remain attached across
        # yields. Closing the outer stream also closes its suspended binding.
        async with aclosing(stream):
            async for event in stream:
                if not self._turn_state.is_active(turn_id):
                    return

                if isinstance(event, AgentToolStarted):
                    if tool_round_started:
                        # This buffered narration belongs to another intermediate
                        # tool round. The customer already heard the first round;
                        # speaking every draft is what repeated the same order.
                        later_round.clear()
                    else:
                        speech = projector.finish()
                        if speech:
                            yield LLMTextFrame(f"{speech} ")
                        tool_round_started = True
                    yield voice_activity_frame("tool", tool_name=event.tool_name)
                elif isinstance(event, AgentToolFinished):
                    yield voice_activity_frame("inference", model=self._binding.model)
                if isinstance(event, AgentTextDelta):
                    if tool_round_started:
                        later_round.append(event.content)
                    else:
                        speech = projector.push(event.content)
                        if speech:
                            yield LLMTextFrame(speech)
        if tool_round_started:
            projector = _SpeechProjector()
            for content in later_round:
                speech = projector.push(content)
                if speech:
                    yield LLMTextFrame(speech)
        speech = projector.finish()
        if speech:
            yield LLMTextFrame(speech)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Answer an aggregated context, or pass the frame along."""
        if isinstance(frame, InterruptionFrame):
            # Invalidate the generation before Pipecat cancels the process task.
            # Any custom iterator cleanup that races with cancellation can then
            # no longer emit frames for the interrupted turn.
            self._turn_state.interrupt()
        # First: the base class routes InterruptionFrame to
        # _handle_interruptions, which cancels in-flight tool calls. Skipping
        # it would lose barge-in while the Agent is inside a tool.
        await super().process_frame(frame, direction)

        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return

        prompt, context = agent_input(frame.context, self._recall)
        if not prompt:
            return
        turn_id = self._turn_state.begin_turn()

        completed = False
        try:
            await self.push_frame(voice_activity_frame("processing"))
            await self.push_frame(LLMFullResponseStartFrame())
            await self.start_processing_metrics()
            response = self.stream_agent(prompt, context, turn_id=turn_id)
            async with aclosing(response):
                async for pushed in response:
                    if not self._turn_state.is_active(turn_id):
                        break
                    if isinstance(pushed, LLMTextFrame):
                        # Pipecat system-frame interruption can overtake queued
                        # text. Recheck ownership when TTS consumes that text,
                        # not only when it is enqueued here.
                        pushed.metadata["openjarvis_is_current"] = (
                            lambda turn_id=turn_id: self._turn_state.is_active(turn_id)
                        )
                    await self.push_frame(pushed)
            completed = self._turn_state.is_active(turn_id)
        except Exception as error:  # noqa: BLE001 - surfaced as a pipeline error frame
            self._turn_state.interrupt()
            await self.push_error(
                error_msg=f"Error during completion: {error}", exception=error
            )
            # This response did not complete, so reset downstream aggregation
            # instead of flushing its partial text as a successful reply.
            await self.push_frame(InterruptionFrame())
        finally:
            await self.stop_processing_metrics()
        if completed:
            await self.push_frame(LLMFullResponseEndFrame())
