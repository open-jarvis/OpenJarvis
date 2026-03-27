"""MCP tools for knowledge graph operations."""

from __future__ import annotations

import json
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("kg_add_entity")
class KGAddEntityTool(BaseTool):
    """Add an entity to the knowledge graph."""

    tool_id = "kg_add_entity"

    def __init__(self, backend: Optional[Any] = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="kg_add_entity",
            description="Add an entity to the knowledge graph.",
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Unique entity ID.",
                    },
                    "entity_type": {
                        "type": "string",
                        "description": (
                            "Entity type (e.g., 'concept', 'tool', 'user')."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": "Entity name.",
                    },
                    "properties": {
                        "type": "object",
                        "description": ("Additional properties."),
                    },
                },
                "required": ["entity_id", "entity_type", "name"],
            },
            category="knowledge_graph",
            required_capabilities=["memory:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if not self._backend or not hasattr(
            self._backend,
            "add_entity",
        ):
            return ToolResult(
                tool_name="kg_add_entity",
                content="No knowledge graph backend available.",
                success=False,
            )
        from openjarvis.tools.storage.knowledge_graph import Entity

        entity = Entity(
            entity_id=params["entity_id"],
            entity_type=params["entity_type"],
            name=params["name"],
            properties=params.get("properties", {}),
        )
        self._backend.add_entity(entity)
        name = params["name"]
        return ToolResult(
            tool_name="kg_add_entity",
            content=f"Entity '{name}' added.",
            success=True,
        )


@ToolRegistry.register("kg_add_relation")
class KGAddRelationTool(BaseTool):
    """Add a relation between two entities in the knowledge graph."""

    tool_id = "kg_add_relation"

    def __init__(self, backend: Optional[Any] = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="kg_add_relation",
            description="Add a relation between two entities in the knowledge graph.",
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source entity ID.",
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Target entity ID.",
                    },
                    "relation_type": {
                        "type": "string",
                        "description": ("Relation type (e.g., 'used', 'depends_on')."),
                    },
                    "weight": {
                        "type": "number",
                        "description": ("Relation weight (default 1.0)."),
                    },
                },
                "required": ["source_id", "target_id", "relation_type"],
            },
            category="knowledge_graph",
            required_capabilities=["memory:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if not self._backend or not hasattr(
            self._backend,
            "add_relation",
        ):
            return ToolResult(
                tool_name="kg_add_relation",
                content="No knowledge graph backend available.",
                success=False,
            )
        from openjarvis.tools.storage.knowledge_graph import Relation

        relation = Relation(
            source_id=params["source_id"],
            target_id=params["target_id"],
            relation_type=params["relation_type"],
            weight=params.get("weight", 1.0),
        )
        self._backend.add_relation(relation)
        rtype = params["relation_type"]
        return ToolResult(
            tool_name="kg_add_relation",
            content=f"Relation '{rtype}' added.",
            success=True,
        )


@ToolRegistry.register("kg_query")
class KGQueryTool(BaseTool):
    """Query the knowledge graph by entity/relation type patterns."""

    tool_id = "kg_query"

    def __init__(self, backend: Optional[Any] = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="kg_query",
            description="Query the knowledge graph by entity or relation type.",
            parameters={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": ("Filter by entity type."),
                    },
                    "relation_type": {
                        "type": "string",
                        "description": ("Filter by relation type."),
                    },
                    "limit": {
                        "type": "integer",
                        "description": ("Max results (default 50)."),
                    },
                },
            },
            category="knowledge_graph",
            required_capabilities=["memory:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if not self._backend or not hasattr(
            self._backend,
            "query_pattern",
        ):
            return ToolResult(
                tool_name="kg_query",
                content="No knowledge graph backend available.",
                success=False,
            )
        result = self._backend.query_pattern(
            entity_type=params.get("entity_type"),
            relation_type=params.get("relation_type"),
            limit=params.get("limit", 50),
        )
        output = {
            "entities": [
                {"id": e.entity_id, "type": e.entity_type, "name": e.name}
                for e in result.entities
            ],
            "relations": [
                {
                    "source": r.source_id,
                    "target": r.target_id,
                    "type": r.relation_type,
                    "weight": r.weight,
                }
                for r in result.relations
            ],
        }
        return ToolResult(
            tool_name="kg_query",
            content=json.dumps(output, indent=2),
            success=True,
        )


@ToolRegistry.register("kg_neighbors")
class KGNeighborsTool(BaseTool):
    """Find neighboring entities in the knowledge graph."""

    tool_id = "kg_neighbors"

    def __init__(self, backend: Optional[Any] = None) -> None:
        self._backend = backend

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="kg_neighbors",
            description="Find entities connected to a given entity.",
            parameters={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": ("Entity ID to find neighbors for."),
                    },
                    "relation_type": {
                        "type": "string",
                        "description": ("Filter by relation type."),
                    },
                    "direction": {
                        "type": "string",
                        "description": (
                            "Direction: 'in', 'out', or 'both' (default 'both')."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": ("Max results (default 50)."),
                    },
                },
                "required": ["entity_id"],
            },
            category="knowledge_graph",
            required_capabilities=["memory:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if not self._backend or not hasattr(
            self._backend,
            "neighbors",
        ):
            return ToolResult(
                tool_name="kg_neighbors",
                content="No knowledge graph backend available.",
                success=False,
            )
        neighbors = self._backend.neighbors(
            params["entity_id"],
            relation_type=params.get("relation_type"),
            direction=params.get("direction", "both"),
            limit=params.get("limit", 50),
        )
        output = [
            {
                "id": e.entity_id,
                "type": e.entity_type,
                "name": e.name,
            }
            for e in neighbors
        ]
        return ToolResult(
            tool_name="kg_neighbors",
            content=json.dumps(output, indent=2),
            success=True,
        )


__all__ = ["KGAddEntityTool", "KGAddRelationTool", "KGNeighborsTool", "KGQueryTool"]
