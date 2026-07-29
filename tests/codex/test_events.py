from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openjarvis.codex import (
    ApprovalMode,
    CodexBackendKind,
    CodexEventAdapter,
    CodexEventType,
    CodexModelConfig,
    CodexRunContext,
    CodexStateStore,
    CodexThreadRecord,
    SandboxMode,
)


def _context(tmp_path: Path) -> CodexRunContext:
    return CodexRunContext(
        task_id="task-1",
        session_id="session-1",
        correlation_id="correlation-1",
        cwd=tmp_path,
        sandbox=SandboxMode.READ_ONLY,
        approval_mode=ApprovalMode.DENY_ALL,
        model=CodexModelConfig(model=None, effort=None, service_tier=None),
        timeout_seconds=30,
        step_limit=10,
        token_limit=None,
        developer_instructions=None,
        isolated_workspace=None,
    )


def _adapter(tmp_path: Path) -> tuple[CodexStateStore, CodexEventAdapter]:
    store = CodexStateStore(tmp_path / "codex.db")
    now = datetime.now(timezone.utc).isoformat()
    store.save_thread(
        CodexThreadRecord(
            task_id="task-1",
            session_id="session-1",
            correlation_id="correlation-1",
            thread_id="thread-1",
            backend=CodexBackendKind.PYTHON_SDK,
            sandbox=SandboxMode.READ_ONLY,
            approval_mode=ApprovalMode.DENY_ALL,
            cwd=str(tmp_path),
            model_config={},
            status="started",
            created_at=now,
            updated_at=now,
        )
    )
    return store, CodexEventAdapter(store)


def test_event_ordering_and_deduplication(tmp_path: Path) -> None:
    store, adapter = _adapter(tmp_path)
    context = _context(tmp_path)
    first = adapter.normalize(
        {
            "method": "turn/started",
            "eventId": "upstream-event-1",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1"},
            },
        },
        context=context,
        backend=CodexBackendKind.PYTHON_SDK,
        thread_id="thread-1",
    )
    duplicate = adapter.normalize(
        {
            "method": "turn/started",
            "eventId": "upstream-event-1",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1"},
            },
        },
        context=context,
        backend=CodexBackendKind.PYTHON_SDK,
        thread_id="thread-1",
    )
    second = adapter.normalize(
        {
            "method": "turn/plan/updated",
            "eventId": "upstream-event-2",
            "params": {"threadId": "thread-1", "turnId": "turn-1", "plan": []},
        },
        context=context,
        backend=CodexBackendKind.PYTHON_SDK,
        thread_id="thread-1",
    )

    assert first is not None and first.sequence == 1
    assert duplicate is None
    assert second is not None and second.sequence == 2
    assert [event.sequence for event in store.list_events("thread-1")] == [1, 2]
    store.close()


def test_required_lifecycle_mappings(tmp_path: Path) -> None:
    store, adapter = _adapter(tmp_path)
    context = _context(tmp_path)
    cases = [
        ("thread/started", CodexEventType.THREAD_STARTED, {}),
        ("thread/resumed", CodexEventType.THREAD_RESUMED, {}),
        ("thread/closed", CodexEventType.THREAD_CLOSED, {}),
        ("turn/started", CodexEventType.TURN_STARTED, {}),
        (
            "turn/completed",
            CodexEventType.TURN_COMPLETED,
            {"turn": {"status": "completed"}},
        ),
        (
            "turn/completed",
            CodexEventType.TURN_FAILED,
            {"turn": {"status": "failed"}},
        ),
        (
            "turn/completed",
            CodexEventType.TURN_INTERRUPTED,
            {"turn": {"status": "interrupted"}},
        ),
        ("item/agentMessage/delta", CodexEventType.ITEM_DELTA, {}),
        ("turn/plan/updated", CodexEventType.PLAN_UPDATED, {}),
        (
            "item/commandExecution/outputDelta",
            CodexEventType.COMMAND_OUTPUT,
            {},
        ),
        (
            "item/commandExecution/requestApproval",
            CodexEventType.APPROVAL_REQUESTED,
            {},
        ),
        ("approval/resolved", CodexEventType.APPROVAL_RESOLVED, {}),
        ("thread/tokenUsage/updated", CodexEventType.USAGE_UPDATED, {}),
        ("error", CodexEventType.ERROR, {}),
    ]

    for index, (method, expected, extra) in enumerate(cases):
        params = {"threadId": "thread-1", "turnId": "turn-1", **extra}
        event = adapter.normalize(
            {
                "method": method,
                "eventId": f"event-{index}",
                "params": params,
            },
            context=context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id="thread-1",
        )
        assert event is not None
        assert event.event_type is expected
    store.close()


def test_item_types_map_to_command_file_and_tool_events(tmp_path: Path) -> None:
    store, adapter = _adapter(tmp_path)
    context = _context(tmp_path)
    cases = [
        ("commandExecution", False, CodexEventType.COMMAND_STARTED),
        ("commandExecution", True, CodexEventType.COMMAND_COMPLETED),
        ("fileChange", False, CodexEventType.FILE_CHANGE_PROPOSED),
        ("fileChange", True, CodexEventType.FILE_CHANGE_APPLIED),
        ("mcpToolCall", False, CodexEventType.TOOL_STARTED),
        ("mcpToolCall", True, CodexEventType.TOOL_COMPLETED),
        ("agentMessage", False, CodexEventType.ITEM_STARTED),
        ("agentMessage", True, CodexEventType.ITEM_COMPLETED),
    ]

    for index, (item_type, completed, expected) in enumerate(cases):
        method = "item/completed" if completed else "item/started"
        event = adapter.normalize(
            {
                "method": method,
                "eventId": f"item-event-{index}",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"id": f"item-{index}", "type": item_type},
                },
            },
            context=context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id="thread-1",
        )
        assert event is not None
        assert event.event_type is expected
        assert event.item_id == f"item-{index}"
    store.close()


def test_unknown_event_is_handled_without_forwarding_payload(tmp_path: Path) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    store, adapter = _adapter(tmp_path)
    event = adapter.normalize(
        {
            "method": "future/unknown",
            "params": {
                "threadId": "thread-1",
                "accessToken": secret,
                "untrusted": "data",
            },
        },
        context=_context(tmp_path),
        backend=CodexBackendKind.APP_SERVER,
        thread_id="thread-1",
    )

    assert event is not None
    assert event.event_type is CodexEventType.ERROR
    assert event.payload == {
        "source_event_type": "future/unknown",
        "message": "Unsupported Codex event type was ignored safely",
    }
    assert secret.encode() not in (tmp_path / "codex.db").read_bytes()
    store.close()
