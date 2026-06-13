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
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus
from openjarvis.core.hooks import HookRegistry, HookStage
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
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
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
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
        )
        self._mode = mode
        self._system_prompt = system_prompt
        self._parallel_tools = parallel_tools

    async def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if self._mode == "structured":
            return await self._run_structured(input, context, **kwargs)
        return await self._run_function_calling(input, context, **kwargs)

    # ------------------------------------------------------------------
    # Structured mode (THOUGHT/TOOL/INPUT/FINAL_ANSWER)
    # ------------------------------------------------------------------

    async def _run_structured(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

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
        hook_ctx = {"agent_id": self.agent_id, "conversation_id": kwargs.get("conversation_id")}

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Pre-generate hook
            gen_payload = {"messages": messages, "model": self._model}
            hr_gen = await HookRegistry.run(HookStage.PRE_GENERATE, payload=gen_payload, context=hook_ctx)
            if not hr_gen.allowed:
                return AgentResult(
                    content=f"Generation denied by hook: {hr_gen.error}",
                    tool_results=all_tool_results,
                    turns=turns,
                )
            if hr_gen.modified_payload:
                messages = hr_gen.modified_payload.get("messages", messages)

            result = self._generate(messages)
            content = result.get("content", "")

            # Post-generate hook
            await HookRegistry.run(
                HookStage.POST_GENERATE,
                payload={"result": result, "model": self._model},
                context=hook_ctx,
            )

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

                # Pre-tool-use hook
                pre_payload = {"tool_name": tool_call.name, "tool_input": tool_call.arguments}
                hr_tool = await HookRegistry.run(HookStage.PRE_TOOL_USE, payload=pre_payload, context=hook_ctx)
                if not hr_tool.allowed:
                    tool_result = ToolResult(
                        tool_name=tool_call.name,
                        content=f"Denied by hook: {hr_tool.error}",
                        success=False,
                    )
                else:
                    tool_result = self._executor.execute(tool_call)

                all_tool_results.append(tool_result)

                # Post-tool-use hook
                await HookRegistry.run(
                    HookStage.POST_TOOL_USE,
                    payload={"tool_name": tool_call.name, "tool_input": tool_call.arguments, "tool_output": tool_result.content},
                    context=hook_ctx,
                )

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

    async def _run_function_calling(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build initial messages
        messages = self._build_messages(input, context)

        # Get OpenAI-format tool definitions
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        hook_ctx = {"agent_id": self.agent_id, "conversation_id": kwargs.get("conversation_id")}

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            # Pre-generate hook
            gen_payload = {"messages": messages, "model": self._model, "kwargs": gen_kwargs}
            hr_gen = await HookRegistry.run(HookStage.PRE_GENERATE, payload=gen_payload, context=hook_ctx)
            if not hr_gen.allowed:
                return AgentResult(
                    content=f"Generation denied by hook: {hr_gen.error}",
                    tool_results=all_tool_results,
                    turns=turns,
                )
            if hr_gen.modified_payload:
                gen_kwargs = hr_gen.modified_payload.get("kwargs", gen_kwargs)

            result = self._generate(messages, **gen_kwargs)

            # Post-generate hook
            await HookRegistry.run(
                HookStage.POST_GENERATE,
                payload={"result": result, "model": self._model},
                context=hook_ctx,
            )

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
                self._emit_turn_end(turns=turns, content_length=len(content))
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={
                        "prompt_tokens": total_prompt_tokens,
                        "completion_tokens": total_completion_tokens,
                        "total_tokens": total_prompt_tokens + total_completion_tokens,
                    },
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

            # Execute each tool (with loop guard check + hooks) and append results
            for tc in tool_calls:
                # Loop guard check before execution
                if self._loop_guard:
                    verdict = self._loop_guard.check_call(
                        tc.name,
                        tc.arguments,
                    )
                    if verdict.blocked:
                        tool_result = ToolResult(
                            tool_name=tc.name,
                            content=f"Loop guard: {verdict.reason}",
                            success=False,
                        )
                        all_tool_results.append(tool_result)
                        messages.append(
                            Message(
                                role=Role.TOOL,
                                content=tool_result.content,
                                tool_call_id=tc.id,
                                name=tc.name,
                            )
                        )
                        continue

                # Pre-tool-use hook
                pre_payload = {"tool_name": tc.name, "tool_input": tc.arguments}
                hr_tool = await HookRegistry.run(HookStage.PRE_TOOL_USE, payload=pre_payload, context=hook_ctx)
                if not hr_tool.allowed:
                    tool_result = ToolResult(
                        tool_name=tc.name,
                        content=f"Denied by hook: {hr_tool.error}",
                        success=False,
                    )
                else:
                    if hr_tool.modified_payload:
                        tc.arguments = hr_tool.modified_payload.get("tool_input", tc.arguments)
                    tool_result = self._executor.execute(tc)

                all_tool_results.append(tool_result)

                # Post-tool-use hook
                await HookRegistry.run(
                    HookStage.POST_TOOL_USE,
                    payload={"tool_name": tc.name, "tool_input": tc.arguments, "tool_output": tool_result.content},
                    context=hook_ctx,
                )

                # Append tool response message
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata={
                "max_turns_exceeded": True,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
        )


__all__ = ["OrchestratorAgent"]
