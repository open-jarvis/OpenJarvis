"""OperativeAgent — persistent, scheduled agent for autonomous operation.

Extends ToolUsingAgent with built-in session persistence and state recall.
Designed for Operators: autonomous agents that run on a schedule with
automatic state management between ticks.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, List, Optional

from openjarvis.agents._stubs import (
    AgentContext,
    AgentResult,
    ToolUsingAgent,
    stage_agent_persistence,
)
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)


@AgentRegistry.register("operative")
class OperativeAgent(ToolUsingAgent):
    """Persistent autonomous agent with built-in state management.

    The Operative agent extends the standard tool-calling loop with:

    1. **Session loading** — restores conversation history from previous ticks.
    2. **State recall** — retrieves previous state JSON from memory backend.
    3. **System prompt** — injects the operator's protocol instructions.
    4. **Tool loop** — standard function-calling loop (same as Orchestrator).
    5. **Session save** — persists the tick's prompt and response.
    6. **State persistence** — auto-persists state if the agent didn't do it
       explicitly via memory_store tool.
    """

    agent_id = "operative"
    accepts_tools = True
    _default_temperature = 0.3
    _default_max_tokens = 2048
    _default_max_turns = 20

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
        operator_id: Optional[str] = None,
        session_store: Optional[Any] = None,
        memory_backend: Optional[Any] = None,
        interactive: bool = False,
        confirm_callback=None,
        capability_policy: Any = None,
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
            prompt_builder=kwargs.get("prompt_builder"),
            capability_policy=capability_policy,
        )
        self._system_prompt = system_prompt or ""
        self._operator_id = operator_id
        self._session_store = session_store
        self._memory_backend = memory_backend

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute a single operator tick."""
        self._emit_turn_start(input)
        loop_guard = self._new_loop_guard()

        # 1. Build system prompt with state context
        sys_parts: list[str] = []
        if self._system_prompt:
            sys_parts.append(self._system_prompt)

        # 2. State recall from memory backend
        previous_state = self._recall_state()
        if previous_state:
            sys_parts.append(f"\n## Previous State\n{previous_state}")

        system_prompt = "\n\n".join(sys_parts) if sys_parts else None
        # Honor SOUL.md / MEMORY.md / USER.md persona files like `jarvis ask`,
        # appended so the operative's own instructions are preserved (#376).
        system_prompt = self._apply_persona(system_prompt)

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

            if loop_guard:
                messages = loop_guard.compress_context(messages)

            gen_kwargs: dict[str, Any] = {}
            if openai_tools:
                gen_kwargs["tools"] = openai_tools

            result = self._generate(messages, **gen_kwargs)
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])

            if not raw_tool_calls:
                content = self._check_continuation(result, messages)
                break

            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
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
                # Loop guard check
                if loop_guard:
                    verdict = loop_guard.check_call(
                        tc.name,
                        tc.arguments,
                        polling=self._tool_is_polling(tc.name),
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

                # Track if agent stored state via memory_store
                if tc.name == "memory_store" and self._operator_id:
                    try:
                        args = json.loads(tc.arguments)
                        state_key = f"{self.agent_id}:{self._operator_id}:state"
                        if args.get("source", "") == state_key:
                            state_stored_by_tool = True
                    except (json.JSONDecodeError, TypeError):
                        pass

                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
        else:
            # Max turns exceeded
            self._save_session(input, content)
            meta = dict(total_usage)
            meta["max_turns_exceeded"] = True
            return AgentResult(
                content=content or "Maximum turns reached without a final answer.",
                tool_results=all_tool_results,
                turns=turns,
                metadata=meta,
            )

        # 6. Save session
        self._save_session(input, content)

        # 7. Auto-persist state if agent didn't do it explicitly
        if not state_stored_by_tool:
            self._auto_persist_state(content)

        self._emit_turn_end(turns=turns, content_length=len(content))
        return AgentResult(
            content=content,
            tool_results=all_tool_results,
            turns=turns,
            metadata=total_usage,
        )

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
        # Inject session history (recent messages from previous ticks)
        if session_messages:
            messages.extend(session_messages)
        # Context conversation (e.g. memory injection)
        if context and context.conversation.messages:
            messages.extend(context.conversation.messages)
        messages.append(Message(role=Role.USER, content=input))
        return messages

    def _recall_state(self) -> str:
        """Retrieve previous operator state from memory backend."""
        if not self._memory_backend or not self._operator_id:
            return ""
        state_key = f"{self.agent_id}:{self._operator_id}:state"
        results = self._memory_backend.retrieve(state_key, top_k=20)
        matching = [
            result
            for result in results
            if result.source == state_key
            or result.metadata.get("state_key") == state_key
        ]
        if not matching:
            return ""

        def _updated_at(result: Any) -> float:
            try:
                timestamp = float(
                    result.metadata.get("updated_at", float("-inf"))
                )
            except (TypeError, ValueError):
                return float("-inf")
            return timestamp if math.isfinite(timestamp) else float("-inf")

        newest = max(
            matching,
            key=_updated_at,
        )
        return newest.content

    def _load_session(self) -> list[Message]:
        """Load recent session history for this operator."""
        if not self._session_store or not self._operator_id:
            return []
        session = self._session_store.get_or_create(
            f"{self.agent_id}:{self._operator_id}"
        )
        return [
            Message(role=Role(message.role), content=message.content)
            for message in session.messages[-10:]
        ]

    def _save_session(self, input_text: str, response: str) -> None:
        """Save the tick's prompt and response to the session store.

        The prompt is durable as soon as it is asked; the answer is staged, so
        a turn the caller never accepts leaves no assistant message behind.
        """
        if not self._session_store or not self._operator_id:
            return
        session = self._session_store.get_or_create(
            f"{self.agent_id}:{self._operator_id}"
        )
        self._session_store.save_message(
            session.session_id, "user", input_text, channel="agent"
        )
        stage_agent_persistence(
            lambda: self._session_store.save_message(
                session.session_id, "assistant", response, channel="agent"
            )
        )

    def _auto_persist_state(self, content: str) -> None:
        """Auto-persist a state summary if the agent didn't store state explicitly."""
        if not self._memory_backend or not self._operator_id or not content.strip():
            return
        state_key = f"{self.agent_id}:{self._operator_id}:state"
        # Stamped now rather than at commit, so recall orders states by when
        # the answer was produced.
        updated_at = time.time()
        stage_agent_persistence(
            lambda: self._memory_backend.store(
                content[:1000],
                source=state_key,
                metadata={
                    "state_key": state_key,
                    "operator_id": self._operator_id,
                    "updated_at": updated_at,
                },
            )
        )


__all__ = ["OperativeAgent"]
