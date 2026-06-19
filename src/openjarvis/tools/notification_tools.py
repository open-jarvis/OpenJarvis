"""Agent tools for outbound alerts (email / SMS / push).

These expose :mod:`openjarvis.notifications` to the agent so Jarvis can act on
requests like "text me when this is done", "email me a summary", or "notify my
phone if the server crashes".

How this connects into the backend
-----------------------------------
* Registration: each tool is decorated with ``@ToolRegistry.register(...)``,
  and this module is imported from ``openjarvis/tools/__init__.py`` so the
  decorators run at import time (same pattern as ``weather``/``news``).
* Availability: the agent only sees tools listed in its config. Add them in
  ``~/.openjarvis/config.toml``::

      [agent]
      tools = "...,notify,notify_email,notify_sms,notify_push"

  or pass them when constructing the agent/operator. The orchestrator then
  selects the tool when the user asks to be alerted.
* Configuration: the underlying functions read secrets from environment
  variables (see ``.env.example``). Nothing is hardcoded here.

Safety
------
Sending an alert is a side effect that leaves the machine, so the *write*-style
tools default to ``requires_confirmation`` semantics via the ``channel:send``
capability. No secret is ever placed in a tool result.
"""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.notifications import (
    send_email_alert,
    send_push_alert,
    send_sms_alert,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _result(tool: str, res: Any) -> ToolResult:
    """Map a NotificationResult to a ToolResult (no secrets in metadata)."""
    return ToolResult(
        tool_name=tool,
        content=(res.detail if res.success else res.error)
        or ("Sent." if res.success else "Failed."),
        success=bool(res.success),
        metadata={"channel": res.channel, "delivered": bool(res.success)},
    )


@ToolRegistry.register("notify_email")
class NotifyEmailTool(BaseTool):
    """Send an email alert to the configured address."""

    tool_id = "notify_email"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notify_email",
            description=(
                "Email the user an alert/summary. Use for 'email me ...'."
                " Requires SMTP settings in the environment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Email subject line."},
                    "message": {"type": "string", "description": "Email body text."},
                },
                "required": ["subject", "message"],
            },
            category="notification",
            required_capabilities=["channel:send"],
        )

    def execute(self, **params: Any) -> ToolResult:
        subject = str(params.get("subject", "") or "OpenJarvis alert")
        message = str(params.get("message", "") or "")
        return _result("notify_email", send_email_alert(subject, message))


@ToolRegistry.register("notify_sms")
class NotifySmsTool(BaseTool):
    """Send an SMS text alert to the configured phone number."""

    tool_id = "notify_sms"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notify_sms",
            description=(
                "Text (SMS) the user an alert. Use for 'text me when ...'."
                " Requires Twilio settings in the environment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Text message body."},
                },
                "required": ["message"],
            },
            category="notification",
            required_capabilities=["channel:send"],
        )

    def execute(self, **params: Any) -> ToolResult:
        message = str(params.get("message", "") or "")
        return _result("notify_sms", send_sms_alert(message))


@ToolRegistry.register("notify_push")
class NotifyPushTool(BaseTool):
    """Send a push notification (ntfy/Pushover) to the user's phone."""

    tool_id = "notify_push"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notify_push",
            description=(
                "Send a push notification to the user's phone. Use for"
                " 'notify my phone ...'. Requires NTFY_TOPIC (or Pushover)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Notification title."},
                    "message": {"type": "string", "description": "Notification body."},
                },
                "required": ["title", "message"],
            },
            category="notification",
            required_capabilities=["channel:send"],
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title", "") or "OpenJarvis")
        message = str(params.get("message", "") or "")
        return _result("notify_push", send_push_alert(title, message))


@ToolRegistry.register("notify")
class NotifyTool(BaseTool):
    """Send an alert across one or more channels (email / sms / push / all)."""

    tool_id = "notify"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notify",
            description=(
                "Alert the user via one or more channels. 'channels' may list"
                " any of: email, sms, push, or 'all'. Defaults to push."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title / email subject.",
                    },
                    "message": {"type": "string", "description": "Alert body."},
                    "channels": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["email", "sms", "push", "all"],
                        },
                        "description": "Channels to use. Default: ['push'].",
                    },
                },
                "required": ["title", "message"],
            },
            category="notification",
            required_capabilities=["channel:send"],
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.notifications import send_alert

        title = str(params.get("title", "") or "OpenJarvis")
        message = str(params.get("message", "") or "")
        channels = params.get("channels") or ["push"]
        if isinstance(channels, str):
            channels = [c.strip() for c in channels.split(",") if c.strip()]

        results = send_alert(title, message, channels=channels)
        delivered = [c for c, r in results.items() if r.success]
        failed = {c: r.error for c, r in results.items() if not r.success}

        lines = []
        if delivered:
            lines.append("Delivered: " + ", ".join(sorted(delivered)))
        for ch, err in failed.items():
            lines.append(f"{ch} failed: {err}")

        return ToolResult(
            tool_name="notify",
            content="\n".join(lines) or "No channels selected.",
            success=bool(delivered),
            metadata={
                "delivered": sorted(delivered),
                "failed": sorted(failed.keys()),
            },
        )


__all__ = [
    "NotifyEmailTool",
    "NotifySmsTool",
    "NotifyPushTool",
    "NotifyTool",
]
