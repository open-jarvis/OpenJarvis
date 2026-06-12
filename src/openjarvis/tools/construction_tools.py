"""Construction agent tools: cost catalog, projects, quotes, and contracts.

Quotes and contracts are written as print-ready HTML (plus PDF when reportlab is
installed) under ``~/.openjarvis/construction/documents`` and recorded in the
construction store so they can be linked to projects.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.construction import documents as docs
from openjarvis.construction.store import ConstructionStore
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

_STORE: Optional[ConstructionStore] = None
_DOC_DIR = DEFAULT_CONFIG_DIR / "construction" / "documents"


def _store() -> ConstructionStore:
    global _STORE
    if _STORE is None:
        _STORE = ConstructionStore()
    return _STORE


def _doc_dir() -> Path:
    return _DOC_DIR


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "document"


def _coerce_items(raw: Any) -> List[dict]:
    """Accept a list of dicts (already-parsed) for quote line items."""
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    return []


# ---------------------------------------------------------------------------
# cost_add / cost_lookup
# ---------------------------------------------------------------------------


@ToolRegistry.register("cost_add")
class CostAddTool(BaseTool):
    tool_id = "cost_add"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cost_add",
            description=(
                "Add or update a unit-cost catalog item (labor, material, or"
                " equipment) used to build quotes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Item name."},
                    "unit_cost": {"type": "number", "description": "Cost per unit."},
                    "unit": {
                        "type": "string",
                        "description": "Unit of measure (e.g. sqft, hour, each).",
                    },
                    "category": {
                        "type": "string",
                        "description": "labor | material | equipment | other.",
                    },
                },
                "required": ["name", "unit_cost"],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        name = str(params.get("name", "")).strip()
        if not name:
            return ToolResult(
                tool_name="cost_add", content="No item name provided.", success=False
            )
        try:
            unit_cost = float(params.get("unit_cost"))
        except (TypeError, ValueError):
            return ToolResult(
                tool_name="cost_add",
                content="unit_cost must be a number.",
                success=False,
            )
        item = _store().add_cost_item(
            name,
            unit_cost,
            category=str(params.get("category", "") or ""),
            unit=str(params.get("unit", "each") or "each"),
        )
        return ToolResult(
            tool_name="cost_add",
            content=(
                f"Saved '{item.name}': {item.unit_cost:,.2f} per {item.unit}"
                f"{f' [{item.category}]' if item.category else ''}."
            ),
            success=True,
            metadata={"name": item.name},
        )


@ToolRegistry.register("cost_lookup")
class CostLookupTool(BaseTool):
    tool_id = "cost_lookup"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cost_lookup",
            description="Search the unit-cost catalog by name or category.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term. Empty lists all items.",
                    },
                },
                "required": [],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query", "") or "").strip()
        items = _store().search_cost_items(query)
        if not items:
            return ToolResult(
                tool_name="cost_lookup",
                content="No catalog items found.",
                success=True,
                metadata={"count": 0},
            )
        lines = [
            f"- {i.name}: {i.unit_cost:,.2f}/{i.unit}"
            f"{f' [{i.category}]' if i.category else ''}"
            for i in items
        ]
        return ToolResult(
            tool_name="cost_lookup",
            content="\n".join(lines),
            success=True,
            metadata={"count": len(items)},
        )


# ---------------------------------------------------------------------------
# project_create / project_list / project_update_status
# ---------------------------------------------------------------------------


@ToolRegistry.register("project_create")
class ProjectCreateTool(BaseTool):
    tool_id = "project_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_create",
            description="Create a construction project record.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name."},
                    "client": {"type": "string", "description": "Client name."},
                    "status": {
                        "type": "string",
                        "description": "lead | quoted | active | completed | cancelled.",
                    },
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["name"],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        name = str(params.get("name", "")).strip()
        if not name:
            return ToolResult(
                tool_name="project_create",
                content="No project name provided.",
                success=False,
            )
        proj = _store().create_project(
            name,
            client=str(params.get("client", "") or ""),
            status=str(params.get("status", "lead") or "lead"),
            notes=str(params.get("notes", "") or ""),
        )
        return ToolResult(
            tool_name="project_create",
            content=f"Created project '{proj.name}' (id {proj.id}, {proj.status}).",
            success=True,
            metadata={"project_id": proj.id, "status": proj.status},
        )


@ToolRegistry.register("project_list")
class ProjectListTool(BaseTool):
    tool_id = "project_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_list",
            description="List construction projects, optionally filtered by status.",
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Optional status filter.",
                    },
                },
                "required": [],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        status = str(params.get("status", "") or "").strip() or None
        projects = _store().list_projects(status)
        if not projects:
            return ToolResult(
                tool_name="project_list",
                content="No projects found.",
                success=True,
                metadata={"count": 0},
            )
        lines = [
            f"- [{p.status}] {p.name}"
            f"{f' — {p.client}' if p.client else ''} (id {p.id})"
            for p in projects
        ]
        return ToolResult(
            tool_name="project_list",
            content="\n".join(lines),
            success=True,
            metadata={"count": len(projects)},
        )


@ToolRegistry.register("project_update_status")
class ProjectUpdateStatusTool(BaseTool):
    tool_id = "project_update_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="project_update_status",
            description=(
                "Update a project's status (lead, quoted, active, completed,"
                " cancelled). Identify the project by id or name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project id or name.",
                    },
                    "status": {"type": "string", "description": "New status."},
                },
                "required": ["project", "status"],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        project = str(params.get("project", "")).strip()
        status = str(params.get("status", "")).strip().lower()
        if not project or not status:
            return ToolResult(
                tool_name="project_update_status",
                content="project and status are required.",
                success=False,
            )
        store = _store()
        proj = store.get_project(project) or store.find_project_by_name(project)
        if proj is None:
            return ToolResult(
                tool_name="project_update_status",
                content=f"No project matching '{project}'.",
                success=False,
            )
        try:
            store.update_project_status(proj.id, status)
        except ValueError as exc:
            return ToolResult(
                tool_name="project_update_status", content=str(exc), success=False
            )
        return ToolResult(
            tool_name="project_update_status",
            content=f"Project '{proj.name}' is now '{status}'.",
            success=True,
            metadata={"project_id": proj.id, "status": status},
        )


# ---------------------------------------------------------------------------
# quote_create
# ---------------------------------------------------------------------------


@ToolRegistry.register("quote_create")
class QuoteCreateTool(BaseTool):
    tool_id = "quote_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="quote_create",
            description=(
                "Generate a printable quote/estimate from line items and save it"
                " as HTML (and PDF if available). Line item unit costs may be"
                " given directly or resolved from the cost catalog."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Quote title."},
                    "client": {"type": "string", "description": "Client name."},
                    "items": {
                        "type": "array",
                        "description": (
                            "Line items. Each: {description, quantity, unit?,"
                            " unit_cost? OR catalog_item}."
                        ),
                        "items": {"type": "object"},
                    },
                    "tax_rate": {
                        "type": "number",
                        "description": "Tax percentage (e.g. 8.25).",
                    },
                    "markup_rate": {
                        "type": "number",
                        "description": "Markup percentage applied to subtotal.",
                    },
                    "notes": {"type": "string", "description": "Optional notes."},
                    "project": {
                        "type": "string",
                        "description": "Optional project id/name to link.",
                    },
                },
                "required": ["title", "items"],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title", "")).strip()
        raw_items = _coerce_items(params.get("items"))
        if not title:
            return ToolResult(
                tool_name="quote_create", content="No title provided.", success=False
            )
        if not raw_items:
            return ToolResult(
                tool_name="quote_create",
                content="No line items provided.",
                success=False,
            )

        store = _store()
        line_items = docs.normalize_line_items(
            raw_items, cost_lookup=store.get_cost_item
        )
        if not line_items:
            return ToolResult(
                tool_name="quote_create",
                content="Line items could not be parsed.",
                success=False,
            )

        try:
            tax_rate = float(params.get("tax_rate", 0) or 0)
        except (TypeError, ValueError):
            tax_rate = 0.0
        try:
            markup_rate = float(params.get("markup_rate", 0) or 0)
        except (TypeError, ValueError):
            markup_rate = 0.0

        totals = docs.compute_quote_totals(
            line_items, tax_rate=tax_rate, markup_rate=markup_rate
        )
        client = str(params.get("client", "") or "")
        html_text = docs.render_quote_html(
            title=title,
            client=client,
            items=line_items,
            totals=totals,
            notes=str(params.get("notes", "") or ""),
            tax_rate=tax_rate,
            markup_rate=markup_rate,
        )

        out = _doc_dir() / f"quote-{_slug(title)}-{date.today().isoformat()}.html"
        html_path, pdf_path = docs.render_and_save(html_text, out)

        project_id = ""
        project_ref = str(params.get("project", "") or "").strip()
        if project_ref:
            proj = store.get_project(project_ref) or store.find_project_by_name(
                project_ref
            )
            if proj:
                project_id = proj.id

        store.record_document(
            doc_type="quote",
            title=title,
            path=str(html_path),
            total=totals["total"],
            project_id=project_id,
            data={"client": client, "line_count": len(line_items)},
        )

        msg = (
            f"Quote '{title}' created — total {totals['total']:,.2f}."
            f"\nSaved: {html_path}"
        )
        if pdf_path:
            msg += f"\nPDF: {pdf_path}"
        else:
            msg += "\n(Open the HTML and print to PDF, or install reportlab for PDF.)"
        return ToolResult(
            tool_name="quote_create",
            content=msg,
            success=True,
            metadata={
                "html_path": str(html_path),
                "pdf_path": str(pdf_path) if pdf_path else "",
                "total": totals["total"],
            },
        )


# ---------------------------------------------------------------------------
# contract_create
# ---------------------------------------------------------------------------


@ToolRegistry.register("contract_create")
class ContractCreateTool(BaseTool):
    tool_id = "contract_create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="contract_create",
            description=(
                "Generate a construction contract document (HTML, plus PDF if"
                " available) with scope, price, schedule, and standard terms."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Contract title."},
                    "client": {"type": "string", "description": "Client name."},
                    "contractor": {
                        "type": "string",
                        "description": "Contractor / company name.",
                    },
                    "scope": {
                        "type": "string",
                        "description": "Scope of work description.",
                    },
                    "amount": {"type": "number", "description": "Contract price."},
                    "start_date": {"type": "string", "description": "Start date."},
                    "end_date": {"type": "string", "description": "End date."},
                    "payment_terms": {
                        "type": "string",
                        "description": "Payment schedule/terms.",
                    },
                    "project": {
                        "type": "string",
                        "description": "Optional project id/name to link.",
                    },
                },
                "required": ["title", "client", "contractor", "scope", "amount"],
            },
            category="construction",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = str(params.get("title", "")).strip()
        client = str(params.get("client", "")).strip()
        contractor = str(params.get("contractor", "")).strip()
        scope = str(params.get("scope", "")).strip()
        if not (title and client and contractor and scope):
            return ToolResult(
                tool_name="contract_create",
                content="title, client, contractor, and scope are required.",
                success=False,
            )
        try:
            amount = float(params.get("amount"))
        except (TypeError, ValueError):
            return ToolResult(
                tool_name="contract_create",
                content="amount must be a number.",
                success=False,
            )

        html_text = docs.render_contract_html(
            title=title,
            client=client,
            contractor=contractor,
            scope=scope,
            amount=amount,
            start_date=str(params.get("start_date", "") or ""),
            end_date=str(params.get("end_date", "") or ""),
            payment_terms=str(params.get("payment_terms", "") or ""),
        )

        out = _doc_dir() / f"contract-{_slug(title)}-{date.today().isoformat()}.html"
        html_path, pdf_path = docs.render_and_save(html_text, out)

        store = _store()
        project_id = ""
        project_ref = str(params.get("project", "") or "").strip()
        if project_ref:
            proj = store.get_project(project_ref) or store.find_project_by_name(
                project_ref
            )
            if proj:
                project_id = proj.id
        store.record_document(
            doc_type="contract",
            title=title,
            path=str(html_path),
            total=amount,
            project_id=project_id,
            data={"client": client, "contractor": contractor},
        )

        msg = f"Contract '{title}' created — {amount:,.2f}.\nSaved: {html_path}"
        if pdf_path:
            msg += f"\nPDF: {pdf_path}"
        else:
            msg += "\n(Open the HTML and print to PDF, or install reportlab for PDF.)"
        return ToolResult(
            tool_name="contract_create",
            content=msg,
            success=True,
            metadata={
                "html_path": str(html_path),
                "pdf_path": str(pdf_path) if pdf_path else "",
                "amount": amount,
            },
        )


__all__ = [
    "CostAddTool",
    "CostLookupTool",
    "ProjectCreateTool",
    "ProjectListTool",
    "ProjectUpdateStatusTool",
    "QuoteCreateTool",
    "ContractCreateTool",
]
