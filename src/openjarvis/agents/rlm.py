"""RLM (Recursive Language Model) Agent — recursive decomposition via persistent REPL.

Based on the RLM paper (arxiv:2512.24601). Instead of passing long context
directly in the LLM prompt, RLM stores context as a Python variable in a
persistent REPL.  A "Root LM" writes Python code to inspect/decompose
context and makes recursive sub-LM calls via ``llm_query()``/``llm_batch()``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.agents.prompt_loader import (
    load_few_shot_exemplars,
    load_system_prompt_override,
)
from openjarvis.agents.rlm_repl import RLMRepl
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, build_tool_descriptions

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

RLM_SYSTEM_PROMPT = (
    "You are an AI assistant that solves problems by writing "
    "Python code in a persistent REPL.\n\n"
    "## Available REPL Functions\n\n"
    "- `llm_query(prompt: str) -> str` — Call a sub-LM with a "
    "prompt and get a response.\n"
    "- `llm_batch(prompts: list[str]) -> list[str]` — Call a "
    "sub-LM with multiple prompts.\n"
    "- `tool_call(tool_name: str, args: dict) -> str` — Execute an "
    "OpenJarvis tool and return its textual output.\n"
    "- `read_file(path: str, max_lines: int = 120) -> str` — Read the "
    "first N lines of a file through the real file_read tool.\n"
    "- `read_file_chunk(path: str, start_line: int, end_line: int) -> str` "
    "— Read only a bounded line range from a file.\n"
    "- `FINAL(value)` — Terminate and return `value` as the "
    "final answer.\n"
    "- `FINAL_VAR(var_name: str)` — Terminate and return the "
    "value of variable `var_name`.\n"
    '- `answer` dict — Set `answer["value"] = ...` and '
    '`answer["ready"] = True` to terminate.\n\n'
    "{tool_section}"
    "## Available Modules\n\n"
    "json, re, math, collections, itertools, functools, "
    "textwrap, string, copy, datetime\n\n"
    "## Context Variable\n\n"
    "The input context (if any) is stored in the variable "
    "`context`. You can inspect it, slice it, or decompose it "
    "using Python.\n\n"
    "## Instructions\n\n"
    "1. Write Python code inside ```python blocks to manipulate "
    "context and solve the problem.\n"
    "2. For long contexts, decompose them into smaller chunks "
    "and use `llm_query()` on each chunk.\n"
    "3. Combine sub-results programmatically.\n"
    "4. When you have the final answer, call "
    '`FINAL(answer_value)` or `FINAL_VAR("var_name")`.\n'
    "5. If you can answer directly without code, just respond "
    "with text (no code block).\n\n"
    "6. For file access, web access, or any external side effect, use "
    "the injected tool helpers (for example "
    '`file_read(path="...")` or `tool_call("file_read", {{"path": "..."}})`). '
    "Do NOT use open(), subprocess, urllib, or direct OS access.\n\n"
    "7. For file-analysis tasks, do NOT dump whole files. Prefer "
    "`read_file(path, max_lines=...)` or "
    "`read_file_chunk(path, start_line, end_line)` and summarize "
    "incrementally.\n\n"
    "## Strategy Tips\n\n"
    "- Split long text into paragraphs or sections, summarize "
    "each with `llm_query()`.\n"
    "- Use `llm_batch()` for parallel sub-queries on multiple "
    "chunks.\n"
    "- Store intermediate results in variables — the REPL "
    "persists state across turns.\n"
    "- Build up the answer incrementally across multiple code "
    "blocks.\n"
)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@AgentRegistry.register("rlm")
class RLMAgent(ToolUsingAgent):
    """Recursive Language Model agent using a persistent REPL.

    The agent generates Python code that runs in a sandboxed REPL with
    access to ``llm_query()`` / ``llm_batch()`` for recursive sub-LM
    calls.  Context is stored as a REPL variable rather than injected
    directly into the prompt, enabling processing of arbitrarily long
    inputs through recursive decomposition.
    """

    agent_id = "rlm"
    _default_temperature = 0.7
    _default_max_tokens = 2048
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
        sub_model: Optional[str] = None,
        sub_temperature: float = 0.3,
        sub_max_tokens: int = 1024,
        max_output_chars: int = 10000,
        system_prompt: Optional[str] = None,
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
        # Override executor: RLM only creates one if tools are provided
        if not self._tools:
            self._executor = None  # type: ignore[assignment]
        self._sub_model = sub_model or model
        self._sub_temperature = sub_temperature
        self._sub_max_tokens = sub_max_tokens
        self._max_output_chars = max_output_chars
        self._custom_system_prompt = system_prompt

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build system prompt with tool section
        if self._tools:
            tool_section = (
                "## Available Tools\n\n"
                "These tools are available to the sub-LM via "
                "llm_query(). When writing prompts for llm_query(), "
                "you can instruct it to use these tools:\n\n"
                + build_tool_descriptions(self._tools)
                + "\n\n"
            )
        else:
            tool_section = ""

        if self._custom_system_prompt:
            system_prompt = self._custom_system_prompt
        else:
            prompt_template = load_system_prompt_override("rlm") or RLM_SYSTEM_PROMPT
            try:
                system_prompt = prompt_template.format(
                    tool_section=tool_section,
                )
            except KeyError:
                system_prompt = prompt_template

        # Create REPL with sub-LM callbacks
        self._repl_tool_results: List[ToolResult] = []
        repl = RLMRepl(
            llm_query_fn=self._make_sub_query,
            llm_batch_fn=self._make_batch_query,
            tool_call_fn=self._execute_tool_from_repl if self._executor else None,
            tool_arg_names=self._tool_arg_names(),
            max_output_chars=self._max_output_chars,
        )

        # Resolve context and inject into REPL
        ctx_text = self._resolve_context(context)
        if ctx_text:
            repl.set_variable("context", ctx_text)
        if self._executor is not None:
            repl.set_variable("read_file", self._repl_read_file)
            repl.set_variable("read_file_chunk", self._repl_read_file_chunk)

        # Build conversation
        messages = self._build_messages(
            input,
            context,
            system_prompt=system_prompt,
        )

        # Inject few-shot exemplars before the user input
        for ex in load_few_shot_exemplars("rlm"):
            if ex.get("input") and ex.get("output"):
                messages.insert(-1, Message(role=Role.USER, content=ex["input"]))
                messages.insert(-1, Message(role=Role.ASSISTANT, content=ex["output"]))

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for _turn in range(self._max_turns):
            turns += 1

            result = self._generate(messages)
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
            content = result.get("content", "")

            # Strip <think> tags
            content = self._strip_think_tags(content)

            # Extract code block
            code = self._extract_code(content)

            # No code block -> return content as final answer
            if code is None:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=total_usage,
                )

            # Execute code in REPL
            output = repl.execute(code)

            if self._repl_tool_results:
                all_tool_results.extend(self._repl_tool_results)
                self._repl_tool_results = []

            # Record as tool result
            tool_result = ToolResult(
                tool_name="rlm_repl",
                content=output or "(no output)",
                success=(
                    not output.startswith("Error:")
                    and not output.startswith("SyntaxError:")
                ),
            )
            all_tool_results.append(tool_result)

            # Check for termination
            if repl.is_terminated:
                final = repl.final_answer
                final_str = str(final) if final is not None else ""
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=final_str,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=total_usage,
                )

            # Feed output back as user message
            messages.append(Message(role=Role.ASSISTANT, content=content))
            feedback = (
                f"REPL Output: {output}" if output else "REPL Output: (no output)"
            )
            messages.append(Message(role=Role.USER, content=feedback))

        # Max turns exceeded -- check answer dict for partial result
        answer = repl.get_variable("answer")
        if isinstance(answer, dict) and answer.get("value") is not None:
            final_content = str(answer["value"])
        else:
            final_content = ""

        return self._max_turns_result(
            all_tool_results, turns, content=final_content, metadata=total_usage
        )

    # ------------------------------------------------------------------
    # Sub-LM callbacks
    # ------------------------------------------------------------------

    def _make_sub_query(self, prompt: str) -> str:
        """Execute a single sub-LM query.

        Called from REPL code via ``llm_query(prompt)``.
        If the sub-LM returns tool_calls, execute one round of tool
        resolution before returning the final text.
        """
        messages = [Message(role=Role.USER, content=prompt)]
        result = self._engine.generate(
            messages,
            model=self._sub_model,
            temperature=self._sub_temperature,
            max_tokens=self._sub_max_tokens,
        )

        # Single-turn tool resolution
        raw_tool_calls = result.get("tool_calls", [])
        if raw_tool_calls and self._executor:
            content = result.get("content", "")
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"sub_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            )
            for tc in tool_calls:
                tr = self._executor.execute(tc)
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tr.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
            followup = self._engine.generate(
                messages,
                model=self._sub_model,
                temperature=self._sub_temperature,
                max_tokens=self._sub_max_tokens,
            )
            return followup.get("content", "")

        return result.get("content", "")

    def _make_batch_query(self, prompts: List[str]) -> List[str]:
        """Execute multiple sub-LM queries sequentially.

        Called from REPL code via ``llm_batch(prompts)``.
        """
        return [self._make_sub_query(p) for p in prompts]

    def _tool_arg_names(self) -> Dict[str, Optional[str]]:
        """Build a best-effort primary-arg map for injected tool helpers."""
        arg_names: Dict[str, Optional[str]] = {}
        for tool in self._tools:
            props = tool.spec.parameters.get("properties", {})
            required = tool.spec.parameters.get("required", [])
            primary = None
            if required:
                primary = required[0]
            elif props:
                primary = next(iter(props.keys()))
            arg_names[tool.spec.name] = primary
        return arg_names

    def _execute_tool_from_repl(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Execute a real OpenJarvis tool from within the REPL."""
        if self._executor is None:
            raise RuntimeError(f"Tool '{tool_name}' is not available")

        tc = ToolCall(
            id=f"rlm_tool_{len(getattr(self, '_repl_tool_results', []))}",
            name=tool_name,
            arguments=json.dumps(params),
        )
        tr = self._executor.execute(tc)
        getattr(self, "_repl_tool_results", []).append(tr)
        return tr.content

    def _repl_read_file(self, path: str, max_lines: int = 120) -> str:
        """Read a bounded number of lines from a file via the real tool."""
        params: Dict[str, Any] = {"path": path}
        try:
            max_lines_int = int(max_lines)
        except (TypeError, ValueError):
            max_lines_int = 120
        if max_lines_int > 0:
            params["max_lines"] = max_lines_int
        return self._execute_tool_from_repl("file_read", params)

    def _repl_read_file_chunk(
        self,
        path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        """Read a bounded line range from a file via the file_read tool.

        The underlying tool only supports a head-style max_lines cap, so this
        helper reads up to ``end_line`` and then slices the requested range in
        Python. This is still much cheaper than asking the model to dump the
        entire file into the next turn.
        """
        try:
            start = max(1, int(start_line))
            end = max(start, int(end_line))
        except (TypeError, ValueError):
            start, end = 1, 120

        content = self._execute_tool_from_repl(
            "file_read",
            {"path": path, "max_lines": end},
        )
        lines = content.splitlines(keepends=True)
        return "".join(lines[start - 1 : end])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        """Extract the first ```python code block from *text*.

        Also matches bare ``` blocks (without language tag).
        Returns ``None`` if no code block is found.
        """
        # Try ```python first
        m = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # Try bare ```
        m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _resolve_context(context: Optional[AgentContext]) -> Optional[str]:
        """Resolve context text from AgentContext metadata or memory_results."""
        if context is None:
            return None
        # Primary: explicit context in metadata
        if context.metadata.get("context"):
            return str(context.metadata["context"])
        # Fallback: join memory results
        if context.memory_results:
            return "\n\n".join(str(r) for r in context.memory_results)
        return None


__all__ = ["RLMAgent", "RLM_SYSTEM_PROMPT"]
