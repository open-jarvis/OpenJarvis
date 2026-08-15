"""The OpenJarvis native Agent, as a Pipecat LLM service."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any, Literal

from pipecat.frames.frames import (
    Frame,
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

    Every delta is pushed the moment it arrives. Collecting them first would
    keep TTS silent until generation ended, which is the latency defect this
    runtime exists to remove.
    """

    def __init__(
        self,
        binding: Any,
        *,
        recall: tuple[Any, Any] | None = None,
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

    async def stream_agent(
        self, prompt: str, context: AgentContext
    ) -> AsyncGenerator[Frame, None]:
        """Yield the Agent's visible text as Pipecat frames, unbuffered.

        Each delta is projected into speech text before it leaves: the Agent
        answers the screen (markdown, bullet lists, emoji), and the VieNeu
        voice would read the syntax out loud. The projector holds back
        incomplete markdown so a partial ``**bo`` never reaches TTS, and
        flushes the remainder at the end of the response.
        """
        projector = _SpeechProjector()
        yield voice_activity_frame("inference", model=self._binding.model)
        async for event in self._binding.run_stream(prompt, context):
            if isinstance(event, AgentToolStarted):
                yield voice_activity_frame("tool", tool_name=event.tool_name)
            elif isinstance(event, AgentToolFinished):
                yield voice_activity_frame("inference", model=self._binding.model)
            if isinstance(event, AgentTextDelta):
                speech = projector.push(event.content)
                if speech:
                    yield LLMTextFrame(speech)
        speech = projector.finish()
        if speech:
            yield LLMTextFrame(speech)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Answer an aggregated context, or pass the frame along."""
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

        try:
            await self.push_frame(voice_activity_frame("processing"))
            await self.push_frame(LLMFullResponseStartFrame())
            await self.start_processing_metrics()
            async for pushed in self.stream_agent(prompt, context):
                await self.push_frame(pushed)
        except Exception as error:  # noqa: BLE001 - surfaced as a pipeline error frame
            await self.push_error(
                error_msg=f"Error during completion: {error}", exception=error
            )
        finally:
            await self.stop_processing_metrics()
            # In a finally, so an interruption that cancels generation still
            # closes the response and does not strand the aggregator.
            await self.push_frame(LLMFullResponseEndFrame())
