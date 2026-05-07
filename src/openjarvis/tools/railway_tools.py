"""Model-callable tools for Railway dashboard operations."""

from __future__ import annotations

import json
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.railway import (
    RailwayClient,
    RailwayUnavailableError,
    get_default_client,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _ok(name: str, payload: Any) -> ToolResult:
    if not isinstance(payload, str):
        try:
            payload = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            payload = str(payload)
    return ToolResult(tool_name=name, content=payload, success=True)


def _err(name: str, exc: Exception) -> ToolResult:
    return ToolResult(tool_name=name, content=f"Railway error: {exc}", success=False)


class _RailwayToolBase(BaseTool):
    is_local = False

    def __init__(self, client: Optional[RailwayClient] = None) -> None:
        self._client = client or get_default_client()


@ToolRegistry.register("railway_list_projects")
class RailwayListProjectsTool(_RailwayToolBase):
    tool_id = "railway_list_projects"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="railway_list_projects",
            description="List Railway projects accessible by the configured token.",
            parameters={"type": "object", "properties": {}},
            category="infra",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(self.spec.name, self._client.list_projects())
        except RailwayUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("railway_list_services")
class RailwayListServicesTool(_RailwayToolBase):
    tool_id = "railway_list_services"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="railway_list_services",
            description="List services within a Railway project.",
            parameters={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
            category="infra",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(self.spec.name, self._client.list_services(params["project_id"]))
        except RailwayUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("railway_get_variables")
class RailwayGetVariablesTool(_RailwayToolBase):
    tool_id = "railway_get_variables"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="railway_get_variables",
            description="Read service environment variables.",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "environment_id": {"type": "string"},
                    "service_id": {"type": "string"},
                },
                "required": ["project_id", "environment_id", "service_id"],
            },
            category="infra",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.get_service_variables(
                    params["project_id"],
                    params["environment_id"],
                    params["service_id"],
                ),
            )
        except RailwayUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("railway_set_variable")
class RailwaySetVariableTool(_RailwayToolBase):
    tool_id = "railway_set_variable"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="railway_set_variable",
            description=(
                "Create or update a service environment variable. "
                "Triggers a redeploy on the affected service."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "environment_id": {"type": "string"},
                    "service_id": {"type": "string"},
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": [
                    "project_id",
                    "environment_id",
                    "service_id",
                    "name",
                    "value",
                ],
            },
            category="infra",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.upsert_variable(
                    params["project_id"],
                    params["environment_id"],
                    params["service_id"],
                    params["name"],
                    params["value"],
                ),
            )
        except RailwayUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("railway_redeploy")
class RailwayRedeployTool(_RailwayToolBase):
    tool_id = "railway_redeploy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="railway_redeploy",
            description="Force-redeploy a service in the given environment.",
            parameters={
                "type": "object",
                "properties": {
                    "service_id": {"type": "string"},
                    "environment_id": {"type": "string"},
                },
                "required": ["service_id", "environment_id"],
            },
            category="infra",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.redeploy_service(
                    params["service_id"], params["environment_id"]
                ),
            )
        except RailwayUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("railway_logs")
class RailwayLogsTool(_RailwayToolBase):
    tool_id = "railway_logs"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="railway_logs",
            description="Fetch logs for a specific deployment.",
            parameters={
                "type": "object",
                "properties": {
                    "deployment_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 200},
                },
                "required": ["deployment_id"],
            },
            category="infra",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.deployment_logs(
                    params["deployment_id"],
                    limit=int(params.get("limit", 200)),
                ),
            )
        except RailwayUnavailableError as exc:
            return _err(self.spec.name, exc)


__all__ = [
    "RailwayGetVariablesTool",
    "RailwayListProjectsTool",
    "RailwayListServicesTool",
    "RailwayLogsTool",
    "RailwayRedeployTool",
    "RailwaySetVariableTool",
]
