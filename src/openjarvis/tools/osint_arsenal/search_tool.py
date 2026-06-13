"""OSINT Arsenal Search Tool for OpenJarvis Agents.

Enables agents to query the awesome-osint-arsenal knowledge base
to recommend tools for specific OSINT tasks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_JSON_PATH = Path(__file__).parent / "osint_tools.json"
ARSENAL_README_SOURCE = Path("/Users/kinggeorge/awesome-osint-arsenal/README.md")

# ---------------------------------------------------------------------------
# In-Memory Index (lazy-loaded)
# ---------------------------------------------------------------------------

_index: list[dict[str, Any]] | None = None


def _ensure_index() -> list[dict[str, Any]]:
    """Lazy-load the OSINT tool index from JSON."""
    global _index
    if _index is not None:
        return _index

    # Auto-generate JSON if missing
    if not DEFAULT_JSON_PATH.exists() and ARSENAL_README_SOURCE.exists():
        from openjarvis.tools.osint_arsenal.parser import parse_readme

        tools = parse_readme(ARSENAL_README_SOURCE)
        DEFAULT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEFAULT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(tools, f, indent=2, ensure_ascii=False)

    if DEFAULT_JSON_PATH.exists():
        with open(DEFAULT_JSON_PATH, "r", encoding="utf-8") as f:
            _index = json.load(f)
    else:
        _index = []

    return _index


def _score(tool: dict[str, Any], query_words: set[str]) -> float:
    """Compute relevance score for a tool against query words."""
    score = 0.0
    text = " ".join([
        tool.get("name", ""),
        tool.get("description", ""),
        tool.get("category", ""),
        " ".join(tool.get("tags", [])),
    ]).lower()

    for word in query_words:
        if word in text:
            # Higher weight for name/category matches
            if word in tool.get("name", "").lower():
                score += 3.0
            elif word in tool.get("category", "").lower():
                score += 2.0
            else:
                score += 1.0

    return score


# ---------------------------------------------------------------------------
# Tool Implementation
# ---------------------------------------------------------------------------


@ToolRegistry.register("osint_search")
class OsintSearchTool(BaseTool):
    """Search the awesome-osint-arsenal knowledge base for OSINT tools."""

    tool_id = "osint_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="osint_search",
            description=(
                "Search the OSINT Arsenal knowledge base for open-source intelligence tools. "
                "Given a task or target type (e.g. 'LinkedIn recon', 'email breach hunting', "
                "'subdomain enumeration'), returns the top relevant tools with descriptions and links."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The OSINT task or target type to search for. "
                            "Examples: 'LinkedIn username recon', 'email breach lookup', "
                            "'dark web search engine', 'subdomain enumeration'"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 5).",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional category filter. Examples: 'Username & Social Media OSINT', "
                            "'Email OSINT Tools', 'Domain & IP OSINT'"
                        ),
                    },
                },
                "required": ["query"],
            },
            category="osint",
            cost_estimate=0.0,
            latency_estimate=0.05,
        )

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        limit = params.get("limit", 5)
        category_filter = params.get("category", "")

        if not query:
            return ToolResult(
                tool_name="osint_search",
                content="Error: query parameter is required.",
                success=False,
            )

        index = _ensure_index()
        if not index:
            return ToolResult(
                tool_name="osint_search",
                content="Error: OSINT Arsenal index not found. Run parser first.",
                success=False,
            )

        # Normalize query
        query_words = set(re.findall(r"[a-zA-Z0-9]+", query.lower()))
        if not query_words:
            query_words = {query.lower()}

        # Score and filter
        scored = []
        for tool in index:
            if category_filter and category_filter.lower() not in tool.get("category", "").lower():
                continue
            score = _score(tool, query_words)
            if score > 0:
                scored.append((score, tool))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        if not top:
            return ToolResult(
                tool_name="osint_search",
                content=f"No OSINT tools found for query: '{query}'",
                success=True,
            )

        # Check if user wants to execute the top tool automatically
        run_keywords = {"run", "execute", "use", "launch", "start", "fire"}
        wants_execution = bool(run_keywords & query_words)
        exec_results: list[str] = []

        if wants_execution:
            from openjarvis.tools.osint_arsenal.exec_tool import OsintExecTool

            exec_tool = OsintExecTool()
            for _score_val, tool in top[:1]:
                target = params.get("target", "")
                if not target:
                    # Heuristic: try to extract a domain/IP/email from the query
                    target_match = re.search(
                        r"([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|[^\s@]+@[^\s@]+\.[^\s@]+)",
                        query,
                    )
                    if target_match:
                        target = target_match.group(0)
                if target:
                    er = exec_tool.execute(tool_name=tool["name"], target=target)
                    exec_results.append(er.content)

        # Format results
        lines = [f"OSINT Arsenal Results for '{query}':", ""]
        for rank, (score, tool) in enumerate(top, 1):
            lines.append(f"{rank}. {tool['name']} ({tool['category']})")
            lines.append(f"   Description: {tool['description']}")
            if tool.get("url"):
                lines.append(f"   URL: {tool['url']}")
            if tool.get("install_command"):
                lines.append(f"   Install: {tool['install_command']}")
            lines.append("")

        if exec_results:
            lines.append("Execution Results:")
            lines.append("")
            for er in exec_results:
                lines.append(er)
                lines.append("")

        content = "\n".join(lines)
        return ToolResult(
            tool_name="osint_search",
            content=content,
            success=True,
            metadata={
                "results_count": len(top),
                "query": query,
                "executed": len(exec_results) > 0,
            },
        )


__all__ = ["OsintSearchTool"]
