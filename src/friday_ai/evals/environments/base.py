"""Abstract base for multi-turn task environments."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from friday_ai.evals.core.types import EvalRecord

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return _THINK_TAG_RE.sub("", text).strip()


def _format_messages(messages: List[Dict[str, str]]) -> str:
    """Format a message list as a single prompt string with role labels."""
    parts: List[str] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            continue
        elif role == "user":
            parts.append(f"[User]\n{content}")
        elif role == "assistant":
            parts.append(f"[Assistant]\n{content}")
    parts.append("[Assistant]")
    return "\n\n".join(parts)


class TaskEnvironment(ABC):
    """Environment for multi-turn interactive evaluation.

    Subclasses implement the reset/step/evaluate lifecycle:
    1. ``reset(record)`` — initialize the environment, return initial observation
    2. ``step(agent_response)`` — parse agent action, execute, return feedback
    3. ``evaluate()`` — assess final state, return (is_correct, metadata)
    4. ``close()`` — release resources
    """

    @abstractmethod
    def reset(self, record: EvalRecord) -> str:
        """Initialize environment for a record.

        Returns the initial observation/context for the agent (e.g. schema
        description, entity list, task instructions).
        """

    @abstractmethod
    def step(self, agent_response: str) -> Tuple[str, bool]:
        """Process an agent response.

        Returns:
            observation: Feedback text to show the agent (e.g. SQL result,
                API return value, bash output).
            is_done: True if the agent signaled completion (e.g. ``Action:
                Answer``, ``Final Answer:``, ``Act: finish``).
        """

    @abstractmethod
    def evaluate(self) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Evaluate the final state after interaction completes.

        Returns:
            is_correct: True/False/None (None = not scorable).
            metadata: Scoring details dict.
        """

    @property
    def max_turns(self) -> int:
        """Maximum interaction turns for this environment.

        Subclasses should override to match the original benchmark's
        per-task-type turn limits.  Default: 15.
        """
        return 15

    def close(self) -> None:
        """Release resources (Docker containers, DB connections, etc.)."""

    def __enter__(self) -> "TaskEnvironment":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def run_agent_loop(
        self,
        generate_fn: Any,
        record: "EvalRecord",
    ) -> str:
        """Run the full reset → [generate → step] × N → evaluate cycle.

        Called by AgenticRunner for environments that use the
        reset/step/evaluate protocol instead of one-shot generation.

        Maintains full conversation history across turns so the agent
        retains context.  Strips ``<think>`` tags from agent responses
        before passing to ``step()``.

        After completion, sets on ``self``:
        - ``last_eval_result``: ``(is_correct, metadata)``
        - ``all_responses``: list of raw agent responses per turn
        - ``turn_wall_clocks``: list of per-turn wall clock seconds
        - ``interaction_history``: message list (for lifelong injection)
        """
        self.reset(record)

        messages: List[Dict[str, str]] = []

        # Use the full record.problem as the first user message — it
        # already contains the system prompt, schema, and task instruction.
        messages.append({"role": "user", "content": record.problem})

        all_responses: List[str] = []
        turn_wall_clocks: List[float] = []
        last_response = ""

        for _ in range(self.max_turns):
            prompt = _format_messages(messages)

            t0 = time.time()
            last_response = generate_fn(prompt)
            turn_wall = time.time() - t0

            all_responses.append(last_response)
            turn_wall_clocks.append(turn_wall)

            cleaned = _strip_think_tags(last_response)
            messages.append({"role": "assistant", "content": cleaned})

            obs, done = self.step(cleaned)
            messages.append({"role": "user", "content": obs})

            if done:
                break

        self.last_eval_result: Optional[Tuple[Optional[bool], Dict[str, Any]]] = (
            self.evaluate()
        )
        self.all_responses: List[str] = all_responses
        self.turn_wall_clocks: List[float] = turn_wall_clocks
        self.interaction_history: List[Dict[str, str]] = [
            msg for msg in messages if msg.get("role") != "system"
        ]
        return last_response


__all__ = ["TaskEnvironment"]
