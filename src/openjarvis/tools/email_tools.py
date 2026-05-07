"""Send-side email tools (SMTP). IMAP read tools deferred to v2."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.email_smtp import SMTPUnavailableError, send_email
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("email_send")
class EmailSendTool(BaseTool):
    tool_id = "email_send"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="email_send",
            description=(
                "Send an email via the configured SMTP server. Supports "
                "plain-text, HTML, cc, and bcc. From address is derived "
                "from SMTP_USER."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Primary recipient address(es).",
                    },
                    "subject": {"type": "string"},
                    "body": {
                        "type": "string",
                        "description": "Plain-text body.",
                    },
                    "html": {
                        "type": "string",
                        "description": "Optional HTML alternative body.",
                    },
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["to", "subject", "body"],
            },
            category="messaging",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            result = send_email(
                to=params["to"],
                subject=params["subject"],
                body=params["body"],
                html=params.get("html"),
                cc=params.get("cc"),
                bcc=params.get("bcc"),
            )
            return ToolResult(
                tool_name=self.spec.name,
                content=json.dumps(result, ensure_ascii=False),
                success=True,
            )
        except SMTPUnavailableError as exc:
            return ToolResult(
                tool_name=self.spec.name,
                content=f"Email error: {exc}",
                success=False,
            )


__all__ = ["EmailSendTool"]
