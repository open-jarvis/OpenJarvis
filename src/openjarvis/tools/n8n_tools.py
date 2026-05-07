"""Model-callable tools for the local/self-hosted n8n workflow service.

Each tool wraps one :class:`N8NClient` operation. Workflow-mutating
tools (create/update/activate/execute) carry ``requires_confirmation``
because they affect shared automation state.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.n8n import (
    N8NClient,
    N8NUnavailableError,
    get_default_client,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _ok(name: str, payload: Any) -> ToolResult:
    if not isinstance(payload, str):
        try:
            payload = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            payload = str(payload)
    return ToolResult(tool_name=name, content=payload or "(no content)", success=True)


def _err(name: str, exc: Exception) -> ToolResult:
    return ToolResult(tool_name=name, content=f"n8n error: {exc}", success=False)


class _N8NToolBase(BaseTool):
    is_local = False

    def __init__(self, client: Optional[N8NClient] = None) -> None:
        self._client = client or get_default_client()


@ToolRegistry.register("n8n_list_workflows")
class N8NListWorkflowsTool(_N8NToolBase):
    tool_id = "n8n_list_workflows"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_list_workflows",
            description="List workflows in the n8n instance.",
            parameters={
                "type": "object",
                "properties": {
                    "active": {
                        "type": "boolean",
                        "description": "Filter by active status (omit for all).",
                    },
                    "limit": {"type": "integer", "default": 50},
                },
            },
            category="automation",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.list_workflows(
                    active=params.get("active"),
                    limit=int(params.get("limit", 50)),
                ),
            )
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("n8n_get_workflow")
class N8NGetWorkflowTool(_N8NToolBase):
    tool_id = "n8n_get_workflow"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_get_workflow",
            description="Fetch full workflow definition by id.",
            parameters={
                "type": "object",
                "properties": {"workflow_id": {"type": "string"}},
                "required": ["workflow_id"],
            },
            category="automation",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(self.spec.name, self._client.get_workflow(params["workflow_id"]))
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("n8n_create_workflow")
class N8NCreateWorkflowTool(_N8NToolBase):
    tool_id = "n8n_create_workflow"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_create_workflow",
            description=(
                "Create a new n8n workflow. The 'definition' must be a "
                "valid n8n workflow JSON (name, nodes[], connections, "
                "settings). Refer to n8n_get_workflow on an existing "
                "workflow for the schema."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "definition": {
                        "type": "object",
                        "description": "Full n8n workflow JSON.",
                    },
                },
                "required": ["definition"],
            },
            category="automation",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(self.spec.name, self._client.create_workflow(params["definition"]))
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("n8n_update_workflow")
class N8NUpdateWorkflowTool(_N8NToolBase):
    tool_id = "n8n_update_workflow"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_update_workflow",
            description="Update an existing workflow's definition (full replace).",
            parameters={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "definition": {"type": "object"},
                },
                "required": ["workflow_id", "definition"],
            },
            category="automation",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.update_workflow(
                    params["workflow_id"], params["definition"]
                ),
            )
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("n8n_activate_workflow")
class N8NActivateWorkflowTool(_N8NToolBase):
    tool_id = "n8n_activate_workflow"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_activate_workflow",
            description=(
                "Activate (or deactivate) a workflow. Activation enables "
                "triggers; deactivation pauses them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "active": {"type": "boolean", "default": True},
                },
                "required": ["workflow_id"],
            },
            category="automation",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            wid = params["workflow_id"]
            result = (
                self._client.activate_workflow(wid)
                if params.get("active", True)
                else self._client.deactivate_workflow(wid)
            )
            return _ok(self.spec.name, result)
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("n8n_execute_workflow")
class N8NExecuteWorkflowTool(_N8NToolBase):
    tool_id = "n8n_execute_workflow"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_execute_workflow",
            description=(
                "Run a workflow synchronously with optional input data. "
                "Returns the execution payload."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "input_data": {
                        "type": "object",
                        "description": "Optional input payload for the workflow.",
                    },
                },
                "required": ["workflow_id"],
            },
            category="automation",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.execute_workflow(
                    params["workflow_id"],
                    input_data=params.get("input_data"),
                ),
            )
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("n8n_list_executions")
class N8NListExecutionsTool(_N8NToolBase):
    tool_id = "n8n_list_executions"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="n8n_list_executions",
            description=(
                "List recent executions across all workflows or filter "
                "by workflow id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            category="automation",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.list_executions(
                    workflow_id=params.get("workflow_id"),
                    limit=int(params.get("limit", 20)),
                ),
            )
        except N8NUnavailableError as exc:
            return _err(self.spec.name, exc)


__all__ = [
    "N8NActivateWorkflowTool",
    "N8NCreateWorkflowTool",
    "N8NExecuteWorkflowTool",
    "N8NGetWorkflowTool",
    "N8NListExecutionsTool",
    "N8NListWorkflowsTool",
    "N8NUpdateWorkflowTool",
]
