"""Tools that let the agent use the on-demand skill library.

* ``find_skills`` - search installed skills (including imported Claude skills)
  by what the user is asking for.
* ``use_skill`` - load one skill's full instructions into the conversation so
  the agent can follow them.

Enable with ``[tools] enabled = [..., "find_skills", "use_skill"]``.
"""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("find_skills")
class FindSkillsTool(BaseTool):
    """Search the skill library."""

    tool_id = "find_skills"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="find_skills",
            description=(
                "Search your library of skills (expert instructions for tasks such "
                "as writing, research, marketing, coding, documents and planning). "
                "Returns matching skill names and what each is for. Then call "
                "use_skill to load one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What the user wants to do, in a few words.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many results (default 5, max 10).",
                    },
                },
                "required": ["query"],
            },
            category="skills",
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.skills.library import get_skill_library

        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult(
                tool_name="find_skills", content="No query given.", success=False
            )
        try:
            limit = max(1, min(10, int(params.get("limit") or 5)))
        except (TypeError, ValueError):
            limit = 5
        hits = get_skill_library().search(query, k=limit)
        if not hits:
            return ToolResult(
                tool_name="find_skills",
                content=f"No skills match '{query}'. Answer without a skill.",
                success=True,
            )
        lines = [f"Skills matching '{query}':"]
        for entry, _ in hits:
            desc = entry.description.splitlines()[0][:200] if entry.description else ""
            lines.append(f"- {entry.name}: {desc}")
        return ToolResult(
            tool_name="find_skills", content="\n".join(lines), success=True
        )


@ToolRegistry.register("use_skill")
class UseSkillTool(BaseTool):
    """Load one skill's full instructions."""

    tool_id = "use_skill"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="use_skill",
            description=(
                "Load the full instructions of a skill from your library by name, "
                "then follow them to do the task. Use a name from find_skills or "
                "from the skill suggestions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name."}
                },
                "required": ["name"],
            },
            category="skills",
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        from openjarvis.skills.library import get_skill_library

        name = str(params.get("name", "")).strip()
        lib = get_skill_library()
        text = lib.load(name) if name else None
        if text is None:
            close = [e.name for e, _ in lib.search(name, k=3)] if name else []
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            return ToolResult(
                tool_name="use_skill",
                content=f"No skill named '{name}'.{hint}",
                success=False,
            )
        return ToolResult(tool_name="use_skill", content=text, success=True)


__all__ = ["FindSkillsTool", "UseSkillTool"]
