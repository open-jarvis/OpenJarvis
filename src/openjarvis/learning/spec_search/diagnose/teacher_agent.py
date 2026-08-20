"""TeacherAgent: frontier model as a tool-calling meta-engineer.

NOT registered in ``AgentRegistry``. NOT a subclass of ``BaseAgent``.
This is a standalone tool-calling loop that wraps ``CloudEngine`` with
diagnostic tools for the diagnose phase.

The teacher:
- Uses a frontier model (default ``claude-opus-4-6``) regardless of the
  user's local intelligence config.
- Has its own tool set (diagnostic tools) that user agents do not have.
- Tracks cost and stops when the budget is exhausted.
- Logs every tool call to a list of ``ToolCallRecord``.

See spec §5.1.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.learning.spec_search.diagnose.types import (
    DiagnosticTool,
    ToolCallRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class TeacherAgentResult:
    """The result of a TeacherAgent.run() call."""

    content: str
    turns: int
    total_cost_usd: float
    total_tokens: int
    tool_call_records: list[ToolCallRecord] = field(default_factory=list)


class TeacherAgent:
    """Frontier model tool-calling loop for the diagnose phase.

    Parameters
    ----------
    engine :
        A ``CloudEngine`` (or mock) that provides ``generate()``.
    model :
        The frontier model id (e.g. ``"claude-opus-4-6"``).
    tools :
        Diagnostic tools exposed to the teacher.
    max_turns :
        Maximum number of generate() calls before stopping.
    max_cost_usd :
        Maximum accumulated cost before stopping.
    """

    def __init__(
        self,
        engine: Any,
        model: str,
        tools: list[DiagnosticTool],
        max_turns: int = 30,
        max_cost_usd: float = 5.0,
        max_tokens: int = 8192,
    ) -> None:
        self._engine = engine
        self._model = model
        self._tools = {t.name: t for t in tools}
        self._tool_specs = [t.to_openai_function() for t in tools]
        self._max_turns = max_turns
        self._max_cost_usd = max_cost_usd
        self._max_tokens = max_tokens

    def run(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> TeacherAgentResult:
        """Run the teacher tool-calling loop.

        Parameters
        ----------
        user_prompt :
            The instruction to the teacher (e.g. "Analyze student failures").
        system_prompt :
            Optional system prompt explaining the teacher's role.

        Returns
        -------
        TeacherAgentResult
            The teacher's final content, cost, and tool call records.
        """
        messages: list[Message] = []
        if system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=system_prompt))
        messages.append(Message(role=Role.USER, content=user_prompt))

        total_cost = 0.0
        total_tokens = 0
        tool_call_records: list[ToolCallRecord] = []
        final_content = ""

        gen_kwargs: dict[str, Any] = {}
        if self._tool_specs:
            gen_kwargs["tools"] = self._tool_specs

        for turn in range(1, self._max_turns + 1):
            # Budget pre-check: don't start a new turn if we've already
            # exceeded the budget. Without this, the `if not raw_tool_calls`
            # early-return path below bypasses the post-check entirely,
            # meaning the final (terminal) turn runs unchecked. Pre-checking
            # here closes that hole.
            #
            # Note: a single turn that ITSELF exceeds the remaining budget
            # still overshoots. With Opus + ~8k max_tokens + growing input
            # context, a late-in-conversation final turn can cost $2-4. To
            # bound this further, lower `max_turns` (caps context growth)
            # or lower `max_cost_usd` in the config.
            if total_cost >= self._max_cost_usd:
                logger.warning(
                    "Teacher budget exceeded before turn %d: $%.2f >= $%.2f",
                    turn,
                    total_cost,
                    self._max_cost_usd,
                )
                return TeacherAgentResult(
                    content=final_content,
                    turns=turn - 1,
                    total_cost_usd=total_cost,
                    total_tokens=total_tokens,
                    tool_call_records=tool_call_records,
                )

            result = self._engine.generate(
                messages=messages,
                model=self._model,
                max_tokens=self._max_tokens,
                **gen_kwargs,
            )

            cost = result.get("cost_usd", 0.0)
            total_cost += cost
            usage = result.get("usage", {})
            total_tokens += usage.get("total_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            if not raw_tool_calls:
                final_content = content
                return TeacherAgentResult(
                    content=final_content,
                    turns=turn,
                    total_cost_usd=total_cost,
                    total_tokens=total_tokens,
                    tool_call_records=tool_call_records,
                )

            # Convert raw tool calls to ToolCall objects
            tool_call_objs = []
            for tc in raw_tool_calls:
                tc_obj = ToolCall(
                    id=tc["id"] if isinstance(tc, dict) else tc.id,
                    name=tc["name"] if isinstance(tc, dict) else tc.name,
                    arguments=(
                        tc.get("arguments", "{}")
                        if isinstance(tc, dict)
                        else tc.arguments
                    ),
                )
                tool_call_objs.append(tc_obj)

            # Append assistant message with tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_call_objs,
                )
            )

            # Execute each tool call
            for tc in tool_call_objs:
                tc_name = tc.name
                tc_id = tc.id
                tc_args_str = tc.arguments

                try:
                    tc_args = json.loads(tc_args_str)
                except json.JSONDecodeError:
                    tc_args = {}

                tool = self._tools.get(tc_name)
                start_time = time.monotonic()
                if tool is not None:
                    try:
                        tool_result = tool.fn(**tc_args)
                    except Exception as e:
                        tool_result = json.dumps({"error": str(e)})
                        logger.warning("Tool %s raised: %s", tc_name, e)
                else:
                    tool_result = json.dumps({"error": f"Unknown tool: {tc_name}"})
                elapsed_ms = (time.monotonic() - start_time) * 1000

                # Safety cap on tool results to bound context growth.
                # Primary truncation should happen inside each tool, but this
                # is defense-in-depth for tools that return too much. 20KB
                # per call × 30 max_turns = 600KB total, well under Opus's
                # 1M-token context window.
                MAX_TOOL_RESULT_CHARS = 20000
                if len(tool_result) > MAX_TOOL_RESULT_CHARS:
                    tool_result = (
                        tool_result[:MAX_TOOL_RESULT_CHARS]
                        + f"\n...[tool result truncated from {len(tool_result)} chars]"
                    )

                tool_call_records.append(
                    ToolCallRecord(
                        timestamp=datetime.now(timezone.utc),
                        tool=tc_name,
                        args=tc_args,
                        result=tool_result[:8000],  # Shorter cap for audit log
                        latency_ms=elapsed_ms,
                        cost_usd=0.0,  # Tool calls themselves are free
                    )
                )

                # Append tool result message (uses the safety-capped value)
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result,
                        tool_call_id=tc_id,
                        name=tc_name,
                    )
                )

            # Check cost budget
            if total_cost >= self._max_cost_usd:
                logger.warning(
                    "Teacher cost budget exceeded: $%.2f >= $%.2f",
                    total_cost,
                    self._max_cost_usd,
                )
                final_content = content
                return TeacherAgentResult(
                    content=final_content,
                    turns=turn,
                    total_cost_usd=total_cost,
                    total_tokens=total_tokens,
                    tool_call_records=tool_call_records,
                )

        # Exhausted max_turns
        logger.warning("Teacher exhausted max_turns=%d", self._max_turns)
        return TeacherAgentResult(
            content=final_content,
            turns=self._max_turns,
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            tool_call_records=tool_call_records,
        )
