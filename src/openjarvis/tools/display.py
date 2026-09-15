"""What the customer sees, as structured data on the event bus.

The LLM never emits markup. It supplies fields; the page renders them with
fixed templates and escapes every string. Anything else would be an XSS
surface and an unpredictable layout, on a screen a customer is looking at.

These tools are exempt from the mutation/observation doctrine: they do not
touch merchant state, they draw. They declare ``displays`` so the doctrine
test does not classify them as either.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from contextvars import ContextVar
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, Optional
from uuid import uuid4

from openjarvis.core.conversation import current_conversation_id
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools import evidence as _evidence
from openjarvis.tools._stubs import BaseTool, ToolSpec

if TYPE_CHECKING:
    from openjarvis.kiosk.presentation import PresentationSessionManager

DISPLAYS = {"displays": True}
_CHECKOUT_REVISION: ContextVar[int] = ContextVar("checkout_revision", default=0)

# Only these reach the page. A model that invents an "html" or "onclick" field
# gets it dropped here rather than at render time.
_ITEM_FIELDS = ("id", "name", "price", "available", "image_url", "note")
_LINE_FIELDS = (
    "line_id",
    "name",
    "size",
    "note",
    "quantity",
    "unit_price",
    "line_total",
)
_BILL_FIELDS = ("order_id", "status", "order_type", "branch", "lines", "total")
_PAYMENT_QR_FIELDS = ("order_id", "payment_slug", "status", "qr_code", "total")
_REQUIRED_PAYMENT_QR_FIELDS = ("order_id", "payment_slug", "status", "qr_code")


class _DisplayTool(BaseTool):
    def __init__(self) -> None:
        # ``_bus`` remains the direct-construction fallback used by narrow tests.
        self._bus: Optional[EventBus] = None
        # Set by SystemBuilder after external MCP discovery completes.
        self._presentation: Optional[PresentationSessionManager] = None

    def _publish(self, payload: dict[str, Any]) -> ToolResult:
        if self._presentation is not None:
            result = self._presentation.publish(payload)
            return ToolResult(
                tool_name=self.spec.name,
                content=result.content,
                success=result.success,
                usage=result.usage,
                cost_usd=result.cost_usd,
                latency_seconds=result.latency_seconds,
                metadata=dict(result.metadata),
            )
        if self._bus is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="display_unavailable: no event bus is configured",
            )
        self._bus.publish(EventType.DISPLAY_UPDATE, payload)
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=json.dumps({"shown": payload["view"]}),
        )


def _picked(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    return {key: row[key] for key in fields if key in row}


def _menu_items_from_latest_http() -> list[dict[str, Any]]:
    content = _evidence.last_result("http_request")
    start = content.find("{")
    if start < 0:
        return []
    try:
        payload = json.loads(content[start:])
    except (TypeError, json.JSONDecodeError):
        return []

    result = payload.get("result") if isinstance(payload, dict) else None
    pages = result.get("items") if isinstance(result, dict) else None
    if not isinstance(pages, list):
        return []

    items: list[dict[str, Any]] = []
    for page in pages:
        menu_items = page.get("menuItems") if isinstance(page, dict) else None
        if not isinstance(menu_items, list):
            continue
        for menu_item in menu_items:
            product = (
                menu_item.get("product") if isinstance(menu_item, dict) else None
            )
            if not isinstance(product, dict) or not product.get("name"):
                continue
            variants = product.get("variants")
            variant = variants[0] if isinstance(variants, list) and variants else {}
            if not isinstance(variant, dict):
                variant = {}
            item = {
                "id": variant.get("slug") or product.get("slug"),
                "name": product["name"],
                "price": variant.get("price"),
                "available": product.get("isActive"),
            }
            description = product.get("description")
            if isinstance(description, str) and description.strip():
                item["note"] = description
            items.append(
                {key: value for key, value in item.items() if value is not None}
            )
    return items


def _menu_customer_message(items: list[dict[str, Any]]) -> str:
    count = len(items)
    if count == 0:
        return "Đã xác minh 0 kết quả phù hợp trong dữ liệu mới nhất."

    spoken = []
    for item in items[:10]:
        name = str(item.get("name", "")).strip()
        if "price" in item:
            spoken.append(f"{name}: {item['price']}")
        else:
            spoken.append(name)
    summary = ", ".join(part for part in spoken if part)
    if count <= 10:
        return f"Đã tìm thấy {count} kết quả: {summary}."
    return (
        f"Đã tìm thấy {count} kết quả. Một số kết quả đầu: {summary}. "
        "Toàn bộ kết quả đang hiển thị trên màn hình."
    )


@ToolRegistry.register("display_menu")
class DisplayMenuTool(_DisplayTool):
    """Put freshly retrieved menu items on the customer's screen."""

    tool_id = "display_menu"

    def __init__(self) -> None:
        super().__init__()
        self._displayed: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._displayed_lock = RLock()

    def agent_context(self) -> dict[str, Any]:
        """Hand the verified on-screen rows to later turns without a tool round."""
        conversation_id = current_conversation_id()
        with self._displayed_lock:
            rows = self._displayed.get(conversation_id) if conversation_id else None
            return {"displayed_menu": [dict(row) for row in rows]} if rows else {}

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="display_menu",
            description=(
                "Show one or more freshly retrieved items on the customer's "
                "screen. For a category browse, omit items and set "
                "all_from_latest_http=true to show every product directly from "
                "the latest successful HTTP menu response. For a filtered search "
                "or recommendation, pass only the matching items. "
                "Each item: id, name, price, available, and optionally "
                "image_url and note."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Items to show, in the order to show them.",
                        "items": {"type": "object"},
                    },
                    "result_complete": {"type": "boolean"},
                    "all_from_latest_http": {
                        "type": "boolean",
                        "description": (
                            "Use every product from the latest successful "
                            "http_request menu response."
                        ),
                    },
                },
                "required": [],
            },
            category="display",
            metadata=dict(DISPLAYS),
        )

    def execute(self, **params: Any) -> ToolResult:
        rows = params.get("items") or []
        result_complete = params.get("result_complete") is True
        from_http = bool(params.get("all_from_latest_http")) and not rows
        if from_http:
            rows = _menu_items_from_latest_http()
        items = [_picked(row, _ITEM_FIELDS) for row in rows]
        picked = [i for i in items if i]
        if result_complete and len(rows) != len(picked):
            return ToolResult(
                tool_name="display_menu",
                content="menu_projection_invalid",
                success=False,
            )
        if not picked and not result_complete:
            # An empty screen published as success reads to the model (and
            # then to the customer, in its own voice) as "the menu is shown"
            # when nothing is. Refuse instead, so a model with no real items
            # to hand it -- no fresh read, nothing left in context -- gets a
            # signal to go fetch some rather than a false success to narrate.
            return ToolResult(
                tool_name="display_menu",
                content=("menu_evidence_missing" if from_http else "items_required"),
                success=False,
            )
        payload = {"view": "menu", "items": picked}
        if result_complete:
            payload.update(
                {
                    "result_complete": True,
                    "projected_count": len(rows),
                    "published_count": len(picked),
                }
            )
        result = self._publish(payload)
        if result.success and result_complete:
            result.content = json.dumps(
                {"shown": "menu", "count": len(picked), "complete": True},
                separators=(",", ":"),
            )
            result.metadata.update(
                {
                    "customer_message": _menu_customer_message(picked),
                    "completed_display": True,
                    "result_complete": True,
                    "projected_count": len(picked),
                    "published_count": len(picked),
                }
            )
            conversation_id = current_conversation_id()
            if conversation_id:
                with self._displayed_lock:
                    self._displayed[conversation_id] = [dict(item) for item in picked]
                    self._displayed.move_to_end(conversation_id)
                    while len(self._displayed) > 64:
                        self._displayed.popitem(last=False)
            return result
        message = params.get("customer_message")
        if result.success and isinstance(message, str) and message.strip():
            result.metadata["customer_message"] = message.strip()
        return result


