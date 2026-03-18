from __future__ import annotations

from typing import Any, List

from openjarvis.core.types import Message


class SessionExpiryHook:
    """Proactive memory flush before session reset."""

    FLUSH_PROMPT = (
        "This session is about to be reset. Review the conversation below "
        "and save anything important to memory or skills. Use memory_manage "
        "to save facts/preferences and skill_manage to save reusable procedures."
    )

    def __init__(self, executor: Any, flush_min_turns: int = 6) -> None:
        self._executor = executor
        self._flush_min_turns = flush_min_turns

    def on_session_expiry(self, session_id: str, messages: List[Message]) -> None:
        if len(messages) < self._flush_min_turns:
            return
        transcript = "\n".join(f"[{m.role}]: {m.content}" for m in messages)
        input_text = f"{self.FLUSH_PROMPT}\n\n---\n\n{transcript}"
        self._executor.run_ephemeral(
            agent_type="simple",
            system_prompt=(
                "You are a memory management agent. "
                "Save important information."
            ),
            input_text=input_text,
            tools=["memory_manage", "skill_manage"],
        )
