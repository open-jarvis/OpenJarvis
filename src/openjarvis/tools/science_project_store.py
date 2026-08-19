"""Tool wrapper around ScienceProjectStore — save/get/list saved science projects."""

from __future__ import annotations

from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.science_lab.store import ScienceProjectStore
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("science_project")
class ScienceProjectTool(BaseTool):
    """Save, retrieve, or list saved Science Lab projects."""

    tool_id = "science_project"

    def __init__(self, db_path: str = "") -> None:
        self._db_path = db_path
        self._store: Optional[ScienceProjectStore] = None

    def _get_store(self) -> ScienceProjectStore:
        if self._store is None:
            self._store = ScienceProjectStore(db_path=self._db_path)
        return self._store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="science_project",
            description="Save, retrieve, or list saved Science Lab projects.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "list"],
                        "description": (
                            "'get' retrieves one saved project by name, 'list' "
                            "returns recent projects. Saving happens automatically "
                            "when a ScienceLabAgent run is given a project_name."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": "Project name (for 'get').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (for 'list').",
                    },
                },
                "required": ["action"],
            },
            category="science",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "list")
        store = self._get_store()
        if action == "get":
            name = params.get("name", "")
            project = store.get(name)
            if project is None:
                return ToolResult(
                    tool_name="science_project",
                    content=f"No project named {name!r}.",
                    success=False,
                )
            return ToolResult(
                tool_name="science_project",
                content=f"Project {project.name}: {project.objective}",
                success=True,
                metadata=project.to_dict(),
            )
        if action == "list":
            limit = int(params.get("limit", 50))
            projects = store.list_projects(limit=limit)
            names = ", ".join(p.name for p in projects) or "(none)"
            return ToolResult(
                tool_name="science_project",
                content=f"Saved projects: {names}",
                success=True,
                metadata={"projects": [p.to_dict() for p in projects]},
            )
        return ToolResult(
            tool_name="science_project",
            content=f"Unknown action: {action}",
            success=False,
        )


__all__ = ["ScienceProjectTool"]
