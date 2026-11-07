"""LLM tool — delegate a sub-query to an inference engine."""

from __future__ import annotations

from typing import Any, Optional

from friday_ai.core.registry import ToolRegistry
from friday_ai.core.types import Message, Role, ToolResult
from friday_ai.engine._stubs import InferenceEngine
from friday_ai.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("llm")
class LLMTool(BaseTool):
    """Delegate a sub-query to an inference engine for generation."""

    tool_id = "llm"

    def __init__(
        self,
        engine: Optional[InferenceEngine] = None,
        *,
        model: str = "",
    ) -> None:
        self._engine = engine
        self._model = model

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="llm",
            description=(
                "Send a prompt to a language model."
                " Useful for sub-queries or summarization."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The prompt to send to the language model.",
                    },
                    "system": {
                        "type": "string",
                        "description": "Optional system message to set context.",
                    },
                },
                "required": ["prompt"],
            },
            category="inference",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._engine is None:
            return ToolResult(
                tool_name="llm",
                content="No inference engine configured.",
                success=False,
            )
        if not self._model:
            return ToolResult(
                tool_name="llm",
                content="No model configured.",
                success=False,
            )
        prompt = params.get("prompt", "")
        if not prompt:
            return ToolResult(
                tool_name="llm",
                content="No prompt provided.",
                success=False,
            )
        messages = []
        system = params.get("system")
        if system:
            messages.append(Message(role=Role.SYSTEM, content=system))
        messages.append(Message(role=Role.USER, content=prompt))
        try:
            result = self._engine.generate(messages, model=self._model)
            content = result.get("content", "")
            return ToolResult(
                tool_name="llm",
                content=content,
                success=True,
                usage=result.get("usage", {}),
            )
        except Exception as exc:
            return ToolResult(
                tool_name="llm",
                content=f"LLM error: {exc}",
                success=False,
            )


__all__ = ["LLMTool"]
