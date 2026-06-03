"""Tests for the macOS automation tool."""

from __future__ import annotations

from openjarvis.tools.mac_automation import MacAutomationTool


def test_spec_requires_confirmation_and_system_admin():
    spec = MacAutomationTool().spec

    assert spec.name == "mac_automation"
    assert spec.requires_confirmation is True
    assert "system:admin" in spec.required_capabilities
    assert "action" in spec.parameters["required"]


def test_missing_action_fails(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    result = MacAutomationTool().execute()

    assert not result.success
    assert "action" in result.content


def test_non_macos_fails(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")

    result = MacAutomationTool().execute(action="notify", message="hello")

    assert not result.success
    assert "macOS" in result.content


def test_build_notify_command():
    cmd = MacAutomationTool()._build_command(
        "notify",
        {"message": "hello", "title": "Jarvis"},
    )

    assert cmd[:2] == ["osascript", "-e"]
    assert "display notification" in cmd[2]
