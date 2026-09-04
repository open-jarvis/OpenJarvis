"""Regression tests for proactive pending-action execution."""

from __future__ import annotations

import json

import pytest

from openjarvis.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_EXECUTED,
    TIER_LOW,
    ApprovalStore,
)
from openjarvis.tools.proactive_tools import ExecutePendingActionsTool, QueueActionTool


def _approved_sms_draft(store: ApprovalStore, payload: dict[str, str]):
    action = store.queue_action(
        action_type="sms_draft_reply",
        description="Reply to the message",
        payload=payload,
        permission_key="sms_draft_reply:contact:+15551234567",
        tier=TIER_LOW,
    )
    store.update_status(action.id, STATUS_APPROVED)
    return action


def test_sms_draft_uses_documented_body_and_marks_success(tmp_path) -> None:
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    action = _approved_sms_draft(
        store,
        {
            "contact": "+15551234567",
            "body": "Sounds good, see you tomorrow.",
        },
    )

    result = ExecutePendingActionsTool(store=store).execute()
    entry = json.loads(result.content)[0]

    assert entry["success"] is True
    assert entry["message"] == (
        "Draft for +15551234567: Sounds good, see you tomorrow."
    )
    persisted = store.get_action(action.id)
    assert persisted is not None
    assert persisted.status == STATUS_EXECUTED
    assert persisted.payload["body"] == "Sounds good, see you tomorrow."
    assert result.metadata == {"attempted": 1, "executed": 1, "failed": 0}
    store.close()


def test_invalid_sms_draft_does_not_report_or_mark_success(tmp_path) -> None:
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    action = _approved_sms_draft(
        store,
        {"contact": "+15551234567", "body": " \n"},
    )

    result = ExecutePendingActionsTool(store=store).execute()
    entry = json.loads(result.content)[0]

    assert entry["success"] is False
    assert entry["message"] == "Missing body in payload"
    assert result.success is False
    assert result.metadata == {"attempted": 1, "executed": 0, "failed": 1}
    persisted = store.get_action(action.id)
    assert persisted is not None
    assert persisted.status == STATUS_APPROVED
    store.close()


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        ({"contact": None, "body": "hello"}, "Missing contact in payload"),
        ({"contact": 15551234567, "body": "hello"}, "Missing contact in payload"),
        ({"contact": "+15551234567", "body": None}, "Missing body in payload"),
        ({"contact": "+15551234567", "body": ["hello"]}, "Missing body in payload"),
    ],
)
def test_non_string_sms_fields_are_not_executed(
    tmp_path, payload, expected_message
) -> None:
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    action = _approved_sms_draft(store, payload)

    result = ExecutePendingActionsTool(store=store).execute()
    entry = json.loads(result.content)[0]

    assert result.success is False
    assert entry["success"] is False
    assert entry["message"] == expected_message
    assert result.metadata == {"attempted": 1, "executed": 0, "failed": 1}
    persisted = store.get_action(action.id)
    assert persisted is not None
    assert persisted.status == STATUS_APPROVED
    store.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"contact": None, "body": "hello"},
        {"contact": 15551234567, "body": "hello"},
        {"contact": " \n", "body": "hello"},
        {"contact": "+15551234567", "body": None},
        {"contact": "+15551234567", "body": ["hello"]},
        {"contact": "+15551234567", "body": " \n"},
    ],
)
def test_invalid_sms_draft_is_rejected_before_queueing(tmp_path, payload) -> None:
    store = ApprovalStore(str(tmp_path / "approvals.db"))

    result = QueueActionTool(store=store).execute(
        action_type="sms_draft_reply",
        description="Reply to the message",
        payload=payload,
        permission_key="sms_draft_reply:contact:+15551234567",
        tier=TIER_LOW,
    )

    assert result.success is False
    assert result.metadata == {"status": "rejected"}
    assert store.list_pending() == []
    assert store.list_approved() == []
    store.close()
