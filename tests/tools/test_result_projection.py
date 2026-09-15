"""The model sees a bounded view while tools retain their full result."""

from __future__ import annotations

import json

from openjarvis.tools.result_projection import project_tool_content


def _large_catalogue() -> str:
    records = [
        {
            "id": f"item-{index:03d}",
            "name": f"Drink {index:03d}",
            "price": 30_000 + index,
            "description": f"Description {index:03d} " + ("x" * 900),
        }
        for index in range(121)
    ]
    return json.dumps({"statusCode": 200, "products": records}, ensure_ascii=False)


def _large_trend_menu() -> str:
    menu_items = []
    for index in range(41):
        menu_items.append(
            {
                "product": {
                    "slug": f"product-{index:02d}",
                    "name": f"Menu item {index:02d}",
                    "description": f"Ingredient {index:02d} " + ("x" * 240),
                    "isActive": True,
                    "images": [{"url": "https://example.test/" + ("y" * 320)}],
                    "variants": [
                        {
                            "slug": f"variant-{index:02d}",
                            "name": "Standard",
                            "price": 30_000 + index,
                            "isActive": True,
                        }
                    ],
                }
            }
        )
    return json.dumps(
        {
            "statusCode": 200,
            "result": {
                "items": [{"menuItems": menu_items}],
                "hasNext": False,
            },
        },
        ensure_ascii=False,
    )


def _large_trend_tables() -> str:
    tables = [
        {
            "name": str(index),
            "location": "Ground floor" if index <= 50 else "First floor",
            "xPosition": None,
            "yPosition": None,
            "status": "reserved" if index in {2, 3, 50, 79} else "available",
            "createdAt": "Sat Apr 19 2025 09:05:09 GMT+0700 (Indochina Time)",
            "slug": f"table-{index:03d}",
        }
        for index in range(1, 101)
    ]
    return json.dumps(
        {"statusCode": 200, "message": "ok", "result": tables},
        ensure_ascii=False,
    )


def test_small_json_is_unchanged() -> None:
    content = '{"orderId":"ord-7","status":"pending"}'

    assert project_tool_content(content) == content


def test_large_json_is_bounded_and_represents_the_whole_array() -> None:
    content = _large_catalogue()

    projected = project_tool_content(content, max_chars=16_000)

    assert len(content) > 100_000
    assert len(projected) <= 16_000
    assert "item-000" in projected
    assert "item-060" in projected
    assert "item-120" in projected
    assert "response compacted" in projected


def test_large_json_keeps_top_level_scalars() -> None:
    content = _large_catalogue()

    projected = project_tool_content(content, max_chars=2_000)

    assert '"statusCode":200' in projected


def test_large_trend_menu_keeps_every_product_for_model_side_filtering() -> None:
    content = _large_trend_menu()

    projected = project_tool_content(content, max_chars=16_000)

    assert len(content) > 16_000
    assert len(projected) <= 16_000
    assert "Menu item 00" in projected
    assert "Menu item 20" in projected
    assert "Menu item 40" in projected
    assert "variant-40" in projected
    assert "Ingredient 40" in projected
    assert "https://example.test" not in projected


def test_large_trend_table_list_keeps_live_status_and_order_slug() -> None:
    content = _large_trend_tables()

    projected = project_tool_content(content, max_chars=16_000)
    payload = json.loads(projected)

    assert len(content) > 16_000
    assert len(projected) < len(content)
    assert len(projected) <= 16_000
    assert payload["result"][0] == {
        "name": "1",
        "slug": "table-001",
        "status": "available",
        "location": "Ground floor",
    }
    assert payload["result"][49]["slug"] == "table-050"
    assert payload["result"][49]["status"] == "reserved"
    assert payload["result"][99]["slug"] == "table-100"
    assert "createdAt" not in projected
    assert "xPosition" not in projected


def test_large_non_json_text_has_an_explicit_marker() -> None:
    projected = project_tool_content("z" * 1_000, max_chars=120)

    assert len(projected) <= 120
    assert projected.endswith("[response compacted]")
