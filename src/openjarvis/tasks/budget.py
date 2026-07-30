"""Separate turn and task token budgets for Codex execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openjarvis.codex.types import CodexEvent
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import TaskUsage


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """Configurable limits with realistic Codex context defaults."""

    max_turn_duration: float = 300.0
    max_steps: int = 100
    max_input_tokens: int = 200_000
    max_output_tokens: int = 32_000
    max_total_tokens_per_task: int = 500_000
    warning_threshold: float = 0.8
    hard_limit_action: str = "interrupt"

    def validated(self) -> BudgetLimits:
        if self.max_turn_duration <= 0:
            raise ValueError("max_turn_duration must be positive")
        for name in (
            "max_steps",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens_per_task",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 < self.warning_threshold < 1:
            raise ValueError("warning_threshold must be between 0 and 1")
        if self.hard_limit_action != "interrupt":
            raise ValueError("Phase 3 hard_limit_action must be 'interrupt'")
        return self


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    """Result of evaluating one usage event."""

    usage: TaskUsage
    warning: bool
    hard_exceeded: bool
    reason: str | None


class BudgetController:
    """Parse usage events, persist snapshots, and evaluate trusted limits."""

    def __init__(self, store: TaskStore, limits: BudgetLimits | None = None) -> None:
        self._store = store
        self.limits = (limits or BudgetLimits()).validated()

    def observe(
        self,
        *,
        task_id: str,
        turn_id: str,
        event: CodexEvent,
    ) -> BudgetDecision:
        turn_input, turn_output, thread_input, thread_output = self._extract(
            dict(event.payload)
        )
        existing = self._store.get_usage(task_id, turn_id)
        previous_turn_input = existing.turn_input_tokens if existing else 0
        previous_turn_output = existing.turn_output_tokens if existing else 0
        effective_turn_input = max(previous_turn_input, turn_input)
        effective_turn_output = max(previous_turn_output, turn_output)

        other_task_total = sum(
            usage.turn_input_tokens + usage.turn_output_tokens
            for usage in self._store.list_usage(task_id)
            if usage.turn_id != turn_id
        )
        task_total = (
            other_task_total + effective_turn_input + effective_turn_output
        )
        if thread_input or thread_output:
            task_total = max(task_total, thread_input + thread_output)

        checks = {
            "max_input_tokens": (
                effective_turn_input,
                self.limits.max_input_tokens,
            ),
            "max_output_tokens": (
                effective_turn_output,
                self.limits.max_output_tokens,
            ),
            "max_total_tokens_per_task": (
                task_total,
                self.limits.max_total_tokens_per_task,
            ),
        }
        hard_reasons = [
            name for name, (value, limit) in checks.items() if value > limit
        ]
        warning_reasons = [
            name
            for name, (value, limit) in checks.items()
            if value >= int(limit * self.limits.warning_threshold)
        ]
        hard = bool(hard_reasons)
        warning = bool(warning_reasons) or hard
        reason = ",".join(hard_reasons or warning_reasons) or None
        usage = self._store.save_usage(
            task_id=task_id,
            turn_id=turn_id,
            turn_input_tokens=effective_turn_input,
            turn_output_tokens=effective_turn_output,
            thread_input_tokens=thread_input,
            thread_output_tokens=thread_output,
            warning=warning,
            hard_exceeded=hard,
            reason=reason,
            source_event_id=event.event_id,
        )
        return BudgetDecision(
            usage=usage,
            warning=warning,
            hard_exceeded=hard,
            reason=reason,
        )

    @classmethod
    def _extract(cls, payload: dict[str, Any]) -> tuple[int, int, int, int]:
        turn_block = cls._dict_value(payload, "turn", "last", "turn_usage")
        thread_block = cls._dict_value(
            payload,
            "total",
            "cumulative",
            "thread",
            "thread_usage",
        )
        if turn_block is None:
            usage = payload.get("usage")
            turn_block = usage if isinstance(usage, dict) else payload
        turn_input = cls._token_value(
            turn_block,
            "input_tokens",
            "inputTokens",
            "prompt_tokens",
            "promptTokens",
        )
        turn_output = cls._token_value(
            turn_block,
            "output_tokens",
            "outputTokens",
            "completion_tokens",
            "completionTokens",
        )
        thread_input = cls._token_value(
            thread_block or {},
            "input_tokens",
            "inputTokens",
            "prompt_tokens",
            "promptTokens",
        )
        thread_output = cls._token_value(
            thread_block or {},
            "output_tokens",
            "outputTokens",
            "completion_tokens",
            "completionTokens",
        )
        return turn_input, turn_output, thread_input, thread_output

    @staticmethod
    def _dict_value(
        payload: dict[str, Any],
        *keys: str,
    ) -> dict[str, Any] | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _token_value(payload: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return 0


__all__ = ["BudgetController", "BudgetDecision", "BudgetLimits"]
