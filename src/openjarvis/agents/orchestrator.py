"""OrchestratorAgent — multi-turn agent with tool-calling loop.

Supports two modes:

- **function_calling** (default): Uses OpenAI-format tool definitions and
  parses ``tool_calls`` from the engine response.
- **structured**: Uses a THOUGHT/TOOL/INPUT/FINAL_ANSWER text format
  (like ReAct) with a canonical system prompt from the orchestrator
  prompt registry.  This is the format used by the SFT/GRPO training
  pipelines, making the Orchestrator a distinctive trainable agent type.
"""

from __future__ import annotations

import concurrent.futures
import re
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any, List, Optional

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    AgentRunCompleted,
    AgentStreamEvent,
    AgentTextDelta,
    AgentToolFinished,
    AgentToolStarted,
    ToolUsingAgent,
    run_agent_sync_worker,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine, merge_tool_call_fragments
from openjarvis.tools._stubs import BaseTool


@AgentRegistry.register("orchestrator")
class OrchestratorAgent(ToolUsingAgent):
    """Multi-turn agent that routes between tools and the LLM.

    Implements a tool-calling loop:
    1. Send messages with tool definitions to the engine.
    2. If the response contains tool_calls, execute them and loop.
    3. If no tool_calls, return the final answer.
    4. Stop after ``max_turns`` iterations.

    In **structured** mode the agent instead uses a
    ``THOUGHT: / TOOL: / INPUT: / FINAL_ANSWER:`` text protocol
    identical to the format used by the orchestrator SFT/GRPO
    training pipelines.
    """

    agent_id = "orchestrator"
    _default_temperature = 0.7
    _default_max_tokens = 1024
    _default_max_turns = 10

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mode: str = "function_calling",
        system_prompt: Optional[str] = None,
        prompt_builder: Optional[Any] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
        loop_guard_config: Optional[Any] = None,
        capability_policy: Any = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
            prompt_builder=prompt_builder,
            loop_guard_config=loop_guard_config,
            capability_policy=capability_policy,
        )
        self._mode = mode
        self._system_prompt = system_prompt
        self._parallel_tools = parallel_tools

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if self._mode == "structured":
            return self._run_structured(input, context, **kwargs)
        return self._run_function_calling(input, context, **kwargs)

    async def run_stream(
        self,
        input: str,
        context: AgentContext | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AgentStreamEvent]:
        if self._mode == "structured":
            async for event in super().run_stream(input, context, **kwargs):
                yield event
            return

        # One agent instance serves every caller, so the model for this run is
        # a local — never an attribute swap, which a concurrent run would see.
        model = kwargs.pop("model", None) or self._model

        supports_semantic_reasoning = getattr(
            self._engine,
            "supports_semantic_reasoning_stream",
            None,
        )
        if not callable(supports_semantic_reasoning) or not bool(
            supports_semantic_reasoning(model)
        ):
            async for event in super().run_stream(
                input, context, model=model, **kwargs
            ):
                yield event
            return

        self._emit_turn_start(input)
        loop_guard = self._new_loop_guard()
        messages = self._build_messages(
            input,
            context,
            system_prompt=self._system_prompt,
        )
        openai_tools = self._executor.get_openai_tools() if self._tools else []
        all_tool_results: list[ToolResult] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for turns in range(1, self._max_turns + 1):
            if loop_guard:
                messages = loop_guard.compress_context(messages)

            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            visible_parts: list[str] = []
            continuations = 0

            while True:
                tool_call_fragments: dict[int, dict[str, Any]] = {}
                visible_text_filter = _VisibleTextFilter()
                round_content: list[str] = []
                finish_reason = ""
                round_usage: dict[str, Any] = {}

                self._emit_stream_inference_start(model=model)
                stream = self._engine.stream_full(
                    messages,
                    model=model,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    **(gen_kwargs if continuations == 0 else {}),
                )
                async with aclosing(stream):
                    async for chunk in stream:
                        if chunk.tool_calls:
                            merge_tool_call_fragments(
                                tool_call_fragments,
                                chunk.tool_calls,
                            )
                        if chunk.content:
                            round_content.append(chunk.content)
                            for visible in visible_text_filter.feed(chunk.content):
                                visible_parts.append(visible)
                                # Handed over here, not replayed at the end:
                                # TTS cannot start speaking until it has text,
                                # so collecting first costs a full generation
                                # of silence.
                                yield AgentTextDelta(visible)
                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason
                        if chunk.usage:
                            round_usage.update(chunk.usage)

                for trailing_visible in visible_text_filter.finish():
                    visible_parts.append(trailing_visible)
                    yield AgentTextDelta(trailing_visible)

                self._emit_stream_inference_end(
                    model=model,
                    content="".join(round_content),
                    tool_calls=tool_call_fragments,
                    finish_reason=finish_reason,
                    usage=round_usage,
                )
                total_prompt_tokens += round_usage.get("prompt_tokens", 0)
                total_completion_tokens += round_usage.get("completion_tokens", 0)

                if (
                    tool_call_fragments
                    or finish_reason != "length"
                    or continuations >= 2
                ):
                    break

                messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content="".join(visible_parts),
                    )
                )
                messages.append(
                    Message(
                        role=Role.USER,
                        content="Continue from where you left off.",
                    )
                )
                continuations += 1

            tool_calls = _build_tool_calls(tool_call_fragments)
            if tool_calls:
                messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content="".join(visible_parts),
                        tool_calls=tool_calls,
                    )
                )
                previous_tool_results = len(all_tool_results)
                for tool_call in tool_calls:
                    yield AgentToolStarted(tool_call.name)
                await self._execute_function_tool_calls_async(
                    messages,
                    tool_calls,
                    all_tool_results,
                    loop_guard,
                )
                new_tool_results = all_tool_results[previous_tool_results:]
                for tool_result in new_tool_results:
                    yield AgentToolFinished(
                        tool_result.tool_name,
                        ok=tool_result.success,
                    )
                if any(
                    _requires_pending_approval(result) for result in new_tool_results
                ):
                    self._emit_turn_end(turns=turns, pending_approval=True)
                    yield AgentRunCompleted(
                        AgentResult(
                            content="",
                            metadata={"pending_approval": True},
                        )
                    )
                    return
                continue

            # Every part was already yielded as it was produced; visible_parts
            # is kept only to assemble the whole answer for AgentRunCompleted.
            content = "".join(visible_parts)
            metadata = {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            }
            self._emit_turn_end(turns=turns, content_length=len(content))
            yield AgentRunCompleted(
                AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=metadata,
                )
            )
            return

        metadata = {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        }
        result = self._max_turns_result(
            all_tool_results,
            self._max_turns,
            content="",
            metadata=metadata,
        )
        if result.content:
            yield AgentTextDelta(result.content)
        yield AgentRunCompleted(result)

    def _emit_stream_inference_start(self, *, model: str | None = None) -> None:
        if self._bus and not getattr(
            self._engine,
            "_publishes_stream_events",
            False,
        ):
            self._bus.publish(
                EventType.INFERENCE_START,
                {
                    "model": model or self._model,
                    "engine": getattr(self._engine, "engine_id", ""),
                },
            )

    def _emit_stream_inference_end(
        self,
        *,
        model: str | None = None,
        content: str,
        tool_calls: dict[int, dict[str, Any]],
        finish_reason: str,
        usage: dict[str, Any],
    ) -> None:
        if self._bus and not getattr(
            self._engine,
            "_publishes_stream_events",
            False,
        ):
            self._bus.publish(
                EventType.INFERENCE_END,
                {
                    "model": model or self._model,
                    "usage": usage,
                    "content": content,
                    "tool_calls": list(tool_calls.values()),
                    "finish_reason": finish_reason,
                },
            )

    # ------------------------------------------------------------------
    # Structured mode (THOUGHT/TOOL/INPUT/FINAL_ANSWER)
    # ------------------------------------------------------------------

    def _run_structured(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)
        loop_guard = self._new_loop_guard()

        # Build system prompt
        if self._system_prompt:
            sys_prompt = self._system_prompt
        else:
            from openjarvis.learning.intelligence.orchestrator.prompt_registry import (
                build_system_prompt,
            )

            sys_prompt = build_system_prompt(tools=self._tools)

        messages = self._build_messages(input, context, system_prompt=sys_prompt)

        all_tool_results: list[ToolResult] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            if loop_guard:
                messages = loop_guard.compress_context(messages)

            result = self._generate(messages)
            content = result.get("content", "")

            parsed = self._parse_structured_response(content)

            # FINAL_ANSWER -> done
            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=parsed["final_answer"],
                    tool_results=all_tool_results,
                    turns=turns,
                )

            # TOOL -> execute
            if parsed["tool"]:
                messages.append(Message(role=Role.ASSISTANT, content=content))

                tool_call = ToolCall(
                    id=f"orch_{turns}",
                    name=parsed["tool"],
                    arguments=parsed["input"] or "{}",
                )
                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                observation = f"Observation: {tool_result.content}"
                messages.append(Message(role=Role.USER, content=observation))
                continue

            # Neither -> treat content as final answer
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=content,
                tool_results=all_tool_results,
                turns=turns,
            )

        # Max turns exceeded
        return self._max_turns_result(all_tool_results, turns)

    @staticmethod
    def _parse_structured_response(text: str) -> dict:
        """Parse THOUGHT/TOOL/INPUT/FINAL_ANSWER from model output."""
        result = {
            "thought": "",
            "tool": "",
            "input": "",
            "final_answer": "",
        }

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nTOOL:|\nFINAL[_ ]?ANSWER:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            return result

        tool_match = re.search(r"TOOL:\s*(.+)", text, re.IGNORECASE)
        if tool_match:
            result["tool"] = tool_match.group(1).strip()

        input_match = re.search(
            r"INPUT:\s*(.+?)(?=\nTHOUGHT:|\nTOOL:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if input_match:
            result["input"] = input_match.group(1).strip()

        return result

    # ------------------------------------------------------------------
    # Function-calling mode (original behaviour)
    # ------------------------------------------------------------------

    def _run_function_calling(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)
        loop_guard = self._new_loop_guard()

        # Build initial messages
        messages = self._build_messages(
            input,
            context,
            system_prompt=self._system_prompt,
        )

        # Get OpenAI-format tool definitions
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0

        for _turn in range(self._max_turns):
            turns += 1

            if loop_guard:
                messages = loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
                content = self._strip_think_tags(content)
                metadata = {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens,
                }
                self._emit_turn_end(turns=turns, content_length=len(content))
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=metadata,
                )

            # Build ToolCall objects from raw dicts
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]

            # Append assistant message with tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            )

            self._execute_function_tool_calls(
                messages,
                tool_calls,
                all_tool_results,
                loop_guard,
            )
        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        metadata = {
            "max_turns_exceeded": True,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        }
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata=metadata,
        )

    def _execute_function_tool_calls(
        self,
        messages: list[Message],
        tool_calls: list[ToolCall],
        all_tool_results: list[ToolResult],
        loop_guard: Any | None,
    ) -> None:
        ordered_results = self._collect_function_tool_results(tool_calls, loop_guard)
        self._append_function_tool_results(
            messages,
            all_tool_results,
            ordered_results,
        )

    async def _execute_function_tool_calls_async(
        self,
        messages: list[Message],
        tool_calls: list[ToolCall],
        all_tool_results: list[ToolResult],
        loop_guard: Any | None,
    ) -> None:
        ordered_results = await run_agent_sync_worker(
            self._collect_function_tool_results,
            tool_calls,
            loop_guard,
        )
        self._append_function_tool_results(
            messages,
            all_tool_results,
            ordered_results,
        )

    def _collect_function_tool_results(
        self,
        tool_calls: list[ToolCall],
        loop_guard: Any | None,
    ) -> list[tuple[ToolCall, ToolResult]]:
        def execute(tc: ToolCall) -> ToolResult:
            if loop_guard:
                verdict = loop_guard.check_call(
                    tc.name,
                    tc.arguments,
                    polling=self._tool_is_polling(tc.name),
                )
                if verdict.blocked:
                    return ToolResult(
                        tool_name=tc.name,
                        content=f"Loop guard: {verdict.reason}",
                        success=False,
                    )
            return self._executor.execute(tc)

        if self._parallel_tools and len(tool_calls) > 1:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(tool_calls)
            ) as pool:
                futures = {pool.submit(execute, tc): tc for tc in tool_calls}
                results = {id(tc): future.result() for future, tc in futures.items()}
            return [(tc, results[id(tc)]) for tc in tool_calls]
        return [(tc, execute(tc)) for tc in tool_calls]

    @staticmethod
    def _append_function_tool_results(
        messages: list[Message],
        all_tool_results: list[ToolResult],
        ordered_results: list[tuple[ToolCall, ToolResult]],
    ) -> None:
        for tc, tool_result in ordered_results:
            all_tool_results.append(tool_result)
            messages.append(
                Message(
                    role=Role.TOOL,
                    content=(
                        f"Tool execution success={str(tool_result.success).lower()}\n"
                        f"{tool_result.content}"
                    ),
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )


class _VisibleTextFilter:
    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._inside_think = False
        self._emitted_visible_text = False

    def feed(self, content: str) -> list[str]:
        visible = self._feed_visible(content)
        return [visible] if visible else []

    def _feed_visible(self, content: str) -> str:
        self._buffer += content
        visible_parts: list[str] = []

        while self._buffer:
            lowered = self._buffer.casefold()
            if self._inside_think:
                close_index = lowered.find(self._CLOSE_TAG)
                if close_index < 0:
                    keep = _partial_tag_suffix_length(
                        lowered,
                        self._CLOSE_TAG,
                    )
                    self._buffer = self._buffer[-keep:] if keep else ""
                    break
                self._buffer = self._buffer[close_index + len(self._CLOSE_TAG) :]
                self._inside_think = False
                continue

            open_index = lowered.find(self._OPEN_TAG)
            close_index = lowered.find(self._CLOSE_TAG)
            if close_index >= 0 and (open_index < 0 or close_index < open_index):
                visible_parts.clear()
                self._buffer = self._buffer[close_index + len(self._CLOSE_TAG) :]
                continue

            if open_index >= 0:
                visible_parts.append(self._buffer[:open_index])
                self._buffer = self._buffer[open_index + len(self._OPEN_TAG) :]
                self._inside_think = True
                continue

            partial_open = _partial_tag_suffix_length(lowered, self._OPEN_TAG)
            partial_close = _partial_tag_suffix_length(lowered, self._CLOSE_TAG)
            keep = max(partial_open, partial_close)
            if partial_close and not self._emitted_visible_text:
                break
            if keep:
                visible_parts.append(self._buffer[:-keep])
                self._buffer = self._buffer[-keep:]
            else:
                visible_parts.append(self._buffer)
                self._buffer = ""
            break

        visible = "".join(visible_parts)
        if visible:
            self._emitted_visible_text = True
        return visible

    def finish(self) -> list[str]:
        visible_parts: list[str] = []
        if self._inside_think:
            self._buffer = ""
            return visible_parts
        visible = self._buffer
        self._buffer = ""
        if visible.casefold() in {
            self._OPEN_TAG[:length] for length in range(1, len(self._OPEN_TAG))
        } | {self._CLOSE_TAG[:length] for length in range(1, len(self._CLOSE_TAG))}:
            return visible_parts
        if visible:
            visible_parts.append(visible)
        return visible_parts


def _partial_tag_suffix_length(text: str, tag: str) -> int:
    for length in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:length]):
            return length
    return 0


def _build_tool_calls(
    fragments: dict[int, dict[str, Any]],
) -> list[ToolCall]:
    return [
        ToolCall(
            id=fragment["id"] or f"call_{index}",
            name=fragment["function"]["name"],
            arguments=fragment["function"]["arguments"] or "{}",
        )
        for index, fragment in sorted(fragments.items())
    ]


def _requires_pending_approval(value: Any) -> bool:
    metadata = (
        value.get("metadata")
        if isinstance(value, dict)
        else getattr(value, "metadata", None)
    )
    return isinstance(metadata, dict) and bool(metadata.get("pending_approval"))


__all__ = ["OrchestratorAgent"]
