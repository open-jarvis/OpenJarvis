"""NativeReActAgent -- Thought-Action-Observation loop agent.

Renamed from ``ReActAgent`` to clarify this is OpenJarvis's native
implementation, not an integration with an external project.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

REACT_SYSTEM_PROMPT = """\
You are a ReAct agent. For each step, respond with exactly one of:

1. To think and act:
Thought: <your reasoning>
Action: <tool_name>
Action Input: <json arguments>

2. To give a final answer:
Thought: <your reasoning>
Final Answer: <your answer>

Available tools: {tool_names}"""


@AgentRegistry.register("native_react")
class NativeReActAgent(ToolUsingAgent):
    """ReAct agent: Thought -> Action -> Observation loop."""

    agent_id = "native_react"

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: int = 10,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(
            engine, model, tools=tools, bus=bus,
            max_turns=max_turns, temperature=temperature,
            max_tokens=max_tokens,
        )

    def _parse_response(self, text: str) -> dict:
        """Parse ReAct structured output."""
        result = {"thought": "", "action": "", "action_input": "", "final_answer": ""}

        # Extract Thought
        thought_match = re.search(
            r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|\Z)", text, re.DOTALL
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        # Check for Final Answer
        final_match = re.search(r"Final Answer:\s*(.+)", text, re.DOTALL)
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            return result

        # Extract Action and Action Input
        action_match = re.search(r"Action:\s*(.+)", text)
        if action_match:
            result["action"] = action_match.group(1).strip()

        input_match = re.search(
            r"Action Input:\s*(.+?)(?=\n\n|\nThought:|\Z)", text, re.DOTALL
        )
        if input_match:
            result["action_input"] = input_match.group(1).strip()

        return result

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build system prompt with available tools
        tool_names = (
            ", ".join(t.spec.name for t in self._tools) if self._tools else "none"
        )
        system_prompt = REACT_SYSTEM_PROMPT.format(tool_names=tool_names)

        messages = self._build_messages(input, context, system_prompt=system_prompt)

        all_tool_results: list[ToolResult] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            result = self._generate(messages)

            content = result.get("content", "")
            parsed = self._parse_response(content)

            # Final answer?
            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=parsed["final_answer"],
                    tool_results=all_tool_results,
                    turns=turns,
                )

            # No action? Treat content as final answer
            if not parsed["action"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=content, tool_results=all_tool_results, turns=turns
                )

            # Execute action
            messages.append(Message(role=Role.ASSISTANT, content=content))

            tool_call = ToolCall(
                id=f"react_{turns}",
                name=parsed["action"],
                arguments=parsed["action_input"] or "{}",
            )
            tool_result = self._executor.execute(tool_call)
            all_tool_results.append(tool_result)

            observation = f"Observation: {tool_result.content}"
            messages.append(Message(role=Role.USER, content=observation))

        # Max turns exceeded
        return self._max_turns_result(all_tool_results, turns)


__all__ = ["NativeReActAgent", "REACT_SYSTEM_PROMPT"]
