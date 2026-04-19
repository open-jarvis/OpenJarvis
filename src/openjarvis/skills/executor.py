"""SkillExecutor — runs skill steps sequentially through ToolExecutor."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.skills.types import SkillManifest
from openjarvis.tools._stubs import ToolExecutor


@dataclass(slots=True)
class SkillResult:
    skill_name: str = ""
    success: bool = True
    step_results: List[ToolResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


# Resolver callback: given a skill name and the current context, returns a SkillResult.
SkillResolver = Callable[[str, Dict[str, Any]], SkillResult]


class SkillExecutor:
    """Execute a skill manifest step-by-step.

    Each step's arguments_template supports ``{key}`` placeholders
    that are resolved from the context dict (populated by prior step outputs).
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        *,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._bus = bus
        self._skill_resolver: Optional[SkillResolver] = None

    def set_skill_resolver(self, resolver: SkillResolver) -> None:
        """Register a callback used to delegate ``skill_name`` steps."""
        self._skill_resolver = resolver

    def run(
        self,
        manifest: SkillManifest,
        *,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """Execute all steps in a skill manifest."""
        ctx: Dict[str, Any] = dict(initial_context or {})
        all_results: List[ToolResult] = []

        if self._bus:
            self._bus.publish(
                EventType.SKILL_EXECUTE_START,
                {"skill": manifest.name, "steps": len(manifest.steps)},
            )

        for i, step in enumerate(manifest.steps):
            step_id = step.tool_name or step.skill_name

            # Render template
            try:
                rendered = self._render_template(step.arguments_template, ctx)
            except Exception as exc:
                result = ToolResult(
                    tool_name=step_id,
                    content=f"Template rendering error: {exc}",
                    success=False,
                )
                all_results.append(result)
                break

            if step.skill_name:
                # Delegate to sub-skill resolver
                result = self._run_sub_skill(
                    step.skill_name, rendered, ctx, manifest.name, i
                )
            else:
                # Execute via tool executor
                tool_call = ToolCall(
                    id=f"skill_{manifest.name}_{i}",
                    name=step.tool_name,
                    arguments=rendered,
                )
                result = self._tool_executor.execute(tool_call)

            all_results.append(result)

            if not result.success:
                break

            # Store output in context
            if step.output_key:
                ctx[step.output_key] = result.content

        success = all(r.success for r in all_results)

        if self._bus:
            self._bus.publish(
                EventType.SKILL_EXECUTE_END,
                {"skill": manifest.name, "success": success},
            )

        return SkillResult(
            skill_name=manifest.name,
            success=success,
            step_results=all_results,
            context=ctx,
        )

    def _run_sub_skill(
        self,
        skill_name: str,
        rendered_args: str,
        parent_ctx: Dict[str, Any],
        parent_skill: str,
        step_index: int,
    ) -> ToolResult:
        """Invoke the skill resolver and convert its result to a ToolResult."""
        if self._skill_resolver is None:
            return ToolResult(
                tool_name=skill_name,
                content=f"No skill resolver registered for sub-skill '{skill_name}'",
                success=False,
            )

        # Parse rendered args and merge into a copy of the parent context
        try:
            args: Dict[str, Any] = json.loads(rendered_args)
        except json.JSONDecodeError:
            args = {}

        child_ctx = {**parent_ctx, **args}

        sub_result: SkillResult = self._skill_resolver(skill_name, child_ctx)

        # Expose the final context value under the first output_key, or the
        # last step's content, as the synthetic "content" of this ToolResult.
        content: Any = ""
        if sub_result.context:
            # Return the last stored value from the child's context that is
            # not already in the parent context (i.e. the output of the sub-skill).
            new_keys = [k for k in sub_result.context if k not in parent_ctx]
            if new_keys:
                content = sub_result.context[new_keys[-1]]
            else:
                content = (
                    list(sub_result.context.values())[-1] if sub_result.context else ""
                )
        elif sub_result.step_results:
            content = sub_result.step_results[-1].content

        return ToolResult(
            tool_name=skill_name,
            content=content,
            success=sub_result.success,
        )

    @staticmethod
    def _render_template(template: str, ctx: Dict[str, Any]) -> str:
        """Simple {key} placeholder rendering."""

        def _replace(match: re.Match) -> str:
            key = match.group(1)
            val = ctx.get(key, match.group(0))
            if isinstance(val, str):
                return val
            return json.dumps(val)

        return re.sub(r"\{(\w+)\}", _replace, template)


__all__ = ["SkillExecutor", "SkillResolver", "SkillResult"]
