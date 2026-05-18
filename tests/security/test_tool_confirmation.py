"""Tests for tool confirmation enforcement in ToolExecutor."""

from __future__ import annotations

from typing import Any

from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# ---------------------------------------------------------------------------
# Test tool helpers
# ---------------------------------------------------------------------------


class _SafeTool(BaseTool):
    """Tool that does NOT require confirmation."""

    tool_id = "safe"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="safe",
            description="A safe tool.",
            requires_confirmation=False,
        )

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(tool_name="safe", content="safe result", success=True)


class _DangerousTool(BaseTool):
    """Tool that REQUIRES confirmation."""

    tool_id = "dangerous"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="dangerous",
            description="A dangerous tool.",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(tool_name="dangerous", content="executed!", success=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolConfirmation:
    def test_requires_confirmation_no_callback(self) -> None:
        """Tool requiring confirmation but no callback → blocked."""
        executor = ToolExecutor([_DangerousTool()])
        call = ToolCall(id="1", name="dangerous", arguments="{}")
        result = executor.execute(call)
        assert result.success is False
        assert "requires confirmation" in result.content

    def test_requires_confirmation_not_interactive(self) -> None:
        """Tool requiring confirmation but interactive=False → blocked."""
        executor = ToolExecutor(
            [_DangerousTool()],
            interactive=False,
            confirm_callback=lambda _: True,
        )
        call = ToolCall(id="1", name="dangerous", arguments="{}")
        result = executor.execute(call)
        assert result.success is False
        assert "requires confirmation" in result.content

    def test_requires_confirmation_denied(self) -> None:
        """Tool requiring confirmation, callback returns False → denied."""
        executor = ToolExecutor(
            [_DangerousTool()],
            interactive=True,
            confirm_callback=lambda _: False,
        )
        call = ToolCall(id="1", name="dangerous", arguments="{}")
        result = executor.execute(call)
        assert result.success is False
        assert "declined the confirmation prompt" in result.content

    def test_requires_confirmation_approved(self) -> None:
        """Tool requiring confirmation, callback returns True → executes."""
        executor = ToolExecutor(
            [_DangerousTool()],
            interactive=True,
            confirm_callback=lambda _: True,
        )
        call = ToolCall(id="1", name="dangerous", arguments="{}")
        result = executor.execute(call)
        assert result.success is True
        assert result.content == "executed!"

    def test_no_confirmation_needed(self) -> None:
        """Tool without requires_confirmation works normally."""
        executor = ToolExecutor([_SafeTool()])
        call = ToolCall(id="1", name="safe", arguments="{}")
        result = executor.execute(call)
        assert result.success is True
        assert result.content == "safe result"

    def test_no_confirmation_needed_with_callback(self) -> None:
        """Tool without requires_confirmation ignores callback."""
        calls = []
        executor = ToolExecutor(
            [_SafeTool()],
            interactive=True,
            confirm_callback=lambda msg: calls.append(msg) or True,
        )
        call = ToolCall(id="1", name="safe", arguments="{}")
        result = executor.execute(call)
        assert result.success is True
        # Callback should NOT have been called
        assert len(calls) == 0

    def test_confirmation_callback_receives_message(self) -> None:
        """Confirm callback receives a descriptive message."""
        received = []

        def capture(msg: str) -> bool:
            received.append(msg)
            return True

        executor = ToolExecutor(
            [_DangerousTool()],
            interactive=True,
            confirm_callback=capture,
        )
        call = ToolCall(id="1", name="dangerous", arguments='{"action": "delete"}')
        executor.execute(call)

        assert len(received) == 1
        assert "dangerous" in received[0]
        assert "action" in received[0]
