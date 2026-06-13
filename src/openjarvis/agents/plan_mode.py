"""Plan Mode Agent — strategic planning without immediate execution.

Inspired by the Claude Agent SDK cookbook.  Plan Mode analyses a
user request, breaks it into discrete steps, estimates risk / effort,
and returns a structured plan that can be reviewed before execution.

Output format (THOUGHT / PLAN / STEPS / FINAL_ANSWER) mirrors the
orchestrator structured mode so the same parser can be reused.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.hooks import HookRegistry, HookStage
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool


_PLAN_SYSTEM_PROMPT = """You are a strategic planning assistant. Your job is to analyse the user's request and produce a structured execution plan.

Do NOT execute any actions. Only plan.

Respond using the following format:

THOUGHT: <your reasoning about what the user wants and how to approach it>
PLAN: <concise title for the plan>
STEPS:
1. <step description> | effort: low/medium/high | risk: low/medium/high
2. <step description> | effort: low/medium/high | risk: low/medium/high
...
FINAL_ANSWER: <optional high-level summary or estimated outcome>

Guidelines:
- Break complex requests into concrete, verifiable steps.
- Flag high-risk steps explicitly.
- Estimate effort realistically (low = minutes, medium = hours, high = days).
- If the request is trivial (1 step, low effort, low risk), say so.
- If the request is ambiguous, ask clarifying questions in THOUGHT.
"""


@dataclass
class PlanStep:
    """Single step in a plan."""

    number: int
    description: str
    effort: str = "medium"
    risk: str = "low"
    estimated_minutes: Optional[int] = None


@dataclass
class ExecutionPlan:
    """Structured plan produced by PlanModeAgent."""

    title: str
    thought: str
    steps: List[PlanStep]
    final_answer: str = ""
    metadata: dict = field(default_factory=dict)


@AgentRegistry.register("plan_mode")
class PlanModeAgent(ToolUsingAgent):
    """Agent that produces strategic plans without executing them.

    Can optionally include tools in the plan description so the user
    sees which capabilities would be used.
    """

    agent_id = "plan_mode"
    _default_temperature = 0.4
    _default_max_tokens = 2048
    _default_max_turns = 3

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[Any] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._system_prompt = _PLAN_SYSTEM_PROMPT

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        messages = self._build_messages(input, context, system_prompt=self._system_prompt)

        # Optional: inject tool descriptions so the model knows what *could* be used
        if self._tools:
            tool_desc = "\n".join(
                f"- {t.name}: {t.description}" for t in self._tools
            )
            # Append as a system-level hint (won't affect conversation history semantics)
            if messages and messages[0].role == Role.SYSTEM:
                messages[0].content += f"\n\nAvailable capabilities:\n{tool_desc}"

        turns = 0
        for _turn in range(self._max_turns):
            turns += 1

            result = self._generate(messages)
            content = result.get("content", "")

            parsed = self._parse_plan_response(content)

            # If we got a valid plan, return it
            if parsed.get("plan"):
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=json.dumps(parsed, indent=2, ensure_ascii=False),
                    tool_results=[],
                    turns=turns,
                    metadata={"plan_mode": True, **parsed},
                )

            # If the model asks clarifying questions, treat that as the answer
            if "?" in content and not parsed.get("steps"):
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=content,
                    tool_results=[],
                    turns=turns,
                    metadata={"plan_mode": True, "needs_clarification": True},
                )

            # Otherwise loop once more (max 3 turns total)
            messages.append(Message(role=Role.ASSISTANT, content=content))
            messages.append(
                Message(
                    role=Role.USER,
                    content="Please restructure your response using the required THOUGHT / PLAN / STEPS / FINAL_ANSWER format.",
                )
            )

        # Max turns exceeded — return whatever we have
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=content or "Could not formulate a plan within the turn limit.",
            tool_results=[],
            turns=turns,
            metadata={"plan_mode": True, "max_turns_exceeded": True},
        )

    @staticmethod
    def _parse_plan_response(text: str) -> dict:
        """Parse THOUGHT / PLAN / STEPS / FINAL_ANSWER from model output."""
        result = {
            "thought": "",
            "plan": "",
            "steps": [],
            "final_answer": "",
        }

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nPLAN:|\nSTEPS:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        plan_match = re.search(
            r"PLAN:\s*(.+?)(?=\nSTEPS:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if plan_match:
            result["plan"] = plan_match.group(1).strip()

        steps_match = re.search(
            r"STEPS:\s*(.+?)(?=\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if steps_match:
            raw_steps = steps_match.group(1).strip()
            # Parse numbered list lines
            for line in raw_steps.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"(\d+)\.\s+(.*)", line)
                if m:
                    desc = m.group(2)
                    effort = "medium"
                    risk = "low"
                    # Try to extract effort / risk markers
                    em = re.search(r"\|\s*effort:\s*(low|medium|high)", desc, re.I)
                    if em:
                        effort = em.group(1).lower()
                        desc = desc.replace(em.group(0), "")
                    rm = re.search(r"\|\s*risk:\s*(low|medium|high)", desc, re.I)
                    if rm:
                        risk = rm.group(1).lower()
                        desc = desc.replace(rm.group(0), "")
                    result["steps"].append(
                        {
                            "number": int(m.group(1)),
                            "description": desc.strip(),
                            "effort": effort,
                            "risk": risk,
                        }
                    )

        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            result["final_answer"] = final_match.group(1).strip()

        return result


__all__ = ["PlanModeAgent", "ExecutionPlan", "PlanStep"]
