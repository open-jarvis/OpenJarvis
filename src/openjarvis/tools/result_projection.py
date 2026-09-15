"""Bound tool output before it enters an inference transcript.

The authoritative result stays on ``ToolResult`` and in ``ToolEvidence``.  This
module produces only the smaller view handed back to a model.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

_DEFAULT_MAX_CHARS = 16_000
_MARKER = "[response compacted]"
_NOTICE_KEY = "__openjarvis_notice__"


def project_tool_content(content: str, *, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """Return a deterministic, bounded view of one tool result."""
    if max_chars <= 0:
        return ""
    if len(content) <= max_chars:
        return content

    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return _truncate_text(content, max_chars)

    table_projection = _project_trend_tables(payload, max_chars=max_chars)
    if table_projection is not None:
        return table_projection

    menu_projection = _project_trend_menu(payload, max_chars=max_chars)
    if menu_projection is not None:
        return menu_projection

    total_records = max(1, _count_array_records(payload))
    per_record_budget = max(32, (max_chars - 512) // total_records)
    projected = _project_json(payload, per_record_budget=per_record_budget)
    if isinstance(projected, dict):
        projected = {_NOTICE_KEY: "response compacted", **projected}
    else:
        projected = {
            _NOTICE_KEY: "response compacted",
            "data": projected,
        }

    encoded = _encode(projected)
    while len(encoded) > max_chars and per_record_budget > 32:
        per_record_budget = max(32, per_record_budget - 16)
        projected = _project_json(payload, per_record_budget=per_record_budget)
        if isinstance(projected, dict):
            projected = {_NOTICE_KEY: "response compacted", **projected}
        else:
            projected = {
                _NOTICE_KEY: "response compacted",
                "data": projected,
            }
        encoded = _encode(projected)

    return encoded if len(encoded) <= max_chars else _truncate_text(encoded, max_chars)


def _project_trend_tables(payload: Any, *, max_chars: int) -> str | None:
    """Keep the live table fields needed to choose and place an at-table order."""
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, list) or not result:
        return None
    if not all(
        isinstance(table, dict)
        and isinstance(table.get("name"), str)
        and isinstance(table.get("slug"), str)
        and isinstance(table.get("status"), str)
        for table in result
    ):
        return None

    projected = {
        _NOTICE_KEY: "response compacted",
        **{
            str(key): _compact_scalar(value, 96)
            for key, value in payload.items()
            if key != "result" and not isinstance(value, (dict, list))
        },
        "result": [
            {
                key: _compact_scalar(table[key], 96)
                for key in ("name", "slug", "status", "location")
                if key in table and not isinstance(table[key], (dict, list))
            }
            for table in result
        ],
    }
    encoded = _encode(projected)
    return encoded if len(encoded) <= max_chars else None


def _project_trend_menu(payload: Any, *, max_chars: int) -> str | None:
    """Keep every menu product visible while discarding presentation-heavy fields."""
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        return None

    products: list[dict[str, Any]] = []
    for group in result["items"]:
        if not isinstance(group, dict) or not isinstance(group.get("menuItems"), list):
            return None
        for menu_item in group["menuItems"]:
            if not isinstance(menu_item, dict):
                continue
            product = menu_item.get("product")
            if isinstance(product, dict) and isinstance(product.get("name"), str):
                products.append(product)
    if not products:
        return None

    for description_limit, first_variant_only in (
        (160, False),
        (80, False),
        (0, False),
        (80, True),
        (0, True),
    ):
        projected_result = {
            str(key): _compact_scalar(value, 96)
            for key, value in result.items()
            if key != "items" and not isinstance(value, (dict, list))
        }
        projected_result["products"] = [
            _project_menu_product(
                product,
                description_limit=description_limit,
                first_variant_only=first_variant_only,
            )
            for product in products
        ]
        projected = {
            _NOTICE_KEY: "response compacted",
            **{
                str(key): _compact_scalar(value, 96)
                for key, value in payload.items()
                if key != "result" and not isinstance(value, (dict, list))
            },
            "result": projected_result,
        }
        encoded = _encode(projected)
        if len(encoded) <= max_chars:
            return encoded
    return None


def _project_menu_product(
    product: dict[str, Any],
    *,
    description_limit: int,
    first_variant_only: bool,
) -> dict[str, Any]:
    projected = {
        key: _compact_scalar(product[key], 96)
        for key in ("slug", "name", "category", "isActive")
        if key in product and not isinstance(product[key], (dict, list))
    }
    description = product.get("description")
    if description_limit and isinstance(description, str) and description:
        projected["description"] = _compact_scalar(description, description_limit)

    variants = product.get("variants")
    if isinstance(variants, list):
        if first_variant_only:
            variants = variants[:1]
        projected["variants"] = [
            {
                key: _compact_scalar(variant[key], 96)
                for key in ("slug", "name", "price", "isActive")
                if key in variant and not isinstance(variant[key], (dict, list))
            }
            for variant in variants
            if isinstance(variant, dict)
        ]
    return projected


def _project_json(value: Any, *, per_record_budget: int) -> Any:
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, nested in value.items():
            if isinstance(nested, list):
                projected[str(key)] = [
                    _compact_record(item, per_record_budget)
                    if isinstance(item, (dict, list))
                    else _compact_scalar(item, per_record_budget)
                    for item in nested
                ]
            elif isinstance(nested, dict):
                projected[str(key)] = _project_json(
                    nested,
                    per_record_budget=per_record_budget,
                )
            else:
                projected[str(key)] = _compact_scalar(nested, 96)
        return projected
    if isinstance(value, list):
        return [
            _compact_record(item, per_record_budget)
            if isinstance(item, (dict, list))
            else _compact_scalar(item, per_record_budget)
            for item in value
        ]
    return _compact_scalar(value, 96)


def _compact_record(value: Any, budget: int) -> Any:
    if not isinstance(value, (dict, list)):
        return _compact_scalar(value, budget)

    record: dict[str, Any] = {}
    for path, leaf in _scalar_leaves(value):
        candidate = _compact_scalar(leaf, min(96, max(16, budget // 2)))
        record[path] = candidate
        if len(_encode(record)) > budget:
            record.pop(path)
            break
    if record:
        return record
    return {"__omitted__": True}


def _scalar_leaves(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _scalar_leaves(nested, path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            yield from _scalar_leaves(nested, path)
    else:
        yield prefix or "value", value


def _compact_scalar(value: Any, limit: int) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


def _count_array_records(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_array_records(nested) for nested in value.values())
    if isinstance(value, list):
        return len(value) + sum(_count_array_records(nested) for nested in value)
    return 0


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _truncate_text(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    if max_chars <= len(_MARKER):
        return _MARKER[:max_chars]
    return content[: max_chars - len(_MARKER)] + _MARKER


__all__ = ["project_tool_content"]
