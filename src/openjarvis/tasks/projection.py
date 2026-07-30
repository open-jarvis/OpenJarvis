"""Projection of normalized Codex events into OpenJarvis runtime state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openjarvis.codex.redaction import redact_data
from openjarvis.codex.types import CodexEvent, CodexEventType
from openjarvis.core.events import EventBus, EventType
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import TaskArtifact, TaskEvent
from openjarvis.traces.store import TraceStore


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """Result of one idempotent Codex event projection."""

    event: TaskEvent
    inserted: bool
    trace_projected: bool
    artifact: TaskArtifact | None = None


class CodexTaskEventProjector:
    """Persist first, then project bounded events to traces and the live bus."""

    def __init__(
        self,
        store: TaskStore,
        *,
        bus: EventBus | None = None,
        trace_store: TraceStore | None = None,
        max_payload_bytes: int = 16_384,
        command_artifact_threshold: int = 4_096,
        preview_chars: int = 1_024,
    ) -> None:
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")
        if command_artifact_threshold <= 0:
            raise ValueError("command_artifact_threshold must be positive")
        if preview_chars <= 0:
            raise ValueError("preview_chars must be positive")
        self._store = store
        self._bus = bus
        self._trace_store = trace_store
        self._max_payload_bytes = max_payload_bytes
        self._command_artifact_threshold = command_artifact_threshold
        self._preview_chars = preview_chars

    def project(self, event: CodexEvent) -> ProjectionResult:
        """Project one normalized event without allowing it to change task state."""

        task = self._store.get_task(event.task_id)
        if task is None:
            raise KeyError(f"unknown task: {event.task_id}")
        if task.session_id != event.session_id:
            raise ValueError("Codex event session does not own the task")

        payload, artifact = self._bounded_payload(event)
        task_event, inserted = self._store.append_event(
            task_id=event.task_id,
            source_event_id=event.event_id,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
            cause="codex_event",
            component="codex_event_projector",
            thread_id=event.thread_id,
            turn_id=event.turn_id,
            item_id=event.item_id,
            artifact_id=artifact.artifact_id if artifact else None,
            schema_version=event.schema_version,
            payload=payload,
        )

        if event.item_id:
            self._store.save_item(
                item_id=event.item_id,
                task_id=event.task_id,
                session_id=event.session_id,
                thread_id=event.thread_id,
                turn_id=event.turn_id or "thread-level",
                item_type=self._item_type(event),
                status=self._item_status(event.event_type),
                sequence=event.sequence,
                source_event_id=event.event_id,
                payload=payload,
                occurred_at=event.occurred_at,
            )

        trace_projected = False
        if self._trace_store is not None:
            trace_projected = self._trace_store.save_task_event(task_event)
            if not trace_projected:
                trace_projected = any(
                    row["event_id"] == task_event.event_id
                    for row in self._trace_store.list_task_events(task_event.task_id)
                )

        if inserted and self._bus is not None:
            self._bus.publish(
                EventType.CODEX_EVENT,
                {
                    "event_id": task_event.event_id,
                    "source_event_id": event.event_id,
                    "task_id": task_event.task_id,
                    "session_id": task_event.session_id,
                    "correlation_id": task_event.correlation_id,
                    "thread_id": task_event.thread_id,
                    "turn_id": task_event.turn_id,
                    "item_id": task_event.item_id,
                    "artifact_id": task_event.artifact_id,
                    "sequence": task_event.sequence,
                    "event_type": task_event.event_type,
                    "occurred_at": task_event.occurred_at,
                    "schema_version": task_event.schema_version,
                    "payload": dict(task_event.payload),
                },
            )

        return ProjectionResult(
            event=task_event,
            inserted=inserted,
            trace_projected=trace_projected,
            artifact=artifact,
        )

    def _bounded_payload(
        self,
        event: CodexEvent,
    ) -> tuple[dict[str, Any], TaskArtifact | None]:
        safe = redact_data(dict(event.payload))
        encoded = json.dumps(
            safe,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        is_command_output = event.event_type is CodexEventType.COMMAND_OUTPUT
        if is_command_output and len(encoded) > self._command_artifact_threshold:
            artifact = self._store.save_artifact(
                task_id=event.task_id,
                artifact_id=f"command-{event.event_id}",
                kind="command_output",
                media_type="application/json",
                content=encoded,
                metadata={
                    "source_event_id": event.event_id,
                    "thread_id": event.thread_id,
                    "turn_id": event.turn_id,
                    "item_id": event.item_id,
                },
            )
            preview = encoded.decode("utf-8", errors="replace")[: self._preview_chars]
            return (
                {
                    "artifact_id": artifact.artifact_id,
                    "byte_size": artifact.byte_size,
                    "sha256": artifact.sha256,
                    "preview": preview,
                    "truncated": True,
                },
                artifact,
            )
        if len(encoded) > self._max_payload_bytes:
            return (
                {
                    "preview": encoded.decode("utf-8", errors="replace")[
                        : self._preview_chars
                    ],
                    "original_byte_size": len(encoded),
                    "truncated": True,
                },
                None,
            )
        return dict(safe), None

    @staticmethod
    def _item_type(event: CodexEvent) -> str:
        item = event.payload.get("item")
        if isinstance(item, dict) and item.get("type"):
            return str(item["type"])
        return event.event_type.value.split(".", 1)[0]

    @staticmethod
    def _item_status(event_type: CodexEventType) -> str:
        if event_type.value.endswith(".completed") or event_type in {
            CodexEventType.FILE_CHANGE_APPLIED,
        }:
            return "completed"
        if event_type.value.endswith(".proposed"):
            return "proposed"
        if (
            event_type.value.endswith(".delta")
            or event_type is CodexEventType.COMMAND_OUTPUT
        ):
            return "running"
        return "started"


__all__ = ["CodexTaskEventProjector", "ProjectionResult"]
