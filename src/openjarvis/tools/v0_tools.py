"""Model-callable tool that asks V0 to design/generate a UI from a prompt."""

from __future__ import annotations

import json
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.v0 import V0Client, V0UnavailableError, get_default_client
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("v0_chat_create")
class V0ChatCreateTool(BaseTool):
    tool_id = "v0_chat_create"
    is_local = False

    def __init__(self, client: Optional[V0Client] = None) -> None:
        self._client = client or get_default_client()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="v0_chat_create",
            description=(
                "Ask V0 (Vercel) to design and generate a UI from a "
                "natural-language prompt. Returns the assistant message, "
                "which typically embeds a deploy/preview URL the user "
                "can visit immediately."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "What to build. Be specific about layout, "
                            "components, and stack (Next.js + shadcn/ui by default)."
                        ),
                    },
                    "system": {
                        "type": "string",
                        "description": "Optional system message to steer V0.",
                    },
                    "model": {
                        "type": "string",
                        "default": "v0-1.5-md",
                        "description": "V0 model id (v0-1.5-md or v0-1.0-md).",
                    },
                },
                "required": ["prompt"],
            },
            category="dev",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            payload = self._client.chat_create(
                params["prompt"],
                model=params.get("model", "v0-1.5-md"),
                system=params.get("system"),
            )
        except V0UnavailableError as exc:
            return ToolResult(
                tool_name=self.spec.name,
                content=f"V0 error: {exc}",
                success=False,
            )
        try:
            content = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            content = str(payload)
        return ToolResult(tool_name=self.spec.name, content=content, success=True)


__all__ = ["V0ChatCreateTool"]
