"""SkillTool — wraps a skill as a tool that agents can invoke."""

from __future__ import annotations

from typing import Any, Dict

from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.types import SkillManifest
from openjarvis.tools._stubs import BaseTool, ToolSpec


class SkillTool(BaseTool):
    """Wraps a SkillManifest as a BaseTool that agents can invoke.

    Follows the same adapter pattern as MCPToolAdapter.
    """

    tool_id: str

    def __init__(
        self,
        manifest: SkillManifest,
        executor: SkillExecutor,
    ) -> None:
        self._manifest = manifest
        self._executor = executor
        self.tool_id = f"skill_{manifest.name}"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=f"skill_{self._manifest.name}",
            description=self._manifest.description or f"Skill: {self._manifest.name}",
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input text for the skill pipeline.",
                    },
                    "context": {
                        "type": "object",
                        "description": "Additional context key-value pairs.",
                    },
                },
            },
            category="skill",
            required_capabilities=self._manifest.required_capabilities,
        )

    def execute(self, **params: Any) -> ToolResult:
        initial_ctx: Dict[str, Any] = params.get("context", {})
        if "input" in params:
            initial_ctx["input"] = params["input"]

        result = self._executor.run(self._manifest, initial_context=initial_ctx)

        return ToolResult(
            tool_name=self.spec.name,
            content=result.context.get(
                result.step_results[-1].tool_name if result.step_results else "",
                result.step_results[-1].content if result.step_results else "",
            )
            if result.step_results
            else "",
            success=result.success,
            metadata={"skill": self._manifest.name, "steps": len(result.step_results)},
        )


__all__ = ["SkillTool"]
