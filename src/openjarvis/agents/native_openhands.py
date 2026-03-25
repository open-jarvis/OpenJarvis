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
from openjarvis.tools._stubs import BaseTool, build_tool_descriptions

OPENHANDS_SYSTEM_PROMPT = (  # noqa: E501
    "You are an AI assistant with access to tools. "
    "You MUST use tools when they would help answer "
    "the user's question.\n\n"
    "## How to use tools\n\n"
    "To call a tool, write on its own lines:\n\n"
    "Action: <tool_name>\n"
    "Action Input: <json_arguments>\n\n"
    "You will receive the result, then continue your "
    "response.\n\n"
    "## Available tools\n\n"
    "{tool_descriptions}\n\n"
    "## Important rules\n\n"
    "- When the user asks you to look up, search, fetch, "
    "or summarize a URL or topic, you MUST use web_search. "
    "Do NOT say you cannot browse the web.\n"
    "- When the user provides a URL, pass the FULL URL "
    "(including https://) as the query to web_search. "
    "Do NOT rewrite URLs into search keywords.\n"
    "- When the user asks a math question, use calculator.\n"
    "- When the user asks to read a file, use file_read.\n"
    "- You CAN write Python code in ```python blocks and "
    "it will be executed. Use this for computation, data "
    "processing, or when no specific tool fits.\n"
    "- If no tool or code is needed, respond directly "
    "with your answer.\n"
    "- Do NOT include <think> tags or internal reasoning "
    "in your response. Respond directly."
)


@AgentRegistry.register("native_openhands")
class NativeOpenHandsAgent(ToolUsingAgent):
    """Native CodeAct agent -- generates and executes Python code."""

    agent_id = "native_openhands"
    _default_temperature = 0.7
    _default_max_tokens = 2048
    _default_max_turns = 3

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
            header = f"\n\n--- Content from {url} ---\n"
            footer = "\n--- End of content ---\n"
            expanded = text.replace(url, f"{header}{content}{footer}")
            return expanded, True
        except Exception:
            return text, False

    def _truncate_if_needed(
        self,
        messages: list[Message],
        max_prompt_tokens: int = 3000,
    ) -> list[Message]:
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
                        content=(
                            truncated + "\n\n[Input truncated to fit context window]"
                        ),
                    )
                break
        return messages

    @staticmethod
    def _strip_tool_call_text(text: str) -> str:
        """Remove raw tool call artifacts from final output."""
        # Remove Action: ... Action Input: ... blocks
        text = re.sub(
            r"Action:\s*.+?(?:Action Input:\s*.+?)?(?=\n\n|\Z)",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Remove <tool_call>...</tool_call> or </tool_name> blocks
        text = re.sub(r"<tool_call>.*?</\w+>", "", text, flags=re.DOTALL)
        return text.strip()

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
        action_match = re.search(r"Action:\s*(.+)", text, re.IGNORECASE)
        input_match = re.search(
            r"Action Input:\s*(.+?)(?=\n\n|\Z)", text, re.DOTALL | re.IGNORECASE
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
            pat = r"\$(\w+)=(.+?)(?=\$|\n<|</|$)"
            for m in re.finditer(pat, raw_params, re.DOTALL):
                params[m.group(1)] = m.group(2).strip().rstrip("</>\n")
            # <key>value</key> format
            for m in re.finditer(r"<(\w+)>(.*?)</\1>", raw_params, re.DOTALL):
                key, val = m.group(1), m.group(2).strip()
                # Try to parse as int
                try:
                    params[key] = int(val)
                except ValueError:
                    params[key] = val
            # key: value format (common in GLM models)
            if not params:
                for m in re.finditer(
                    r"(\w+)\s*:\s*(.+?)(?=\n\w+\s*:|$)", raw_params, re.DOTALL
                ):
                    key, val = m.group(1), m.group(2).strip().strip("\"'")
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

        tool_descriptions = build_tool_descriptions(self._tools)
        system_prompt = OPENHANDS_SYSTEM_PROMPT.format(
            tool_descriptions=tool_descriptions,
        )

        # Pre-fetch any URLs in the input so the LLM gets the content directly
        input, url_expanded = self._expand_urls(input)

        # If URL content was inlined, skip the tool loop -- just summarize directly
        if url_expanded:
            direct_messages: list[Message] = [
                Message(
                    role=Role.SYSTEM,
                    content=(
                        "You are a helpful assistant. "
                        "Respond directly to the user's "
                        "request using the provided content."
                        " Do NOT include <think> tags."
                    ),
                ),
                Message(role=Role.USER, content=input),
            ]
            direct_messages = self._truncate_if_needed(direct_messages)
            try:
                result = self._generate(direct_messages)
                content = self._strip_think_tags(result.get("content", ""))
                usage = result.get("usage", {})
                self._emit_turn_end(turns=1)
                return AgentResult(
                    content=content,
                    tool_results=[],
                    turns=1,
                    metadata={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                )
            except Exception as exc:
                error_str = str(exc)
                if "400" in error_str:
                    error_msg = (
                        "The input is too long for the "
                        "model's context window. "
                        "Please try a shorter message."
                    )
                else:
                    error_msg = "The model returned an error: " + error_str
                self._emit_turn_end(turns=1, error=True)
                return AgentResult(
                    content=error_msg,
                    tool_results=[],
                    turns=1,
                    metadata={"error": True},
                )

        messages = self._build_messages(input, context, system_prompt=system_prompt)
        messages = self._truncate_if_needed(messages)

        all_tool_results: list[ToolResult] = []
        turns = 0
        last_content = ""
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

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

            # Accumulate usage from this generate call
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)

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
            content = self._strip_tool_call_text(content)
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=content,
                tool_results=all_tool_results,
                turns=turns,
                metadata=total_usage,
            )

        # Max turns
        final = self._strip_think_tags(last_content) or "Maximum turns reached."
        final = self._strip_tool_call_text(final)
        result = self._max_turns_result(all_tool_results, turns, content=final)
        result.metadata.update(total_usage)
        return result


__all__ = ["NativeOpenHandsAgent"]
