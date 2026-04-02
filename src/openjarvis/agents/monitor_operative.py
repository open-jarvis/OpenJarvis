"""MonitorOperativeAgent -- long-horizon agent with configurable strategies.

Extends ToolUsingAgent (not OperativeAgent) with four configurable strategy
axes for long-horizon benchmark evaluation:

1. **memory_extraction** -- how findings are persisted to memory
2. **observation_compression** -- how tool outputs are compressed
3. **retrieval_strategy** -- how prior context is recalled
4. **task_decomposition** -- how complex tasks are split

The agent also inherits cross-session state persistence from the
OperativeAgent pattern (session_store, memory_backend, operator_id).
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult, _message_to_dict
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid strategy values
# ---------------------------------------------------------------------------

VALID_MEMORY_EXTRACTION = {"causality_graph", "scratchpad", "structured_json", "none"}
VALID_OBSERVATION_COMPRESSION = {"summarize", "truncate", "none"}
VALID_RETRIEVAL_STRATEGY = {"hybrid_with_self_eval", "keyword", "semantic", "none"}
VALID_TASK_DECOMPOSITION = {"phased", "monolithic", "hierarchical"}

# ---------------------------------------------------------------------------
# Default system prompt
# ---------------------------------------------------------------------------

MONITOR_OPERATIVE_SYSTEM_PROMPT = """\
You are a Monitor Operative Agent designed for long-horizon tasks.

## Capabilities
1. TOOLS: Call any available tool via function calling
2. STATE: Your previous findings and state are automatically restored
3. MEMORY: Store important findings for future recall

## Strategy
- Memory extraction: {memory_extraction}
- Observation compression: {observation_compression}
- Retrieval strategy: {retrieval_strategy}
- Task decomposition: {task_decomposition}

## Protocol
- Break complex tasks into phases and track progress
- Store causal relationships and key findings in memory
- Compress long tool outputs before adding to context
- Self-evaluate retrieved context for relevance
- Always persist state before finishing

