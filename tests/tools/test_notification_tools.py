"""Tests for notification agent tools — mocked alert functions, no network."""

from __future__ import annotations

import pytest

from openjarvis.core.types import ToolCall
from openjarvis.notifications import alerts as alerts_mod
from openjarvis.tools import notification_tools as nt
from openjarvis.tools._stubs import ToolExecutor


@pytest.fixture
def ok(monkeypatch):
    """Force all underlying alert sends to succeed."""
    def _email(subject, message, **k):
        return alerts_mod.NotificationResult("email", True, detail="sent")

    def _sms(message, **k):
        return alerts_mod.NotificationResult("sms", True, detail="sent")

    def _push(title, message, **k):
        return alerts_mod.NotificationResult("push", True, detail="sent")

    monkeypatch.setattr(nt, "send_email_alert", _email)
    monkeypatch.setattr(nt, "send_sms_alert", _sms)
    monkeypatch.setattr(nt, "send_push_alert", _push)
    # the unified tool imports send_alert lazily from the package
    def _send_alert(title, message, *, channels=("push",)):
        return {c: alerts_mod.NotificationResult(c, True, detail="sent")
                for c in (["email", "sms", "push"] if "all" in channels else channels)}

    monkeypatch.setattr(alerts_mod, "send_alert", _send_alert, raising=False)
    import openjarvis.notifications as pkg
    monkeypatch.setattr(pkg, "send_alert", _send_alert, raising=False)
    yield


def test_notify_email_tool(ok):
    res = nt.NotifyEmailTool().execute(subject="Hi", message="Body")
    assert res.success is True
    assert res.metadata["channel"] == "email"


def test_notify_sms_tool(ok):
    res = nt.NotifySmsTool().execute(message="Done")
    assert res.success is True
    assert res.metadata["channel"] == "sms"


def test_notify_push_tool(ok):
    res = nt.NotifyPushTool().execute(title="T", message="M")
    assert res.success is True
    assert res.metadata["channel"] == "push"


def test_notify_unified_tool(ok):
    res = nt.NotifyTool().execute(title="T", message="M", channels=["push", "email"])
    assert res.success is True
    assert set(res.metadata["delivered"]) == {"push", "email"}


def test_notify_tools_require_send_capability():
    tool_classes = (
        nt.NotifyEmailTool,
        nt.NotifySmsTool,
        nt.NotifyPushTool,
        nt.NotifyTool,
    )
    for tool_cls in tool_classes:
        spec = tool_cls().spec
        assert "channel:send" in spec.required_capabilities
        assert spec.category == "notification"
        assert spec.requires_confirmation is True


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (nt.NotifyEmailTool(), '{"subject":"Hi","message":"Body"}'),
        (nt.NotifySmsTool(), '{"message":"Done"}'),
        (nt.NotifyPushTool(), '{"title":"Hi","message":"Done"}'),
        (nt.NotifyTool(), '{"title":"Hi","message":"Done"}'),
    ],
)
def test_notification_send_is_blocked_when_confirmation_denied(
    ok, monkeypatch, tool, arguments
):
    calls = []
    original_execute = tool.execute

    def tracked_execute(**params):
        calls.append(params)
        return original_execute(**params)

    monkeypatch.setattr(tool, "execute", tracked_execute)
    executor = ToolExecutor(
        [tool],
        interactive=True,
        confirm_callback=lambda prompt: False,
    )

    result = executor.execute(
        ToolCall(id="notification", name=tool.spec.name, arguments=arguments)
    )

    assert result.success is False
    assert "denied by user" in result.content
    assert calls == []


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (nt.NotifyEmailTool(), '{"subject":"Hi","message":"Body"}'),
        (nt.NotifySmsTool(), '{"message":"Done"}'),
        (nt.NotifyPushTool(), '{"title":"Hi","message":"Done"}'),
        (nt.NotifyTool(), '{"title":"Hi","message":"Done"}'),
    ],
)
def test_notification_send_runs_after_confirmation(ok, tool, arguments):
    prompts = []
    executor = ToolExecutor(
        [tool],
        interactive=True,
        confirm_callback=lambda prompt: prompts.append(prompt) or True,
    )

    result = executor.execute(
        ToolCall(id="notification", name=tool.spec.name, arguments=arguments)
    )

    assert result.success is True
    assert len(prompts) == 1
    assert tool.spec.name in prompts[0]


def test_notify_tool_reports_failure_cleanly(monkeypatch):
    """A failed send yields success=False with the clean error, no exception."""
    def _failing(title, message, *, channels=("push",)):
        return {"push": alerts_mod.NotificationResult(
            "push", False, error="Push not configured."
        )}

    import openjarvis.notifications as pkg
    monkeypatch.setattr(pkg, "send_alert", _failing, raising=False)

    res = nt.NotifyTool().execute(title="T", message="M", channels=["push"])
    assert res.success is False
    assert "Push not configured." in res.content
