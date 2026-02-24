"""NativeOpenHandsAgent -- code-execution-centric agent.

Renamed from ``OpenHandsAgent`` to clarify this is OpenJarvis's native
CodeAct-style implementation.  The ``OpenHandsAgent`` name is now used
for the real openhands-sdk integration in ``openhands.py``.
"""

from __future__ import annotations

import json as _json
import re
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

OPENHANDS_SYSTEM_PROMPT = """\
You are an AI assistant with access to tools. You MUST use tools when they would help answer the user's question.

## How to use tools

To call a tool, write on its own lines:

Action: <tool_name>
Action Input: <json_arguments>

You will receive the result, then continue your response.

## Available tools

{tool_descriptions}

## Important rules

- When the user asks you to look up, search, fetch, or summarize a URL or topic, you MUST use web_search. Do NOT say you cannot browse the web.
- When the user provides a URL, pass the FULL URL (including https://) as the query to web_search. Do NOT rewrite URLs into search keywords.
- When the user asks a math question, use calculator.
- When the user asks to read a file, use file_read.
- You CAN write Python code in ```python blocks and it will be executed. Use this for computation, data processing, or when no specific tool fits.
- If no tool or code is needed, respond directly with your answer.
- Do NOT include <think> tags or internal reasoning in your response. Respond directly.\
"""


def _build_tool_descriptions(tools: list) -> str:
    """Build detailed tool descriptions from ToolSpec objects."""
    if not tools:
        return "No tools available."
    lines = []
    for t in tools:
        s = t.spec
        params = s.parameters.get("properties", {})
        required = s.parameters.get("required", [])
        param_parts = []
        for pname, pinfo in params.items():
            req_mark = " (required)" if pname in required else ""
            param_parts.append(
                f"    - {pname}{req_mark}: {pinfo.get('description', pinfo.get('type', ''))}"
            )
        param_str = "\n".join(param_parts) if param_parts else "    (no parameters)"
        lines.append(f"### {s.name}\n{s.description}\nParameters:\n{param_str}")
    return "\n\n".join(lines)


