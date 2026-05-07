"""Model-callable Cloudinary tools."""

from __future__ import annotations

import json
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.cloudinary import (
    CloudinaryClient,
    CloudinaryUnavailableError,
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
    return ToolResult(tool_name=name, content=f"Cloudinary error: {exc}", success=False)


class _CldToolBase(BaseTool):
    is_local = False

    def __init__(self, client: Optional[CloudinaryClient] = None) -> None:
        self._client = client or get_default_client()


@ToolRegistry.register("cloudinary_upload")
class CloudinaryUploadTool(_CldToolBase):
    tool_id = "cloudinary_upload"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cloudinary_upload",
            description=(
                "Upload an image or video to Cloudinary by remote URL. "
                "Returns the asset's public_id, secure_url, and metadata."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_url": {
                        "type": "string",
                        "description": "HTTPS URL of the asset to upload.",
                    },
                    "public_id": {
                        "type": "string",
                        "description": "Optional public id (otherwise auto-generated).",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Optional folder under the cloud namespace.",
                    },
                    "resource_type": {
                        "type": "string",
                        "enum": ["image", "video", "raw", "auto"],
                        "default": "auto",
                    },
                },
                "required": ["file_url"],
            },
            category="media",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.upload(
                    file_url=params["file_url"],
                    public_id=params.get("public_id"),
                    folder=params.get("folder"),
                    resource_type=params.get("resource_type", "auto"),
                ),
            )
        except (CloudinaryUnavailableError, ValueError) as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("cloudinary_search")
class CloudinarySearchTool(_CldToolBase):
    tool_id = "cloudinary_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cloudinary_search",
            description=(
                "Search uploaded assets via Cloudinary's search expression "
                "syntax (e.g. 'folder:memes AND tags:cat')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string"},
                    "max_results": {"type": "integer", "default": 30},
                },
                "required": ["expression"],
            },
            category="media",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.search(
                    params["expression"],
                    max_results=int(params.get("max_results", 30)),
                ),
            )
        except CloudinaryUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("cloudinary_delete")
class CloudinaryDeleteTool(_CldToolBase):
    tool_id = "cloudinary_delete"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cloudinary_delete",
            description="Delete a single asset by public_id.",
            parameters={
                "type": "object",
                "properties": {
                    "public_id": {"type": "string"},
                    "resource_type": {
                        "type": "string",
                        "enum": ["image", "video", "raw"],
                        "default": "image",
                    },
                },
                "required": ["public_id"],
            },
            category="media",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.delete(
                    params["public_id"],
                    resource_type=params.get("resource_type", "image"),
                ),
            )
        except CloudinaryUnavailableError as exc:
            return _err(self.spec.name, exc)


__all__ = [
    "CloudinaryDeleteTool",
    "CloudinarySearchTool",
    "CloudinaryUploadTool",
]