{tool_descriptions}"""


@AgentRegistry.register("monitor_operative")
class MonitorOperativeAgent(ToolUsingAgent):
    """Long-horizon agent with configurable memory, compression, retrieval,
    and decomposition strategies.

    The four strategy axes control how the agent manages information across
    turns and sessions:

    - ``memory_extraction``: How findings are persisted (causality_graph,
      scratchpad, structured_json, none).
    - ``observation_compression``: How tool outputs are compressed before
      being added to context (summarize, truncate, none).
    - ``retrieval_strategy``: How prior context is recalled at the start
      of each run (hybrid_with_self_eval, keyword, semantic, none).
    - ``task_decomposition``: How complex tasks are broken down
      (phased, monolithic, hierarchical).
    """

    agent_id = "monitor_operative"
    accepts_tools = True
    _default_temperature = 0.3
    _default_max_tokens = 4096
    _default_max_turns = 25

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
        system_prompt: Optional[str] = None,
        # Strategy parameters
        memory_extraction: str = "causality_graph",
        observation_compression: str = "summarize",
        retrieval_strategy: str = "hybrid_with_self_eval",
        task_decomposition: str = "phased",
        # State persistence (OperativeAgent pattern)
        operator_id: Optional[str] = None,
        session_store: Optional[Any] = None,
        memory_backend: Optional[Any] = None,
        interactive: bool = False,
        confirm_callback=None,
        **kwargs: Any,
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
        # Validate strategies
        if memory_extraction not in VALID_MEMORY_EXTRACTION:
            raise ValueError(
                f"Invalid memory_extraction {memory_extraction!r}, "
                f"must be one of {VALID_MEMORY_EXTRACTION}"
            )
        if observation_compression not in VALID_OBSERVATION_COMPRESSION:
            raise ValueError(
                f"Invalid observation_compression {observation_compression!r}, "
                f"must be one of {VALID_OBSERVATION_COMPRESSION}"
            )
        if retrieval_strategy not in VALID_RETRIEVAL_STRATEGY:
            raise ValueError(
                f"Invalid retrieval_strategy {retrieval_strategy!r}, "
                f"must be one of {VALID_RETRIEVAL_STRATEGY}"
            )
        if task_decomposition not in VALID_TASK_DECOMPOSITION:
            raise ValueError(
                f"Invalid task_decomposition {task_decomposition!r}, "
                f"must be one of {VALID_TASK_DECOMPOSITION}"
            )

        self._memory_extraction = memory_extraction
        self._observation_compression = observation_compression
        self._retrieval_strategy = retrieval_strategy
        self._task_decomposition = task_decomposition

        self._system_prompt = system_prompt
        self._operator_id = operator_id
        self._session_store = session_store
        self._memory_backend = memory_backend

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the agent on *input* with the configured strategies."""
        self._emit_turn_start(input)

        # 1. Build system prompt with state context
        sys_parts: list[str] = []
        if self._system_prompt:
            sys_parts.append(self._system_prompt)
        else:
            tool_desc = self._build_tool_descriptions()
            try:
                sys_parts.append(
                    MONITOR_OPERATIVE_SYSTEM_PROMPT.format(
                        memory_extraction=self._memory_extraction,
                        observation_compression=self._observation_compression,
                        retrieval_strategy=self._retrieval_strategy,
                        task_decomposition=self._task_decomposition,
                        tool_descriptions=tool_desc,
                    ),
                )
            except KeyError:
                sys_parts.append(MONITOR_OPERATIVE_SYSTEM_PROMPT)

        # 2. State recall from memory backend
        previous_state = self._recall_state()
        if previous_state:
            sys_parts.append(f"\n## Previous State\n{previous_state}")

        system_prompt = "\n\n".join(sys_parts) if sys_parts else None

        # 3. Load session history
        session_messages = self._load_session()

        # 4. Build messages
        messages = self._build_operative_messages(
            input,
            context,
            system_prompt=system_prompt,
            session_messages=session_messages,
        )

        # 5. Run function-calling tool loop
        openai_tools = self._executor.get_openai_tools() if self._tools else []
        all_tool_results: list[ToolResult] = []
        turns = 0
        content = ""
        state_stored_by_tool = False
        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for _turn in range(self._max_turns):
            turns += 1

            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
                break

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

            # Execute each tool
            for tc in tool_calls:
                # Loop guard check
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

                tool_result = self._executor.execute(tc)
                all_tool_results.append(tool_result)

                # Track explicit state storage
                if tc.name == "memory_store" and self._operator_id:
                    try:
                        args = json.loads(tc.arguments)
                        state_key = f"monitor_operative:{self._operator_id}:state"
                        if args.get("key", "") == state_key:
                            state_stored_by_tool = True
                    except (json.JSONDecodeError, TypeError) as exc:
                        logger.debug(
                            "Failed to parse tool call arguments"
                            " for state tracking: %s",
                            exc,
                        )

                # Compress observation if strategy requires it
                observation_content = self._compress_observation(tool_result.content)

                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=observation_content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

                # Extract and store findings based on memory strategy
                self._extract_and_store(tc.name, tool_result.content)
        else:
            # Max turns exceeded
            self._save_session(input, content)
            msg_dicts = [_message_to_dict(m) for m in messages]
            return self._max_turns_result(
                all_tool_results,
                turns,
                content=content,
                metadata={**total_usage, "messages": msg_dicts},
            )

        # 6. Save session
        self._save_session(input, content)

        # 7. Auto-persist state if agent didn't do it explicitly
        if not state_stored_by_tool:
            self._auto_persist_state(content)

        self._emit_turn_end(turns=turns, content_length=len(content))
        msg_dicts = [_message_to_dict(m) for m in messages]
        return AgentResult(
            content=content,
            tool_results=all_tool_results,
            turns=turns,
            metadata={**total_usage, "messages": msg_dicts},
        )

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def _build_operative_messages(
        self,
        input: str,
        context: Optional[AgentContext],
        *,
        system_prompt: Optional[str] = None,
        session_messages: Optional[list[Message]] = None,
    ) -> list[Message]:
        """Build message list with system prompt, session history, and input."""
        messages: list[Message] = []
        if system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=system_prompt))
        if session_messages:
            messages.extend(session_messages)
        if context and context.conversation.messages:
            messages.extend(context.conversation.messages)
        messages.append(Message(role=Role.USER, content=input))
        return messages

    def _build_tool_descriptions(self) -> str:
        """Build a text description of available tools for the system prompt."""
        if not self._tools:
            return ""
        from openjarvis.tools._stubs import build_tool_descriptions

        return build_tool_descriptions(self._tools)

    # ------------------------------------------------------------------
    # Strategy methods
    # ------------------------------------------------------------------

    def _compress_observation(self, content: str) -> str:
        """Compress a tool observation according to the compression strategy.

        - ``summarize``: If content exceeds 2000 chars, ask the LLM to
          summarize. Falls back to truncation if generation fails.
        - ``truncate``: Hard-truncate at 2000 chars with an ellipsis.
        - ``none``: Return content unchanged.
        """
        if self._observation_compression == "none":
            return content
        if self._observation_compression == "truncate":
            if len(content) > 2000:
                return content[:2000] + "\n... [truncated]"
            return content
        # "summarize"
        if len(content) <= 2000:
            return content
        try:
            summary_messages = [
                Message(
                    role=Role.SYSTEM,
                    content="Summarize the following tool output concisely, "
                    "preserving all key facts and data points.",
                ),
                Message(role=Role.USER, content=content[:8000]),
            ]
            result = self._generate(summary_messages)
            summary = result.get("content", "")
            if summary:
                return summary
        except Exception:
            logger.debug("Observation summarization failed, falling back to truncation")
        # Fallback to truncation
        return content[:2000] + "\n... [truncated]"

    def _extract_and_store(self, tool_name: str, content: str) -> None:
        """Extract findings from a tool result and store them.

        The extraction strategy depends on ``_memory_extraction``:

        - ``causality_graph``: Extract causal relationships via
          :meth:`_extract_causality` and store as KG triples.
        - ``scratchpad``: Append raw content to a scratchpad key in
          memory.
        - ``structured_json``: Attempt to parse JSON from the content
          and store structured data.
        - ``none``: Do nothing.
        """
        if self._memory_extraction == "none":
            return
        if not self._memory_backend:
            return

        if self._memory_extraction == "causality_graph":
            self._extract_causality(tool_name, content)
        elif self._memory_extraction == "scratchpad":
            self._store_scratchpad(tool_name, content)
        elif self._memory_extraction == "structured_json":
            self._store_structured(tool_name, content)

    def _extract_causality(self, tool_name: str, content: str) -> None:
        """Extract causal relationships from tool output and store them.

        Uses the LLM to identify cause-effect patterns, then stores
        them via the memory backend.
        """
        if not self._memory_backend or not content.strip():
            return
        # Only attempt extraction for substantial outputs
        if len(content) < 50:
            return
        try:
            extract_messages = [
                Message(
                    role=Role.SYSTEM,
                    content=(
                        "Extract causal relationships from the following tool "
                        "output. Return a JSON array of objects with 'cause', "
                        "'effect', and 'confidence' fields. If no causal "
                        "relationships are found, return an empty array []."
                    ),
                ),
                Message(role=Role.USER, content=content[:4000]),
            ]
            result = self._generate(extract_messages)
            raw = result.get("content", "")
            # Try to parse JSON from the response
            raw = raw.strip()
            if raw.startswith("```"):
                # Strip code fences
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1] if len(lines) > 2 else lines)
            relations = json.loads(raw)
            if isinstance(relations, list):
                operator_prefix = (
                    f"monitor_operative:{self._operator_id}"
                    if self._operator_id
                    else "monitor_operative"
                )
                for rel in relations[:10]:  # Cap at 10 per extraction
                    if isinstance(rel, dict) and "cause" in rel and "effect" in rel:
                        key = f"{operator_prefix}:causality:{rel['cause'][:50]}"
                        value = json.dumps(rel)
                        try:
                            self._memory_backend.store(key, value)
                        except Exception as exc:
                            logger.debug(
                                "Failed to store causality relation in memory: %s",
                                exc,
                            )
        except (json.JSONDecodeError, Exception):
            logger.debug(
                "Causality extraction failed for tool %s output",
                tool_name,
            )

    def _store_scratchpad(self, tool_name: str, content: str) -> None:
        """Append content to a scratchpad entry in memory."""
        if not self._memory_backend:
            return
        operator_prefix = (
            f"monitor_operative:{self._operator_id}"
            if self._operator_id
            else "monitor_operative"
        )
        key = f"{operator_prefix}:scratchpad:{tool_name}"
        # Truncate long content
        snippet = content[:1000] if len(content) > 1000 else content
        try:
            self._memory_backend.store(key, snippet)
        except Exception:
            logger.debug("Could not store scratchpad for tool %s", tool_name)

    def _store_structured(self, tool_name: str, content: str) -> None:
        """Try to parse JSON from tool output and store structured data."""
        if not self._memory_backend:
            return
        operator_prefix = (
            f"monitor_operative:{self._operator_id}"
            if self._operator_id
            else "monitor_operative"
        )
        try:
            data = json.loads(content)
            key = f"{operator_prefix}:structured:{tool_name}"
            self._memory_backend.store(key, json.dumps(data))
        except (json.JSONDecodeError, TypeError):
            # Not JSON -- store as plain text truncated
            key = f"{operator_prefix}:structured:{tool_name}"
            try:
                self._memory_backend.store(key, content[:1000])
            except Exception as exc:
                logger.debug(
                    "Failed to store structured data for tool %s: %s",
                    tool_name,
                    exc,
                )

    # ------------------------------------------------------------------
    # State persistence (OperativeAgent pattern)
    # ------------------------------------------------------------------

    def _recall_state(self) -> str:
        """Retrieve previous state from memory backend."""
        if not self._memory_backend or not self._operator_id:
            return ""
        state_key = f"monitor_operative:{self._operator_id}:state"
        try:
            result = self._memory_backend.retrieve(state_key)
            if result:
                return result if isinstance(result, str) else str(result)
        except Exception:
            logger.debug(
                "No previous state for monitor_operative %s",
                self._operator_id,
            )
        return ""

    def _load_session(self) -> list[Message]:
        """Load recent session history for this operator."""
        if not self._session_store or not self._operator_id:
            return []
        session_id = f"monitor_operative:{self._operator_id}"
        try:
            session = self._session_store.get_or_create(session_id)
            if hasattr(session, "messages") and session.messages:
                recent = session.messages[-10:]
                return [
                    Message(
                        role=Role(m.get("role", "user")),
                        content=m.get("content", ""),
                    )
                    for m in recent
                    if isinstance(m, dict)
                ]
        except Exception:
            logger.debug(
                "Could not load session for monitor_operative %s",
                self._operator_id,
            )
        return []

    def _save_session(self, input_text: str, response: str) -> None:
        """Save the tick's prompt and response to the session store."""
        if not self._session_store or not self._operator_id:
            return
        session_id = f"monitor_operative:{self._operator_id}"
        try:
            self._session_store.save_message(
                session_id,
                {"role": "user", "content": input_text},
            )
            self._session_store.save_message(
                session_id,
                {"role": "assistant", "content": response},
            )
        except Exception:
            logger.debug(
                "Could not save session for monitor_operative %s",
                self._operator_id,
            )

    def _auto_persist_state(self, content: str) -> None:
        """Auto-persist a state summary if agent didn't store explicitly."""
        if not self._memory_backend or not self._operator_id:
            return
        state_key = f"monitor_operative:{self._operator_id}:state"
        try:
            summary = content[:1000] if content else ""
            self._memory_backend.store(state_key, summary)
        except Exception:
            logger.debug(
                "Could not auto-persist state for monitor_operative %s",
                self._operator_id,
            )


__all__ = ["MonitorOperativeAgent", "MONITOR_OPERATIVE_SYSTEM_PROMPT"]