@AgentRegistry.register("native_openhands")
class NativeOpenHandsAgent(ToolUsingAgent):
    """Native CodeAct agent -- generates and executes Python code."""

    agent_id = "native_openhands"

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: int = 3,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> None:
        super().__init__(
            engine, model, tools=tools, bus=bus,
            max_turns=max_turns, temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _expand_urls(text: str) -> tuple[str, bool]:
        """If the user message contains a URL, fetch it and inline the content.

        Returns (possibly_expanded_text, was_expanded).
        """
        import re as _re

        url_match = _re.search(r"https?://[^\s,;\"'<>]+", text)
        if not url_match:
            return text, False
        url = url_match.group(0).rstrip(".,;)")
        try:
            from openjarvis.tools.web_search import WebSearchTool

            content = WebSearchTool._fetch_url(url, max_chars=4000)
            expanded = text.replace(url, f"\n\n--- Content from {url} ---\n{content}\n--- End of content ---\n")
            return expanded, True
        except Exception:
            return text, False

    def _truncate_if_needed(self, messages: list[Message], max_prompt_tokens: int = 3000) -> list[Message]:
        """Truncate messages if estimated token count exceeds limit."""
        total_chars = sum(len(m.content) for m in messages)
        estimated_tokens = total_chars // 4
        if estimated_tokens <= max_prompt_tokens:
            return messages
        # Find the last user message and truncate its content
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == Role.USER:
                excess_tokens = estimated_tokens - max_prompt_tokens
                excess_chars = excess_tokens * 4
                original = messages[i].content
                if len(original) > excess_chars + 200:
                    truncated = original[: len(original) - excess_chars]
                    messages[i] = Message(
                        role=Role.USER,
                        content=truncated + "\n\n[Input truncated to fit context window]",
                    )
                break
        return messages

    def _extract_code(self, text: str) -> str | None:
        """Extract Python code from markdown code blocks."""
        match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _extract_tool_call(self, text: str) -> tuple[str, str] | None:
        """Extract tool call from structured output.

        Supports two formats:
        1. Action: tool_name / Action Input: {"key": "value"}
        2. <tool_call>tool_name\\n$key=value</tool_call> (XML-style)
        """
        # Format 1: Action / Action Input
        action_match = re.search(r"Action:\s*(.+)", text)
        input_match = re.search(
            r"Action Input:\s*(.+?)(?=\n\n|\Z)", text, re.DOTALL
        )
        if action_match:
            return (
                action_match.group(1).strip(),
                input_match.group(1).strip() if input_match else "{}",
            )

        # Format 2: <tool_call>tool_name ... </tool_call> or </tool_name>
        xml_match = re.search(
            r"<tool_call>\s*(\w+)\s*(.*?)</\w+>",
            text,
            re.DOTALL,
        )
        if xml_match:
            tool_name = xml_match.group(1).strip()
            raw_params = xml_match.group(2).strip()
            # Parse $key=value or <key>value</key> params into JSON
            params: dict[str, Any] = {}
            # $key=value format
            for m in re.finditer(r"\$(\w+)=(.+?)(?=\$|\n<|</|$)", raw_params, re.DOTALL):
                params[m.group(1)] = m.group(2).strip().rstrip("</>\n")
            # <key>value</key> format
            for m in re.finditer(r"<(\w+)>(.*?)</\1>", raw_params, re.DOTALL):
                key, val = m.group(1), m.group(2).strip()
                # Try to parse as int
                try:
                    params[key] = int(val)
                except ValueError:
                    params[key] = val
            if params:
                return (tool_name, _json.dumps(params))
            return (tool_name, "{}")

        return None

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        tool_descriptions = _build_tool_descriptions(self._tools)
        system_prompt = OPENHANDS_SYSTEM_PROMPT.format(tool_descriptions=tool_descriptions)

        # Pre-fetch any URLs in the input so the LLM gets the content directly
        input, url_expanded = self._expand_urls(input)

        # If URL content was inlined, skip the tool loop -- just summarize directly
        if url_expanded:
            direct_messages: list[Message] = [
                Message(role=Role.SYSTEM, content="You are a helpful assistant. Respond directly to the user's request using the provided content. Do NOT include <think> tags."),
                Message(role=Role.USER, content=input),
            ]
            direct_messages = self._truncate_if_needed(direct_messages)
            try:
                result = self._generate(direct_messages)
                content = self._strip_think_tags(result.get("content", ""))
                self._emit_turn_end(turns=1)
                return AgentResult(content=content, tool_results=[], turns=1)
            except Exception as exc:
                error_str = str(exc)
                error_msg = (
                    "The input is too long for the model's context window. Please try a shorter message."
                    if "400" in error_str
                    else f"The model returned an error: {error_str}"
                )
                self._emit_turn_end(turns=1, error=True)
                return AgentResult(content=error_msg, tool_results=[], turns=1, metadata={"error": True})

        messages = self._build_messages(input, context, system_prompt=system_prompt)
        messages = self._truncate_if_needed(messages)

        all_tool_results: list[ToolResult] = []
        turns = 0
        last_content = ""

        for _turn in range(self._max_turns):
            turns += 1
            # Truncate before every generate call -- tool results may have
            # expanded the context beyond what the model supports.
            messages = self._truncate_if_needed(messages)

            try:
                result = self._generate(messages)
            except Exception as exc:
                error_str = str(exc)
                if "400" in error_str:
                    error_msg = (
                        "The input is too long for the model's context window. "
                        "Please try a shorter message."
                    )
                else:
                    error_msg = f"The model returned an error: {error_str}"
                self._emit_turn_end(turns=turns, error=True)
                return AgentResult(
                    content=error_msg,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata={"error": True},
                )

            content = result.get("content", "")
            # Strip think tags so they don't interfere with parsing
            content = self._strip_think_tags(content)
            last_content = content

            # Try to extract code
            code = self._extract_code(content)
            if code:
                messages.append(Message(role=Role.ASSISTANT, content=content))

                # Execute via code_interpreter tool if available
                tool_call = ToolCall(
                    id=f"code_{turns}",
                    name="code_interpreter",
                    arguments=_json.dumps({"code": code}),
                )
                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                obs_text = tool_result.content
                if len(obs_text) > 4000:
                    obs_text = obs_text[:4000] + "\n\n[Output truncated]"
                observation = f"Output:\n{obs_text}"
                messages.append(Message(role=Role.USER, content=observation))
                continue

            # Try tool call
            tool_info = self._extract_tool_call(content)
            if tool_info:
                action, action_input = tool_info
                messages.append(Message(role=Role.ASSISTANT, content=content))

                tool_call = ToolCall(
                    id=f"tool_{turns}", name=action, arguments=action_input
                )
                tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                obs_text = tool_result.content
                if len(obs_text) > 4000:
                    obs_text = obs_text[:4000] + "\n\n[Output truncated]"
                observation = f"Result: {obs_text}"
                messages.append(Message(role=Role.USER, content=observation))
                continue

            # No code or tool call -- this is the final answer
            content = self._strip_think_tags(content)
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=content, tool_results=all_tool_results, turns=turns
            )

        # Max turns
        final = self._strip_think_tags(last_content) or "Maximum turns reached."
        return self._max_turns_result(all_tool_results, turns, content=final)


__all__ = ["NativeOpenHandsAgent"]
