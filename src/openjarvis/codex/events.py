"""Normalization of SDK and app-server messages into stable Codex events."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from openjarvis.codex.redaction import redact_data
from openjarvis.codex.store import CodexStateStore
from openjarvis.codex.types import (
    CodexBackendKind,
    CodexEvent,
    CodexEventType,
    CodexRunContext,
)

_DIRECT_EVENT_MAP = {
    "thread/started": CodexEventType.THREAD_STARTED,
    "thread/resumed": CodexEventType.THREAD_RESUMED,
    "thread/closed": CodexEventType.THREAD_CLOSED,
    "turn/started": CodexEventType.TURN_STARTED,
    "turn/plan/updated": CodexEventType.PLAN_UPDATED,
    "thread/tokenUsage/updated": CodexEventType.USAGE_UPDATED,
    "error": CodexEventType.ERROR,
    "approval/requested": CodexEventType.APPROVAL_REQUESTED,
    "approval/resolved": CodexEventType.APPROVAL_RESOLVED,
}
_ITEM_DELTA_METHODS = {
    "item/agentMessage/delta",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/textDelta",
    "item/fileChange/outputDelta",
}
_COMMAND_OUTPUT_METHODS = {
    "item/commandExecution/outputDelta",
    "command/exec/outputDelta",
}
_TOOL_ITEM_TYPES = {
    "mcpToolCall",
    "dynamicToolCall",
    "collabAgentToolCall",
}


class CodexEventAdapter:
    """Create ordered, redacted, deduplicated events for one state store."""

    def __init__(self, store: CodexStateStore) -> None:
        self._store = store

    def normalize(
        self,
        raw: Any,
        *,
        context: CodexRunContext,
        backend: CodexBackendKind,
        thread_id: str,
        turn_id: str | None = None,
    ) -> CodexEvent | None:
        """Normalize and persist one SDK notification or wire message."""

        method, params, explicit_event_id = self._unpack(raw)
        if explicit_event_id and self._store.has_event(explicit_event_id):
            return None

        event_type = self._event_type(method, params)
        actual_thread_id = self._find_id(params, "threadId", "thread_id") or thread_id
        actual_turn_id = (
            self._find_id(params, "turnId", "turn_id") or turn_id
        )
        if actual_turn_id is None:
            nested_turn = params.get("turn")
            if isinstance(nested_turn, dict):
                actual_turn_id = self._find_id(nested_turn, "id")
        item_id = self._find_id(params, "itemId", "item_id")
        if item_id is None:
            item = params.get("item")
            if isinstance(item, dict):
                item_id = self._find_id(item, "id")

        if event_type is CodexEventType.ERROR and method not in {
            "error",
            "turn/completed",
        }:
            payload: dict[str, Any] = {
                "source_event_type": method,
                "message": "Unsupported Codex event type was ignored safely",
            }
        else:
            payload = redact_data(params)

        sequence = self._store.next_sequence(actual_thread_id)
        event_id = explicit_event_id or self._derived_event_id(
            method=method,
            thread_id=actual_thread_id,
            turn_id=actual_turn_id,
            item_id=item_id,
            sequence=sequence,
        )
        event = CodexEvent(
            event_id=event_id,
            sequence=sequence,
            occurred_at=self._occurred_at(params),
            task_id=context.task_id,
            session_id=context.session_id,
            thread_id=actual_thread_id,
            turn_id=actual_turn_id,
            item_id=item_id,
            backend=backend,
            event_type=event_type,
            payload=payload,
        )
        if not self._store.save_event(event):
            return None
        return event

    def emit(
        self,
        event_type: CodexEventType,
        *,
        context: CodexRunContext,
        backend: CodexBackendKind,
        thread_id: str,
        turn_id: str | None = None,
        item_id: str | None = None,
        payload: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> CodexEvent | None:
        """Emit a backend-created lifecycle event through the same safeguards."""

        if event_id and self._store.has_event(event_id):
            return None
        sequence = self._store.next_sequence(thread_id)
        actual_event_id = event_id or self._derived_event_id(
            method=event_type.value,
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
            sequence=sequence,
        )
        event = CodexEvent(
            event_id=actual_event_id,
            sequence=sequence,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            task_id=context.task_id,
            session_id=context.session_id,
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
            backend=backend,
            event_type=event_type,
            payload=redact_data(payload or {}),
        )
        if not self._store.save_event(event):
            return None
        return event

    @staticmethod
    def _unpack(raw: Any) -> tuple[str, dict[str, Any], str | None]:
        if isinstance(raw, dict):
            method = str(raw.get("method") or raw.get("event_type") or "")
            payload = raw.get("params", raw.get("payload", {}))
            params = payload if isinstance(payload, dict) else {}
            event_id = raw.get("eventId") or raw.get("event_id")
            return method, dict(params), str(event_id) if event_id else None

        method = str(getattr(raw, "method", ""))
        payload = getattr(raw, "payload", {})
        if hasattr(payload, "model_dump"):
            dumped = payload.model_dump(mode="json", by_alias=True)
            params = dumped if isinstance(dumped, dict) else {}
        elif isinstance(payload, dict):
            params = dict(payload)
        else:
            params = {}
        event_id = getattr(raw, "event_id", None)
        return method, params, str(event_id) if event_id else None

    @classmethod
    def _event_type(
        cls,
        method: str,
        params: dict[str, Any],
    ) -> CodexEventType:
        if method == "turn/completed":
            turn = params.get("turn")
            status = turn.get("status") if isinstance(turn, dict) else None
            if status == "failed":
                return CodexEventType.TURN_FAILED
            if status == "interrupted":
                return CodexEventType.TURN_INTERRUPTED
            return CodexEventType.TURN_COMPLETED
        if method in _ITEM_DELTA_METHODS:
            return CodexEventType.ITEM_DELTA
        if method in _COMMAND_OUTPUT_METHODS:
            return CodexEventType.COMMAND_OUTPUT
        if method == "item/started":
            return cls._item_event_type(params, completed=False)
        if method == "item/completed":
            return cls._item_event_type(params, completed=True)
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            return CodexEventType.APPROVAL_REQUESTED
        return _DIRECT_EVENT_MAP.get(method, CodexEventType.ERROR)

    @staticmethod
    def _item_event_type(
        params: dict[str, Any],
        *,
        completed: bool,
    ) -> CodexEventType:
        item = params.get("item")
        item_type = item.get("type") if isinstance(item, dict) else None
        if item_type == "commandExecution":
            return (
                CodexEventType.COMMAND_COMPLETED
                if completed
                else CodexEventType.COMMAND_STARTED
            )
        if item_type == "fileChange":
            return (
                CodexEventType.FILE_CHANGE_APPLIED
                if completed
                else CodexEventType.FILE_CHANGE_PROPOSED
            )
        if item_type in _TOOL_ITEM_TYPES:
            return (
                CodexEventType.TOOL_COMPLETED
                if completed
                else CodexEventType.TOOL_STARTED
            )
        return (
            CodexEventType.ITEM_COMPLETED
            if completed
            else CodexEventType.ITEM_STARTED
        )

    @staticmethod
    def _find_id(data: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if value:
                return str(value)
        nested_turn = data.get("turn")
        if isinstance(nested_turn, dict):
            for key in keys:
                value = nested_turn.get(key)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _occurred_at(params: dict[str, Any]) -> str:
        for key in ("occurredAt", "occurred_at", "timestamp"):
            value = params.get(key)
            if isinstance(value, str) and value:
                return value
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _derived_event_id(
        *,
        method: str,
        thread_id: str,
        turn_id: str | None,
        item_id: str | None,
        sequence: int,
    ) -> str:
        entropy = uuid.uuid4().hex
        raw = json.dumps(
            [method, thread_id, turn_id, item_id, sequence, entropy],
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["CodexEventAdapter"]