@ToolRegistry.register("display_cart")
class DisplayCartTool(_DisplayTool):
    """Own and show the current conversation's local draft cart."""

    tool_id = "display_cart"

    def __init__(self) -> None:
        super().__init__()
        self._carts: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._order_notes: dict[str, str] = {}
        self._order_types: dict[str, str] = {}
        self._tables: dict[str, str] = {}
        self._table_names: dict[str, str] = {}
        self._cart_revisions: dict[str, int] = {}
        self._revision_sequence = 0
        self._checkout_claims: dict[str, int] = {}
        self._checkout_pending: set[str] = set()
        self._checkout_contracts: set[bytes] | None = None
        self._cart_lock = RLock()

    @property
    def spec(self) -> ToolSpec:
        item_schema = {
            "type": "object",
            "properties": {
                "variant_id": {"type": "string"},
                "name": {"type": "string"},
                "size": {"type": "string"},
                "note": {"type": "string"},
                "available": {"type": "boolean"},
                "unit_price": {"type": "integer", "minimum": 0},
                "quantity": {"type": "integer", "minimum": 1},
            },
            "required": [
                "variant_id",
                "name",
                "size",
                "unit_price",
                "quantity",
                "note",
            ],
        }
        return ToolSpec(
            name="display_cart",
            description=(
                "Manage the current conversation's local draft cart and show it "
                "on the customer's screen. Add one verified item with item or an "
                "atomic batch with items. Remove saved lines with line_ids, or set "
                "absolute quantities/notes on several lines at once with update "
                "and updates; every targeted line goes in this one atomic call "
                "(line_id alone edits a single line). Save the whole-order "
                "note, at-table/take-out choice, and a verified table selection "
                "separately. Adding does not place "
                "an order or start payment. A view is fresh state for the agent to "
                "act on, so it never ends the agent turn by itself. Resolve item "
                "facts from fresh menu evidence; do not invent them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "add",
                            "remove",
                            "update",
                            "set_order_note",
                            "set_order_type",
                            "set_table",
                            "view",
                            "clear",
                        ],
                    },
                    "item": item_schema,
                    "items": {"type": "array", "items": item_schema},
                    "line_id": {"type": "string"},
                    "line_ids": {"type": "array", "items": {"type": "string"}},
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_id": {"type": "string"},
                                "quantity": {"type": "integer", "minimum": 1},
                                "note": {"type": "string"},
                            },
                            "required": ["line_id"],
                        },
                    },
                    "quantity": {"type": "integer", "minimum": 1},
                    "note": {"type": "string"},
                    "order_note": {"type": "string"},
                    "order_type": {
                        "type": "string",
                        "enum": ["at-table", "take-out"],
                    },
                    "table": {"type": "string"},
                    "table_name": {"type": "string"},
                    "lines": {
                        "type": "array",
                        "description": "Legacy complete cart display payload.",
                        "items": {"type": "object"},
                    },
                    "total": {
                        "type": "integer",
                        "description": "Legacy complete cart display total.",
                    },
                },
                "required": ["action"],
            },
            category="display",
            metadata=dict(DISPLAYS),
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action")
        if action is not None:
            return self._manage_draft(str(action), params)
        if "lines" not in params or "total" not in params:
            return ToolResult(
                tool_name=self.spec.name,
                content="invalid_cart_action",
                success=False,
            )

        # Preserve the original direct display contract for saved procedures and
        # callers created before draft-cart actions were introduced.
        rows = params.get("lines") or []
        lines = [_picked(row, _LINE_FIELDS) for row in rows]
        try:
            total = int(params.get("total", 0) or 0)
        except (TypeError, ValueError):
            total = 0
        return self._publish(
            {"view": "cart", "lines": [line for line in lines if line], "total": total}
        )

    def _manage_draft(self, action: str, params: dict[str, Any]) -> ToolResult:
        conversation_id = current_conversation_id()
        if not conversation_id:
            return ToolResult(
                tool_name=self.spec.name,
                content="conversation_required",
                success=False,
            )
        if action not in {
            "add",
            "remove",
            "update",
            "set_order_note",
            "set_order_type",
            "set_table",
            "view",
            "clear",
        }:
            return ToolResult(
                tool_name=self.spec.name,
                content="invalid_cart_action",
                success=False,
            )

        with self._cart_lock:
            if action != "view" and conversation_id in self._checkout_pending:
                return ToolResult(
                    tool_name=self.spec.name,
                    content="checkout_in_progress",
                    success=False,
                )
            stored_lines = self._carts.get(conversation_id, [])
            lines = [dict(line) for line in stored_lines]
            stored_order_note = self._order_notes.get(conversation_id, "")
            stored_order_type = self._order_types.get(conversation_id, "")
            stored_table = self._tables.get(conversation_id, "")
            stored_table_name = self._table_names.get(conversation_id, "")
            order_note = stored_order_note
            order_type = stored_order_type
            table = stored_table
            table_name = stored_table_name
            if action == "add":
                raw_items = params.get("items")
                if raw_items is None:
                    raw_items = [params.get("item")]
                    invalid_content = "invalid_cart_item"
                else:
                    invalid_content = "invalid_cart_items"
                if not isinstance(raw_items, list) or not raw_items:
                    return ToolResult(
                        tool_name=self.spec.name,
                        content=invalid_content,
                        success=False,
                    )
                items = [self._cart_item(raw_item) for raw_item in raw_items]
                if any(item is None for item in items):
                    return ToolResult(
                        tool_name=self.spec.name,
                        content=invalid_content,
                        success=False,
                    )
                for item in items:
                    assert item is not None
                    identity = (item["variant_id"], item["size"], item["note"])
                    existing = next(
                        (
                            line
                            for line in lines
                            if (
                                line["variant_id"],
                                line["size"],
                                line["note"],
                            )
                            == identity
                        ),
                        None,
                    )
                    if existing is None:
                        lines.append(item)
                    else:
                        existing["quantity"] += item["quantity"]
                        existing["line_total"] = (
                            existing["unit_price"] * existing["quantity"]
                        )
            elif action in {"remove", "update"}:
                # One call edits every targeted line: a turn ends after a
                # successful display batch, so edits spread over several
                # calls would stop after the first. ``lines`` is a copy, so
                # an early return below leaves the saved draft untouched.
                batch = params.get("line_ids" if action == "remove" else "updates")
                if batch is None:
                    targets = [
                        {
                            "line_id": params.get("line_id"),
                            "quantity": params.get("quantity"),
                            "note": params.get("note"),
                        }
                    ]
                elif action == "remove" and isinstance(batch, list):
                    targets = [{"line_id": line_id} for line_id in batch]
                else:
                    targets = batch
                if (
                    not isinstance(targets, list)
                    or not targets
                    or not all(
                        isinstance(target, dict)
                        and isinstance(target.get("line_id"), str)
                        and target["line_id"].strip()
                        for target in targets
                    )
                ):
                    return ToolResult(
                        tool_name=self.spec.name,
                        content="invalid_cart_line",
                        success=False,
                    )
                target_ids = [target["line_id"].strip() for target in targets]
                if len(set(target_ids)) != len(target_ids):
                    return ToolResult(
                        tool_name=self.spec.name,
                        content="invalid_cart_line",
                        success=False,
                    )
                positions = {line["line_id"]: index for index, line in enumerate(lines)}
                if any(line_id not in positions for line_id in target_ids):
                    return ToolResult(
                        tool_name=self.spec.name,
                        content="cart_line_not_found",
                        success=False,
                    )
                if action == "remove":
                    removed = set(target_ids)
                    lines = [line for line in lines if line["line_id"] not in removed]
                else:
                    for target, line_id in zip(targets, target_ids):
                        line = lines[positions[line_id]]
                        quantity = target.get("quantity")
                        note = target.get("note")
                        if quantity is None and note is None:
                            return ToolResult(
                                tool_name=self.spec.name,
                                content="cart_update_required",
                                success=False,
                            )
                        if quantity is not None and (
                            isinstance(quantity, bool)
                            or not isinstance(quantity, int)
                            or quantity < 1
                        ):
                            return ToolResult(
                                tool_name=self.spec.name,
                                content="invalid_cart_quantity",
                                success=False,
                            )
                        if note is not None and not isinstance(note, str):
                            return ToolResult(
                                tool_name=self.spec.name,
                                content="invalid_cart_note",
                                success=False,
                            )
                        if quantity is not None:
                            line["quantity"] = quantity
                        if note is not None:
                            line["note"] = note.strip()
                        line["line_total"] = line["unit_price"] * line["quantity"]
            elif action == "set_order_note":
                value = params.get("order_note")
                if not isinstance(value, str):
                    return ToolResult(
                        tool_name=self.spec.name,
                        content="invalid_order_note",
                        success=False,
                    )
                order_note = value.strip()
            elif action == "set_order_type":
                value = params.get("order_type")
                if value not in {"at-table", "take-out"}:
                    return ToolResult(
                        tool_name=self.spec.name,
                        content="invalid_order_type",
                        success=False,
                    )
                order_type = value
                if order_type == "take-out":
                    table = ""
                    table_name = ""
            elif action == "set_table":
                value = params.get("table")
                name = params.get("table_name")
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or not isinstance(name, str)
                    or not name.strip()
                ):
                    return ToolResult(
                        tool_name=self.spec.name,
                        content="invalid_cart_table",
                        success=False,
                    )
                table = value.strip()
                table_name = name.strip()
                order_type = "at-table"
            elif action == "clear":
                lines = []
                order_note = ""
                order_type = ""
                table = ""
                table_name = ""

            total = sum(line["line_total"] for line in lines)
            payload_lines = [_picked(line, _LINE_FIELDS) for line in lines]
            published = self._publish(
                {
                    "view": "cart",
                    "lines": payload_lines,
                    "total": total,
                    "order_note": order_note,
                    "order_type": order_type,
                    "table": table,
                    "table_name": table_name,
                }
            )
            if not published.success:
                return published

            self._carts[conversation_id] = lines
            self._carts.move_to_end(conversation_id)
            self._order_notes[conversation_id] = order_note
            self._order_types[conversation_id] = order_type
            self._tables[conversation_id] = table
            self._table_names[conversation_id] = table_name
            revision = self._cart_revisions.get(conversation_id, 0)
            if (
                lines != stored_lines
                or order_note != stored_order_note
                or order_type != stored_order_type
                or table != stored_table
                or table_name != stored_table_name
            ):
                self._revision_sequence += 1
                revision = self._revision_sequence
                self._checkout_claims.pop(conversation_id, None)
            self._cart_revisions[conversation_id] = revision
            while len(self._carts) > 64:
                stale_id, _ = self._carts.popitem(last=False)
                self._cart_revisions.pop(stale_id, None)
                self._checkout_claims.pop(stale_id, None)
                self._order_notes.pop(stale_id, None)
                self._order_types.pop(stale_id, None)
                self._tables.pop(stale_id, None)
                self._table_names.pop(stale_id, None)

            cart = {
                "lines": lines,
                "total": total,
                "order_note": order_note,
                "order_type": order_type,
                "table": table,
                "table_name": table_name,
            }
            metadata = dict(published.metadata or {})
            metadata["cart_revision"] = revision
            if action == "view":
                metadata["continue_agent"] = True
            return ToolResult(
                tool_name=self.spec.name,
                content=json.dumps({"cart": cart, "shown": "cart"}, ensure_ascii=False),
                success=True,
                metadata=metadata,
            )

    def current_snapshot(self) -> dict[str, Any] | None:
        """Return a copy of this conversation's draft and revision."""
        conversation_id = current_conversation_id()
        if not conversation_id:
            return None
        with self._cart_lock:
            lines = [dict(line) for line in self._carts.get(conversation_id, [])]
            return {
                "revision": self._cart_revisions.get(conversation_id, 0),
                "lines": lines,
                "total": sum(line["line_total"] for line in lines),
                "order_note": self._order_notes.get(conversation_id, ""),
                "order_type": self._order_types.get(conversation_id, ""),
                "table": self._tables.get(conversation_id, ""),
                "table_name": self._table_names.get(conversation_id, ""),
            }

    def begin_checkout(
        self,
        nonce: str,
        revision: Any,
        contract: bytes = b"",
        *,
        replacement_lines: Any = None,
        order_type: Any = None,
        order_note: Any = None,
        table: Any = None,
    ) -> dict[str, Any]:
        """Reserve the exact draft once before any merchant write."""
        from openjarvis.core.conversation import claim_turn_nonce

        owner = current_conversation_id()
        with self._cart_lock:
            if not owner:
                raise ValueError("checkout requires a conversation scope")
            if (
                self._checkout_contracts is not None
                and contract not in self._checkout_contracts
            ):
                raise ValueError("checkout contract is not active")
            if replacement_lines is not None and revision is not None:
                raise ValueError("provide cart lines or cart revision, not both")
            normalized_lines = None
            normalized_order_type = order_type
            normalized_order_note = order_note
            normalized_table = table
            if normalized_order_type is not None and normalized_order_type not in {
                "at-table",
                "take-out",
            }:
                raise ValueError("checkout order type is invalid")
            if normalized_table is not None:
                if not isinstance(normalized_table, str):
                    raise ValueError("checkout table is invalid")
                normalized_table = normalized_table.strip()
            if normalized_order_type == "at-table" and not normalized_table:
                raise ValueError("checkout at-table order requires a table")
            if normalized_order_type == "take-out" and normalized_table:
                raise ValueError("checkout take-out order cannot use a table")
            if normalized_order_note is not None:
                if not isinstance(normalized_order_note, str):
                    raise ValueError("checkout order note is invalid")
                normalized_order_note = normalized_order_note.strip()
            if replacement_lines is not None:
                if not isinstance(replacement_lines, list) or not replacement_lines:
                    raise ValueError("replacement cart is empty")
                normalized_lines = [self._cart_item(line) for line in replacement_lines]
                if any(line is None for line in normalized_lines):
                    raise ValueError("replacement cart contains an invalid item")
                keys = [
                    (line["variant_id"], line["size"], line["note"])
                    for line in normalized_lines
                ]
                if len(keys) != len(set(keys)):
                    raise ValueError("replacement cart contains duplicate items")
            else:
                snapshot = self.current_snapshot()
                if (
                    not snapshot
                    or not snapshot["lines"]
                    or type(revision) is not int
                    or snapshot["revision"] != revision
                ):
                    raise ValueError("cart revision is stale or empty")
                if (
                    normalized_order_type is not None
                    and snapshot["order_type"] != normalized_order_type
                ):
                    raise ValueError("checkout order type does not match the draft")
                if (
                    normalized_order_note is not None
                    and snapshot["order_note"] != normalized_order_note
                ):
                    raise ValueError("checkout order note does not match the draft")
                if (
                    normalized_table is not None
                    and snapshot["table"] != normalized_table
                ):
                    raise ValueError("checkout table does not match the draft")
            if owner in self._checkout_pending or (
                normalized_lines is None
                and self._checkout_claims.get(owner) == revision
            ):
                raise ValueError("cart revision already consumed")
            if not claim_turn_nonce(nonce):
                raise ValueError("turn nonce is stale or consumed")
            if normalized_lines is not None:
                self._revision_sequence += 1
                revision = self._revision_sequence
                self._carts[owner] = normalized_lines
                self._cart_revisions[owner] = revision
                self._order_types[owner] = normalized_order_type or ""
                self._order_notes[owner] = normalized_order_note or ""
                self._tables[owner] = normalized_table or ""
                self._table_names[owner] = ""
                snapshot = {
                    "revision": revision,
                    "lines": [dict(line) for line in normalized_lines],
                    "total": sum(line["line_total"] for line in normalized_lines),
                    "order_note": self._order_notes[owner],
                    "order_type": self._order_types[owner],
                    "table": self._tables[owner],
                    "table_name": self._table_names[owner],
                }
            self._checkout_claims[owner] = revision
            self._checkout_pending.add(owner)
            _CHECKOUT_REVISION.set(revision)
            return snapshot

    def checkout_write_allowed(self) -> bool:
        """Only the reserved composite worker may issue its dependent writes."""
        from openjarvis.core.conversation import (
            current_turn_nonce,
            turn_nonce_is_active,
        )

        owner = current_conversation_id()
        with self._cart_lock:
            return bool(
                owner in self._checkout_pending
                and self._checkout_claims.get(owner) == _CHECKOUT_REVISION.get()
                and turn_nonce_is_active(current_turn_nonce())
            )

    def end_checkout(self) -> None:
        """Release edits, retaining the claim after ambiguous write failures."""
        with self._cart_lock:
            self._checkout_pending.discard(current_conversation_id())
            _CHECKOUT_REVISION.set(0)

    def agent_context(self) -> dict[str, Any]:
        """Supply the current draft to the first inference without a tool round."""
        snapshot = self.current_snapshot()
        return {"draft_cart": snapshot} if snapshot and snapshot["lines"] else {}

    def settle_current(self) -> bool:
        """Forget the current draft after its merchant payment is verified."""
        conversation_id = current_conversation_id()
        if not conversation_id:
            return False
        with self._cart_lock:
            removed = self._carts.pop(conversation_id, None) is not None
            self._cart_revisions.pop(conversation_id, None)
            self._checkout_claims.pop(conversation_id, None)
            self._order_notes.pop(conversation_id, None)
            self._order_types.pop(conversation_id, None)
            self._tables.pop(conversation_id, None)
            self._table_names.pop(conversation_id, None)
            return removed

    @staticmethod
    def _cart_item(raw_item: Any) -> dict[str, Any] | None:
        if not isinstance(raw_item, dict):
            return None
        variant_id = raw_item.get("variant_id")
        name = raw_item.get("name")
        unit_price = raw_item.get("unit_price")
        quantity = raw_item.get("quantity")
        if not isinstance(variant_id, str) or not variant_id.strip():
            return None
        if not isinstance(name, str) or not name.strip():
            return None
        if "available" in raw_item and raw_item.get("available") is not True:
            return None
        if isinstance(unit_price, bool) or not isinstance(unit_price, int):
            return None
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            return None
        if unit_price < 0 or quantity < 1:
            return None
        size = raw_item.get("size", "")
        note = raw_item.get("note", "")
        if not isinstance(size, str) or not isinstance(note, str):
            return None
        return {
            "line_id": uuid4().hex,
            "variant_id": variant_id.strip(),
            "name": name.strip(),
            "size": size.strip(),
            "note": note.strip(),
            "quantity": quantity,
            "unit_price": unit_price,
            "line_total": unit_price * quantity,
        }


