"""Digest collection tool — fetches recent data from configured connectors."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from openjarvis.core.registry import ConnectorRegistry, ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("digest_collect")
class DigestCollectTool(BaseTool):
    """Collect recent data from multiple connectors for digest synthesis."""

    tool_id = "digest_collect"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="digest_collect",
            description=(
                "Fetch recent data from configured connectors (email, calendar, "
                "health, tasks, etc.) and return a structured summary for digest "
                "synthesis."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of connector IDs to fetch from "
                            "(e.g., ['gmail', 'oura', 'gcalendar'])."
                        ),
                    },
                    "hours_back": {
                        "type": "number",
                        "description": "How many hours back to look (default: 24).",
                    },
                },
                "required": ["sources"],
            },
            category="data",
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        sources: List[str] = params.get("sources", [])
        hours_back: float = params.get("hours_back", 24)
        since = datetime.now() - timedelta(hours=hours_back)

        collected: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for source in sources:
            if not ConnectorRegistry.contains(source):
                errors.append(f"Connector '{source}' not available")
                continue

            try:
                connector_cls = ConnectorRegistry.get(source)
                connector = connector_cls()

                if not connector.is_connected():
                    errors.append(
                        f"Connector '{source}' not connected (no credentials)"
                    )
                    continue

                docs = list(connector.sync(since=since))
                collected[source] = [
                    {
                        "title": d.title,
                        "content": d.content,
                        "doc_type": d.doc_type,
                        "author": d.author,
                        "timestamp": d.timestamp.isoformat(),
                        "metadata": d.metadata,
                    }
                    for d in docs
                ]
            except Exception as exc:
                errors.append(f"Error fetching from '{source}': {exc}")

        summary_parts = []
        for source, docs in collected.items():
            summary_parts.append(f"## {source} ({len(docs)} items)")
            for doc in docs:
                summary_parts.append(json.dumps(doc, default=str))

        if errors:
            summary_parts.append("\n## Errors")
            summary_parts.extend(errors)

        return ToolResult(
            tool_name="digest_collect",
            content="\n".join(summary_parts),
            success=True,
            metadata={
                "sources_queried": sources,
                "sources_ok": list(collected.keys()),
                "sources_failed": errors,
                "total_items": sum(len(v) for v in collected.values()),
            },
        )
