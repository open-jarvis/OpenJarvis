"""Registered tools for Friday's local assistant actions."""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.friday_assistant import (
    FridayAssistantRouter,
    check_friday_status,
    open_macos_app,
    open_website,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("friday_time_date")
class FridayTimeDateTool(BaseTool):
    """Answer local Korean time/date questions."""

    tool_id = "friday_time_date"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Answer Korean time, date, and weekday questions using local "
                "system time."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            category="friday",
            metadata={"local_only": True, "requires_api_key": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query") or "")
        result = FridayAssistantRouter()._route_time_date(query)
        if result is None:
            return ToolResult(
                tool_name=self.tool_id,
                content="시간이나 날짜 질문을 인식하지 못했습니다.",
                success=False,
            )
        return ToolResult(tool_name=self.tool_id, content=result.content, success=True)


@ToolRegistry.register("friday_open_website")
class FridayOpenWebsiteTool(BaseTool):
    """Open a website from a small allowlist."""

    tool_id = "friday_open_website"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Open allowed websites only: Google, Naver, YouTube, GitHub, ChatGPT."
            ),
            parameters={
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
            category="friday",
            requires_confirmation=True,
            metadata={"local_only": True, "allowlist": True, "requires_api_key": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        result = open_website(str(params.get("target") or ""))
        return ToolResult(
            tool_name=self.tool_id,
            content=result.content,
            success=result.success,
            metadata=result.metadata,
        )


@ToolRegistry.register("friday_open_app")
class FridayOpenAppTool(BaseTool):
    """Open a macOS app from a small allowlist."""

    tool_id = "friday_open_app"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Open allowed macOS apps only: Chrome, Safari, Notes, "
                "Calculator, Terminal, KakaoTalk."
            ),
            parameters={
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
            category="friday",
            requires_confirmation=True,
            metadata={"local_only": True, "allowlist": True, "requires_api_key": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        result = open_macos_app(str(params.get("target") or ""))
        return ToolResult(
            tool_name=self.tool_id,
            content=result.content,
            success=result.success,
            metadata=result.metadata,
        )


@ToolRegistry.register("friday_notes")
class FridayNotesTool(BaseTool):
    """Store and list local Friday notes and todos."""

    tool_id = "friday_notes"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Handle local JSON notes and todos for Friday.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            category="friday",
            metadata={"local_only": True, "requires_api_key": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        result = FridayAssistantRouter()._route_notes_todos(
            str(params.get("query") or "")
        )
        if result is None:
            return ToolResult(
                tool_name=self.tool_id,
                content="메모나 할 일 요청을 인식하지 못했습니다.",
                success=False,
            )
        return ToolResult(
            tool_name=self.tool_id,
            content=result.content,
            success=result.success,
            metadata=result.metadata,
        )


@ToolRegistry.register("friday_status")
class FridayStatusTool(BaseTool):
    """Check Friday's local service status."""

    tool_id = "friday_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check local Friday ports for Ollama, backend, and frontend.",
            parameters={"type": "object", "properties": {}, "required": []},
            category="friday",
            metadata={"local_only": True, "requires_api_key": False},
        )

    def execute(self, **params: Any) -> ToolResult:
        result = check_friday_status()
        return ToolResult(
            tool_name=self.tool_id,
            content=result.content,
            success=result.success,
            metadata=result.metadata,
        )


__all__ = [
    "FridayNotesTool",
    "FridayOpenAppTool",
    "FridayOpenWebsiteTool",
    "FridayStatusTool",
    "FridayTimeDateTool",
]
