"""End-to-end identity context for one OpenJarvis task activity."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class TaskIdentity:
    """Stable IDs propagated through orchestration, Codex, tools, and traces."""

    task_id: str
    session_id: str
    correlation_id: str
    thread_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    approval_id: str | None = None
    action_id: str | None = None
    artifact_id: str | None = None

    def validated(self) -> TaskIdentity:
        for field_name in ("task_id", "session_id", "correlation_id"):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        for field_name in (
            "thread_id",
            "turn_id",
            "item_id",
            "approval_id",
            "action_id",
            "artifact_id",
        ):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} cannot be blank")
        return self

    def with_ids(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        item_id: str | None = None,
        approval_id: str | None = None,
        action_id: str | None = None,
        artifact_id: str | None = None,
    ) -> TaskIdentity:
        """Return a validated child identity while retaining parent IDs."""

        values = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "item_id": item_id,
            "approval_id": approval_id,
            "action_id": action_id,
            "artifact_id": artifact_id,
        }
        updates = {
            name: value
            for name, value in values.items()
            if value is not None
        }
        return replace(self, **updates).validated()

    def as_dict(self) -> dict[str, str | None]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "item_id": self.item_id,
            "approval_id": self.approval_id,
            "action_id": self.action_id,
            "artifact_id": self.artifact_id,
        }


__all__ = ["TaskIdentity"]