@ToolRegistry.register("display_bill")
class DisplayBillTool(_DisplayTool):
    """Put a merchant-read order on the customer's screen."""

    tool_id = "display_bill"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="display_bill",
            description=(
                "Show an order bill exactly as order_verify read it from the "
                "merchant. Pass order_id, status, order_type, branch, lines "
                "and total from that verified readback; do not invent them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "status": {"type": "string"},
                    "order_type": {"type": "string"},
                    "branch": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "object"}},
                    "total": {"type": "integer"},
                },
                "required": list(_BILL_FIELDS),
            },
            category="display",
            metadata=dict(DISPLAYS),
        )

    def execute(self, **params: Any) -> ToolResult:
        bill = _picked(params, _BILL_FIELDS)
        rows = bill.get("lines") or []
        lines = [_picked(row, _LINE_FIELDS) for row in rows]
        try:
            total = int(bill.get("total", 0) or 0)
        except (TypeError, ValueError):
            total = 0
        bill["lines"] = [line for line in lines if line]
        bill["total"] = total
        return self._publish({"view": "bill", **bill})


@ToolRegistry.register("display_payment_qr")
class DisplayPaymentQrTool(_DisplayTool):
    """Put a verified merchant payment QR value on the customer's screen."""

    tool_id = "display_payment_qr"

    def __init__(self) -> None:
        super().__init__()
        # Set by SystemBuilder from config. Empty means no QR can be displayed:
        # provenance is required, never assumed.
        self._payment_trusted_origins: tuple = ()
        self._cart_settler: Optional[Callable[[], bool]] = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="display_payment_qr",
            description=(
                "Show the QR value from a payment response. Omit qr_code to "
                "reuse it directly from the latest trusted http_request JSON "
                "in this conversation instead of copying a large base64 value. "
                "A verified payment settles this conversation's draft cart."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "payment_slug": {"type": "string"},
                    "status": {"type": "string"},
                    "qr_code": {"type": "string"},
                    "total": {
                        "type": "integer",
                        "description": "Payment amount in VND.",
                    },
                    "customer_message": {
                        "type": "string",
                        "description": (
                            "Final spoken reply in the customer's language, using the "
                            "verified order and payment. Returned only after display "
                            "succeeds, avoiding another inference just to announce QR."
                        ),
                    },
                },
                "required": ["order_id", "payment_slug", "status", "customer_message"],
            },
            category="display",
            metadata=dict(DISPLAYS),
        )

    def execute(self, **params: Any) -> ToolResult:
        qr_code = params.get("qr_code")
        if qr_code is None:
            qr_code = _evidence.latest_json_string(
                "qrCode",
                from_tool="http_request",
                require_ok=True,
                trusted_origins=self._payment_trusted_origins,
            )
            params = {**params, "qr_code": qr_code}
        elif not isinstance(qr_code, str) or not qr_code.strip():
            return ToolResult(
                tool_name="display_payment_qr",
                content="qr_code_required",
                success=False,
            )

        total = params.get("total")
        if total is None:
            total = _evidence.latest_json_number(
                "amount",
                from_tool="http_request",
                require_ok=True,
                trusted_origins=self._payment_trusted_origins,
            ) or _evidence.latest_json_number(
                "total",
                from_tool="http_request",
                require_ok=True,
                trusted_origins=self._payment_trusted_origins,
            )
        if total is not None:
            try:
                params = {**params, "total": int(total)}
            except (TypeError, ValueError):
                pass

        payment = _picked(params, _PAYMENT_QR_FIELDS)
        complete = all(
            isinstance(payment.get(field), str) and payment[field].strip()
            for field in _REQUIRED_PAYMENT_QR_FIELDS
        )
        # Four conditions: this exact string, from http_request, with a 2xx,
        # from a trusted origin, in this conversation. observed_in_tool_output
        # treats empty trusted_origins as "no origin restriction", so an empty
        # configured list is checked here instead -- it must refuse everything.
        verified = (
            complete
            and bool(self._payment_trusted_origins)
            and _evidence.observed_in_tool_output(
                qr_code,
                from_tool="http_request",
                require_ok=True,
                trusted_origins=self._payment_trusted_origins,
            )
        )
        if not verified:
            return ToolResult(
                tool_name="display_payment_qr",
                content="payment_evidence_missing",
                success=False,
            )
        if self._cart_settler is not None:
            self._cart_settler()
        result = self._publish({"view": "payment_qr", **payment})
        message = params.get("customer_message")
        if result.success and isinstance(message, str) and message.strip():
            result.metadata["customer_message"] = message.strip()
        return result


@ToolRegistry.register("display_clear")
class DisplayClearTool(_DisplayTool):
    """Return the screen to its idle state."""

    tool_id = "display_clear"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="display_clear",
            description="Clear the customer's screen back to its idle state.",
            parameters={"type": "object", "properties": {}},
            category="display",
            metadata=dict(DISPLAYS),
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._publish({"view": "none"})
