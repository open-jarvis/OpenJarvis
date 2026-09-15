"""Display tools publish structured data. They never emit markup."""

from __future__ import annotations

import json

import pytest

from openjarvis.core.conversation import conversation_scope
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult
from openjarvis.kiosk.presentation import PresentationSessionManager
from openjarvis.tools import evidence
from openjarvis.tools.display import (
    DisplayBillTool,
    DisplayCartTool,
    DisplayClearTool,
    DisplayMenuTool,
    DisplayPaymentQrTool,
)


class _Recorder:
    def __init__(self, bus):
        self.events = []
        bus.subscribe(EventType.DISPLAY_UPDATE, self.events.append)


class _FakePresentationManager:
    def __init__(self) -> None:
        self.payloads = []

    def publish(self, payload):
        self.payloads.append(payload)
        return ToolResult(tool_name="presentation", content="presentation_published")


def _wired(cls):
    bus = EventBus()
    recorder = _Recorder(bus)
    tool = cls()
    tool._bus = bus
    return tool, recorder


def test_display_tools_are_neither_mutations_nor_observations():
    """They draw; they do not touch merchant state, so the doctrine test
    must not classify them."""
    for cls in (
        DisplayMenuTool,
        DisplayCartTool,
        DisplayBillTool,
        DisplayPaymentQrTool,
        DisplayClearTool,
    ):
        metadata = cls().spec.metadata
        assert metadata == {"displays": True}
        assert cls().spec.category == "display"


def test_display_menu_publishes_the_items_it_was_given():
    tool, recorder = _wired(DisplayMenuTool)
    result = tool.execute(
        items=[
            {"id": "latte", "name": "Latte", "price": 45000, "available": True},
        ]
    )

    assert result.success
    assert len(recorder.events) == 1
    data = recorder.events[0].data
    assert data["view"] == "menu"
    assert data["items"][0]["name"] == "Latte"


def test_display_menu_keeps_only_the_fields_the_page_renders():
    """Anything else the model invents must not reach the page."""
    tool, recorder = _wired(DisplayMenuTool)
    tool.execute(
        items=[
            {
                "id": "latte",
                "name": "Latte",
                "price": 45000,
                "available": True,
                "html": "<script>alert(1)</script>",
                "onclick": "steal()",
            }
        ]
    )

    item = recorder.events[0].data["items"][0]
    assert set(item) <= {"id", "name", "price", "available", "image_url", "note"}


def test_display_cart_publishes_lines_and_total():
    tool, recorder = _wired(DisplayCartTool)
    tool.execute(
        lines=[{"name": "Latte", "quantity": 2, "line_total": 102000}],
        total=102000,
    )

    data = recorder.events[0].data
    assert data["view"] == "cart"
    assert data["total"] == 102000
    assert data["lines"][0]["quantity"] == 2


def test_display_cart_advertises_conversation_draft_actions():
    params = DisplayCartTool().spec.parameters

    assert params["required"] == ["action"]
    assert params["properties"]["action"]["enum"] == [
        "add",
        "remove",
        "update",
        "set_order_note",
        "set_order_type",
        "set_table",
        "view",
        "clear",
    ]
    assert params["properties"]["item"]["required"] == [
        "variant_id",
        "name",
        "size",
        "unit_price",
        "quantity",
        "note",
    ]
    assert params["properties"]["items"]["items"] == params["properties"]["item"]
    assert params["properties"]["order_type"]["enum"] == ["at-table", "take-out"]
    assert params["properties"]["table"]["type"] == "string"
    assert params["properties"]["table_name"]["type"] == "string"


def test_display_cart_rejects_an_item_without_an_action():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-missing-action"):
        result = tool.execute(
            item={
                "variant_id": "pizza-standard",
                "name": "Pizza Truyền Thống Ý",
                "size": "tiêu chuẩn",
                "unit_price": 107000,
                "quantity": 2,
                "note": "",
            }
        )

    assert result.success is False
    assert result.content == "invalid_cart_action"
    assert recorder.events == []


def test_display_cart_keeps_size_and_note_but_drops_invented_fields():
    """The screen is what a person at the shop reads to make the drink --
    size and note must survive, and a model-invented key must not."""
    tool, recorder = _wired(DisplayCartTool)
    tool.execute(
        lines=[
            {
                "name": "Latte",
                "size": "Lớn",
                "note": "ít đường",
                "quantity": 2,
                "line_total": 122000,
                "html": "<b>x</b>",
            }
        ],
        total=122000,
    )

    line = recorder.events[0].data["lines"][0]
    assert line["size"] == "Lớn"
    assert line["note"] == "ít đường"
    assert set(line) <= {
        "line_id",
        "name",
        "size",
        "note",
        "quantity",
        "unit_price",
        "line_total",
    }
    assert "html" not in line


def test_display_cart_batch_add_is_atomic_and_publishes_once():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-batch"):
        result = tool.execute(
            action="add",
            items=[
                {
                    "variant_id": "cola-standard",
                    "name": "Coca Cola",
                    "unit_price": 25_000,
                    "quantity": 1,
                },
                {
                    "variant_id": "coconut-standard",
                    "name": "Nước dừa",
                    "unit_price": 35_000,
                    "quantity": 2,
                    "note": "",
                },
            ],
        )

    assert result.success
    cart = json.loads(result.content)["cart"]
    assert [(line["name"], line["quantity"]) for line in cart["lines"]] == [
        ("Coca Cola", 1),
        ("Nước dừa", 2),
    ]
    assert len({line["line_id"] for line in cart["lines"]}) == 2
    assert cart["total"] == 95_000
    assert cart["order_note"] == ""
    assert cart["order_type"] == ""
    assert len(recorder.events) == 1


def test_display_cart_rejects_an_invalid_batch_without_mutating_or_publishing():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-invalid-batch"):
        before = tool.execute(
            action="add",
            item={
                "variant_id": "coffee-standard",
                "name": "Coffee",
                "unit_price": 40_000,
                "quantity": 1,
            },
        )
        result = tool.execute(
            action="add",
            items=[
                {
                    "variant_id": "cola-standard",
                    "name": "Coca Cola",
                    "unit_price": 25_000,
                    "quantity": 1,
                },
                {"variant_id": "missing-fields"},
            ],
        )
        snapshot = tool.current_snapshot()

    assert not result.success
    assert result.content == "invalid_cart_items"
    assert snapshot is not None
    assert [line["name"] for line in snapshot["lines"]] == ["Coffee"]
    assert snapshot["revision"] == before.metadata["cart_revision"]
    assert len(recorder.events) == 1


def test_display_cart_updates_and_removes_a_stable_line_identity():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-edit"):
        added = tool.execute(
            action="add",
            items=[
                {
                    "variant_id": "salt-coffee",
                    "name": "Cà phê muối",
                    "unit_price": 45_000,
                    "quantity": 1,
                },
                {
                    "variant_id": "milk-coffee",
                    "name": "Cà phê sữa",
                    "unit_price": 40_000,
                    "quantity": 1,
                },
            ],
        )
        lines = json.loads(added.content)["cart"]["lines"]
        salt_id, milk_id = [line["line_id"] for line in lines]
        updated = tool.execute(
            action="update",
            line_id=milk_id,
            quantity=3,
            note="ít đá",
        )
        removed = tool.execute(action="remove", line_id=salt_id)

    updated_cart = json.loads(updated.content)["cart"]
    assert updated_cart["lines"][1] == {
        **lines[1],
        "note": "ít đá",
        "quantity": 3,
        "line_total": 120_000,
    }
    removed_cart = json.loads(removed.content)["cart"]
    assert [line["line_id"] for line in removed_cart["lines"]] == [milk_id]
    assert removed_cart["total"] == 120_000
    assert len(recorder.events) == 3


def _three_line_cart(tool):
    added = tool.execute(
        action="add",
        items=[
            {
                "variant_id": "coconut",
                "name": "Nước dừa",
                "unit_price": 39_000,
                "quantity": 1,
            },
            {
                "variant_id": "orange",
                "name": "Cam tươi",
                "unit_price": 45_000,
                "quantity": 1,
            },
            {
                "variant_id": "matcha-ice",
                "name": "Matcha Đá Xay",
                "unit_price": 55_000,
                "quantity": 1,
            },
        ],
    )
    tool.execute(action="set_order_type", order_type="take-out")
    return added.metadata["cart_revision"], [
        line["line_id"] for line in json.loads(added.content)["cart"]["lines"]
    ]


def test_display_cart_advertises_batch_update_and_remove():
    params = DisplayCartTool().spec.parameters["properties"]

    assert params["line_ids"] == {"type": "array", "items": {"type": "string"}}
    update = params["updates"]["items"]
    assert update["required"] == ["line_id"]
    assert set(update["properties"]) == {"line_id", "quantity", "note"}


def test_display_cart_batch_update_changes_every_line_in_one_publish():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-batch-update"):
        revision, ids = _three_line_cart(tool)
        published = len(recorder.events)
        result = tool.execute(
            action="update",
            updates=[
                {"line_id": ids[0], "quantity": 100},
                {"line_id": ids[1], "quantity": 100, "note": "ít đá"},
                {"line_id": ids[2], "quantity": 100},
            ],
        )

    assert result.success
    cart = json.loads(result.content)["cart"]
    assert [line["line_id"] for line in cart["lines"]] == ids
    assert [line["quantity"] for line in cart["lines"]] == [100, 100, 100]
    assert cart["lines"][1]["note"] == "ít đá"
    assert cart["total"] == (39_000 + 45_000 + 55_000) * 100
    assert cart["order_type"] == "take-out"
    assert result.metadata["cart_revision"] > revision
    assert len(recorder.events) == published + 1
    assert recorder.events[-1].data["lines"] == [
        {key: line[key] for key in line if key != "variant_id"}
        for line in cart["lines"]
    ]


def test_display_cart_batch_remove_deletes_every_targeted_line_in_one_publish():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-batch-remove"):
        _, ids = _three_line_cart(tool)
        published = len(recorder.events)
        result = tool.execute(action="remove", line_ids=[ids[0], ids[2]])

    assert result.success
    cart = json.loads(result.content)["cart"]
    assert [line["line_id"] for line in cart["lines"]] == [ids[1]]
    assert cart["total"] == 45_000
    assert cart["order_type"] == "take-out"
    assert len(recorder.events) == published + 1


@pytest.mark.parametrize(
    ("params", "content"),
    [
        ({"action": "remove", "line_ids": ["LIVE", "missing"]}, "cart_line_not_found"),
        ({"action": "remove", "line_ids": []}, "invalid_cart_line"),
        ({"action": "remove", "line_ids": ["LIVE", "LIVE"]}, "invalid_cart_line"),
        (
            {
                "action": "update",
                "updates": [
                    {"line_id": "LIVE", "quantity": 100},
                    {"line_id": "missing", "quantity": 100},
                ],
            },
            "cart_line_not_found",
        ),
        (
            {
                "action": "update",
                "updates": [
                    {"line_id": "LIVE", "quantity": 100},
                    {"line_id": "LIVE2", "quantity": 0},
                ],
            },
            "invalid_cart_quantity",
        ),
        (
            {"action": "update", "updates": [{"line_id": "LIVE"}]},
            "cart_update_required",
        ),
    ],
)
def test_display_cart_rejects_a_bad_batch_edit_without_mutating(params, content):
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-bad-batch-edit"):
        revision, ids = _three_line_cart(tool)
        before = tool.current_snapshot()
        published = len(recorder.events)
        swap = {"LIVE": ids[0], "LIVE2": ids[1]}
        params = json.loads(
            json.dumps(params).replace('"LIVE2"', f'"{swap["LIVE2"]}"').replace(
                '"LIVE"', f'"{swap["LIVE"]}"'
            )
        )
        result = tool.execute(**params)
        after = tool.current_snapshot()

    assert not result.success
    assert result.content == content
    assert after == before
    assert len(recorder.events) == published


def test_display_cart_persists_order_note_and_order_type_in_the_revisioned_draft():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-metadata"):
        added = tool.execute(
            action="add",
            item={
                "variant_id": "milk-coffee",
                "name": "Cà phê sữa",
                "unit_price": 40_000,
                "quantity": 1,
            },
        )
        noted = tool.execute(action="set_order_note", order_note="Làm nhanh giúp mình")
        typed = tool.execute(action="set_order_type", order_type="take-out")
        viewed = tool.execute(action="view")

    assert noted.metadata["cart_revision"] > added.metadata["cart_revision"]
    assert typed.metadata["cart_revision"] > noted.metadata["cart_revision"]
    assert viewed.metadata["cart_revision"] == typed.metadata["cart_revision"]
    cart = json.loads(viewed.content)["cart"]
    assert cart["order_note"] == "Làm nhanh giúp mình"
    assert cart["order_type"] == "take-out"
    assert recorder.events[-1].data["order_note"] == "Làm nhanh giúp mình"
    assert recorder.events[-1].data["order_type"] == "take-out"


def test_display_cart_persists_an_at_table_selection_and_take_out_clears_it():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-table"):
        tool.execute(
            action="add",
            item={
                "variant_id": "milk-coffee",
                "name": "Cà phê sữa",
                "unit_price": 40_000,
                "quantity": 1,
            },
        )
        selected = tool.execute(
            action="set_table",
            table="table-73",
            table_name="73",
        )
        selected_snapshot = tool.current_snapshot()
        take_out = tool.execute(action="set_order_type", order_type="take-out")
        take_out_snapshot = tool.current_snapshot()

    assert selected.success
    assert selected_snapshot is not None
    assert selected_snapshot["order_type"] == "at-table"
    assert selected_snapshot["table"] == "table-73"
    assert selected_snapshot["table_name"] == "73"
    assert take_out.success
    assert take_out_snapshot is not None
    assert take_out_snapshot["order_type"] == "take-out"
    assert take_out_snapshot["table"] == ""
    assert take_out_snapshot["table_name"] == ""
    assert take_out.metadata["cart_revision"] > selected.metadata["cart_revision"]
    assert recorder.events[-1].data["table"] == ""
    assert recorder.events[-1].data["table_name"] == ""


def test_display_cart_adds_and_accumulates_a_conversation_draft():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-add"):
        first = tool.execute(
            action="add",
            item={
                "variant_id": "pizza-standard",
                "name": "Pizza Truyền Thống Ý",
                "size": "tiêu chuẩn",
                "unit_price": 107000,
                "quantity": 2,
                "note": "",
            },
        )
        second = tool.execute(
            action="add",
            item={
                "variant_id": "pizza-standard",
                "name": "Pizza Truyền Thống Ý",
                "size": "tiêu chuẩn",
                "unit_price": 107000,
                "quantity": 1,
                "note": "",
            },
        )

    assert first.success
    assert second.success
    cart = json.loads(second.content)["cart"]
    line_id = cart["lines"][0]["line_id"]
    assert cart == {
        "lines": [
            {
                "line_id": line_id,
                "variant_id": "pizza-standard",
                "name": "Pizza Truyền Thống Ý",
                "size": "tiêu chuẩn",
                "note": "",
                "quantity": 3,
                "unit_price": 107000,
                "line_total": 321000,
            }
        ],
        "total": 321000,
        "order_note": "",
        "order_type": "",
        "table": "",
        "table_name": "",
    }
    assert recorder.events[-1].data == {
        "view": "cart",
        "lines": [
            {
                "line_id": line_id,
                "name": "Pizza Truyền Thống Ý",
                "size": "tiêu chuẩn",
                "note": "",
                "quantity": 3,
                "unit_price": 107000,
                "line_total": 321000,
            }
        ],
        "total": 321000,
        "order_note": "",
        "order_type": "",
        "table": "",
        "table_name": "",
    }


def test_display_cart_draft_is_isolated_by_conversation():
    tool, recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-owner"):
        tool.execute(
            action="add",
            item={
                "variant_id": "latte-standard",
                "name": "Latte",
                "unit_price": 51000,
                "quantity": 1,
            },
        )
    with conversation_scope("next-customer"):
        result = tool.execute(action="view")

    assert result.success
    assert json.loads(result.content)["cart"] == {
        "lines": [],
        "total": 0,
        "order_note": "",
        "order_type": "",
        "table": "",
        "table_name": "",
    }
    assert recorder.events[-1].data == {
        "view": "cart",
        "lines": [],
        "total": 0,
        "order_note": "",
        "order_type": "",
        "table": "",
        "table_name": "",
    }


def test_display_cart_view_requires_the_agent_to_continue_with_fresh_state():
    tool, _recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-checkout"):
        result = tool.execute(action="view")

    assert result.success
    assert result.metadata["continue_agent"] is True


def test_checkout_claim_rejects_stale_revision_replay_and_concurrent_edit():
    import pytest

    from openjarvis.core.conversation import agent_turn_scope

    tool, _ = _wired(DisplayCartTool)
    item = {"variant_id": "coffee", "name": "Coffee", "unit_price": 100, "quantity": 1}
    with conversation_scope("claim"):
        tool.execute(action="add", item=item)
        with agent_turn_scope() as nonce:
            with pytest.raises(ValueError, match="revision"):
                tool.begin_checkout(nonce, 0)
            snapshot = tool.begin_checkout(nonce, 1)
            assert snapshot["total"] == 100
            assert tool.checkout_write_allowed()
            assert not tool.execute(action="add", item=item).success
            tool.end_checkout()
            assert not tool.checkout_write_allowed()
        with agent_turn_scope() as nonce:
            with pytest.raises(ValueError, match="consumed"):
                tool.begin_checkout(nonce, 1)
        tool.settle_current()
        result = tool.execute(action="add", item=item)
        assert result.metadata["cart_revision"] > 1


def test_checkout_rejects_invalid_replacement_without_changing_the_draft():
    import pytest

    from openjarvis.core.conversation import agent_turn_scope

    tool, _ = _wired(DisplayCartTool)
    original = {
        "variant_id": "coffee",
        "name": "Coffee",
        "unit_price": 100,
        "quantity": 1,
    }
    with conversation_scope("invalid-replacement"):
        tool.execute(action="add", item=original)
        before = tool.current_snapshot()
        with agent_turn_scope() as nonce:
            with pytest.raises(ValueError, match="invalid item"):
                tool.begin_checkout(
                    nonce,
                    None,
                    replacement_lines=[{"variant_id": "fries", "quantity": 3}],
                )
        assert tool.current_snapshot() == before


def test_checkout_requires_table_identity_to_match_the_order_type():
    import pytest

    from openjarvis.core.conversation import agent_turn_scope

    tool, _ = _wired(DisplayCartTool)
    lines = [
        {
            "variant_id": "coffee",
            "name": "Coffee",
            "unit_price": 100,
            "quantity": 1,
        }
    ]

    with conversation_scope("at-table-without-table"):
        with agent_turn_scope() as nonce:
            with pytest.raises(ValueError, match="requires a table"):
                tool.begin_checkout(
                    nonce,
                    None,
                    replacement_lines=lines,
                    order_type="at-table",
                    table="",
                )

    with conversation_scope("take-out-with-table"):
        with agent_turn_scope() as nonce:
            with pytest.raises(ValueError, match="cannot use a table"):
                tool.begin_checkout(
                    nonce,
                    None,
                    replacement_lines=lines,
                    order_type="take-out",
                    table="table-73",
                )


def test_checkout_replacement_requires_a_conversation_scope():
    import pytest

    tool, _ = _wired(DisplayCartTool)

    with pytest.raises(ValueError, match="conversation scope"):
        tool.begin_checkout(
            "turn",
            None,
            replacement_lines=[
                {
                    "variant_id": "fries",
                    "name": "French fries",
                    "unit_price": 100,
                    "quantity": 1,
                }
            ],
        )


def test_display_cart_revision_changes_only_when_the_draft_changes():
    tool, _recorder = _wired(DisplayCartTool)

    with conversation_scope("cart-revision"):
        first = tool.execute(
            action="add",
            item={
                "variant_id": "latte-standard",
                "name": "Latte",
                "unit_price": 51_000,
                "quantity": 1,
            },
        )
        viewed = tool.execute(action="view")
        second = tool.execute(
            action="add",
            item={
                "variant_id": "americano-standard",
                "name": "Americano",
                "unit_price": 45_000,
                "quantity": 1,
            },
        )
        snapshot = tool.current_snapshot()

    assert first.metadata["cart_revision"] == 1
    assert viewed.metadata["cart_revision"] == 1
    assert second.metadata["cart_revision"] == 2
    assert snapshot is not None
    line_ids = [line["line_id"] for line in snapshot["lines"]]
    assert snapshot == {
        "revision": 2,
        "lines": [
            {
                "line_id": line_ids[0],
                "variant_id": "latte-standard",
                "name": "Latte",
                "size": "",
                "note": "",
                "quantity": 1,
                "unit_price": 51_000,
                "line_total": 51_000,
            },
            {
                "line_id": line_ids[1],
                "variant_id": "americano-standard",
                "name": "Americano",
                "size": "",
                "note": "",
                "quantity": 1,
                "unit_price": 45_000,
                "line_total": 45_000,
            },
        ],
        "total": 96_000,
        "order_note": "",
        "order_type": "",
        "table": "",
        "table_name": "",
    }


def test_display_bill_keeps_only_merchant_bill_fields_and_normalizes_total():
    tool, recorder = _wired(DisplayBillTool)

    result = tool.execute(
        order_id="order-1",
        status="placed",
        order_type="take-out",
        branch="br-thu-duc",
        lines=[
            {
                "name": "Cà phê đen",
                "size": "tiêu chuẩn",
                "note": "ít đường",
                "quantity": 2,
                "line_total": 70_000,
                "html": "<script>x</script>",
            }
        ],
        total="70000",
        receipt_id="invented-receipt",
    )

    assert result.success is True
    assert recorder.events[0].data == {
        "view": "bill",
        "order_id": "order-1",
        "status": "placed",
        "order_type": "take-out",
        "branch": "br-thu-duc",
        "lines": [
            {
                "name": "Cà phê đen",
                "size": "tiêu chuẩn",
                "note": "ít đường",
                "quantity": 2,
                "line_total": 70_000,
            }
        ],
        "total": 70_000,
    }


def test_display_payment_qr_publishes_a_normalized_receipt_snapshot():
    tool, recorder = _wired(DisplayPaymentQrTool)
    tool._payment_trusted_origins = (("https", "merchant.example", 443),)

    evidence.reset()
    try:
        with conversation_scope("test-display-payment-qr-drops-fields"):
            evidence.record(
                "http_request",
                "merchant-opaque-qr",
                200,
                "https://merchant.example/pay",
            )
            result = tool.execute(
                order_id="order-1",
                payment_slug="payment-1",
                status="pending",
                qr_code="merchant-opaque-qr",
                order_type="at-table",
                branch="br-thu-duc",
                table_name="73",
                lines=[
                    {
                        "name": "Cà phê đen",
                        "size": "tiêu chuẩn",
                        "quantity": 2,
                        "unit_price": 35_000,
                        "line_total": 70_000,
                        "html": "<script>x</script>",
                    }
                ],
                total=70_000,
                html="<img src=x onerror=alert(1)>",
                receipt_id="receipt-that-must-not-be-shown",
            )
    finally:
        evidence.reset()

    assert result.success is True
    assert recorder.events[0].data == {
        "view": "payment_qr",
        "order_id": "order-1",
        "payment_slug": "payment-1",
        "status": "pending",
        "qr_code": "merchant-opaque-qr",
        "order_type": "at-table",
        "branch": "br-thu-duc",
        "table_name": "73",
        "lines": [
            {
                "name": "Cà phê đen",
                "size": "tiêu chuẩn",
                "quantity": 2,
                "unit_price": 35_000,
                "line_total": 70_000,
            }
        ],
        "total": 70_000,
    }


def test_display_payment_qr_rejects_an_arbitrary_nonempty_value_without_publishing():
    tool, recorder = _wired(DisplayPaymentQrTool)
    tool._payment_trusted_origins = (("https", "merchant.example", 443),)

    evidence.reset()
    try:
        with conversation_scope("test-display-payment-qr-rejects-invented"):
            result = tool.execute(
                order_id="order-1",
                payment_slug="payment-invented",
                status="pending",
                qr_code="agent-invented-qr",
            )
    finally:
        evidence.reset()

    assert result == ToolResult(
        tool_name="display_payment_qr",
        content="payment_evidence_missing",
        success=False,
    )
    assert recorder.events == []


def test_display_payment_qr_rejects_a_missing_payment_identifier():
    """Evidence alone must not be enough -- the payload must be complete too.

    Records matching evidence so the ``observed_in_tool_output`` term is
    satisfied, then omits ``payment_slug`` so completeness is the only thing
    that can still cause the refusal.
    """
    tool, recorder = _wired(DisplayPaymentQrTool)
    tool._payment_trusted_origins = (("https", "merchant.example", 443),)

    evidence.reset()
    try:
        with conversation_scope("test-display-payment-qr-rejects-incomplete"):
            evidence.record(
                "http_request",
                "merchant-opaque-qr",
                200,
                "https://merchant.example/pay",
            )
            result = tool.execute(
                order_id="order-1",
                status="pending",
                qr_code="merchant-opaque-qr",
            )
    finally:
        evidence.reset()

    assert result == ToolResult(
        tool_name="display_payment_qr",
        content="payment_evidence_missing",
        success=False,
    )
    assert recorder.events == []


def test_display_payment_qr_rejects_an_empty_qr_without_publishing():
    tool, recorder = _wired(DisplayPaymentQrTool)

    result = tool.execute(
        order_id="order-1",
        payment_slug="payment-1",
        status="pending",
        qr_code="  ",
    )

    assert result == ToolResult(
        tool_name="display_payment_qr",
        content="qr_code_required",
        success=False,
    )
    assert recorder.events == []


def test_display_clear_publishes_an_empty_view():
    tool, recorder = _wired(DisplayClearTool)
    tool.execute()
    assert recorder.events[0].data == {"view": "none"}


def test_a_display_tool_without_a_bus_fails_rather_than_silently_doing_nothing():
    result = DisplayMenuTool().execute(items=[{"id": "latte", "name": "Latte"}])
    assert result.success is False
    assert "display_unavailable" in result.content


def test_display_menu_remembers_the_latest_complete_menu_per_conversation():
    tool, _ = _wired(DisplayMenuTool)
    first = [{"id": "v-1", "name": "Taco gà", "price": 86000, "available": True}]
    second = [
        {"id": "v-2", "name": "Salad sân vườn", "price": 97000, "available": True}
    ]

    with conversation_scope("menu-owner"):
        assert tool.agent_context() == {}
        tool.execute(items=first, result_complete=True)
        tool.execute(items=second, result_complete=True)
        assert tool.agent_context() == {"displayed_menu": second}
    with conversation_scope("next-customer"):
        assert tool.agent_context() == {}


def test_display_menu_forgets_nothing_it_did_not_verifiably_publish():
    item = {"id": "v-1", "name": "Taco gà", "price": 86000, "available": True}
    unwired = DisplayMenuTool()
    partial, _ = _wired(DisplayMenuTool)

    with conversation_scope("menu-unverified"):
        assert unwired.execute(items=[item], result_complete=True).success is False
        partial.execute(items=[item])
        assert unwired.agent_context() == {}
        assert partial.agent_context() == {}


def test_display_menu_publishes_through_the_presentation_manager():
    presentation = _FakePresentationManager()
    tool = DisplayMenuTool()
    tool._presentation = presentation

    result = tool.execute(items=[{"id": "latte", "name": "Latte"}])

    assert result.success is True
    assert result.tool_name == "display_menu"
    assert presentation.payloads == [
        {"view": "menu", "items": [{"id": "latte", "name": "Latte"}]}
    ]


def test_legacy_display_menu_returns_customer_message_as_control_metadata():
    tool, _ = _wired(DisplayMenuTool)
    result = tool.execute(
        items=[{"id": "latte", "name": "Latte"}],
        customer_message="Menu đang hiển thị.",
    )
    assert result.metadata["customer_message"] == "Menu đang hiển thị."


@pytest.mark.parametrize("count", [0, 1, 6, 7, 100])
def test_complete_display_menu_publishes_every_projected_item(count):
    tool, recorder = _wired(DisplayMenuTool)
    items = [
        {"id": f"item-{index}", "name": f"Item {index}", "price": index}
        for index in range(count)
    ]

    result = tool.execute(
        items=items,
        result_complete=True,
        customer_message="model supplied text",
    )

    assert result.success
    assert len(recorder.events) == 1
    payload = recorder.events[0].data
    assert payload["items"] == items
    assert payload["result_complete"] is True
    assert payload["projected_count"] == count
    assert payload["published_count"] == count
    assert result.metadata["projected_count"] == count
    assert result.metadata["published_count"] == count
    assert result.metadata["completed_display"] is True
    assert result.metadata["result_complete"] is True
    assert json.loads(result.content) == {
        "shown": "menu",
        "count": count,
        "complete": True,
    }
    assert result.metadata["customer_message"] != "model supplied text"


def test_complete_display_menu_rejects_any_unrenderable_row_before_publication():
    tool, recorder = _wired(DisplayMenuTool)

    result = tool.execute(
        items=[{"id": "valid", "name": "Valid"}, {"unknown": "invalid"}],
        result_complete=True,
    )

    assert not result.success
    assert result.content == "menu_projection_invalid"
    assert result.metadata == {}
    assert recorder.events == []


def test_complete_empty_menu_is_verified_and_published():
    tool, recorder = _wired(DisplayMenuTool)

    result = tool.execute(items=[], result_complete=True)

    assert result.success
    assert recorder.events[0].data["items"] == []
    assert result.metadata["completed_display"] is True
    message = result.metadata["customer_message"].lower()
    assert "0" in message
    assert "đang tìm" not in message
    assert "kiểm tra" not in message


@pytest.mark.parametrize("count", [1, 6, 10])
def test_complete_small_menu_message_names_every_item_and_price(count):
    tool, _ = _wired(DisplayMenuTool)
    items = [
        {"id": f"id-{index}", "name": f"Món {index}", "price": 10_000 + index}
        for index in range(count)
    ]

    message = tool.execute(items=items, result_complete=True).metadata[
        "customer_message"
    ]

    for item in items:
        assert item["name"] in message
        assert str(item["price"]) in message


def test_complete_large_menu_message_is_bounded_and_reports_exact_count():
    tool, _ = _wired(DisplayMenuTool)
    items = [
        {"id": f"id-{index}", "name": f"Món {index}", "price": index}
        for index in range(11)
    ]

    message = tool.execute(items=items, result_complete=True).metadata[
        "customer_message"
    ]

    assert "11" in message
    assert "Món 9" in message
    assert "Món 10" not in message
    assert "Toàn bộ" in message


def test_failed_complete_publication_releases_no_terminal_metadata():
    class FailingPresentation:
        def publish(self, payload):
            return ToolResult(
                tool_name="presentation",
                content="presentation_unavailable",
                success=False,
            )

    tool = DisplayMenuTool()
    tool._presentation = FailingPresentation()

    result = tool.execute(
        items=[{"id": "latte", "name": "Latte"}], result_complete=True
    )

    assert not result.success
    assert "customer_message" not in result.metadata
    assert "completed_display" not in result.metadata


def test_display_menu_with_a_manager_fails_before_a_session_is_active():
    client = type("PlaywrightClient", (), {"_server_name": "playwright"})()
    tool = DisplayMenuTool()
    tool._presentation = PresentationSessionManager(EventBus(), client)

    result = tool.execute(items=[{"id": "latte", "name": "Latte"}])

    assert result.success is False
    assert "presentation_unavailable" in result.content


def test_display_menu_rejects_an_empty_item_list_without_publishing():
    # A model with nothing real to show (no fresh read, nothing usable left
    # in context) must not get a false "success" it can narrate as if the
    # menu were actually on screen.
    tool, recorder = _wired(DisplayMenuTool)

    result = tool.execute(items=[])

    assert result == ToolResult(
        tool_name="display_menu",
        content="items_required",
        success=False,
    )
    assert recorder.events == []


def test_display_menu_schema_allows_verified_empty_and_declares_completion_flag():
    properties = DisplayMenuTool().spec.parameters["properties"]

    assert "minItems" not in properties["items"]
    assert properties["result_complete"] == {"type": "boolean"}


def test_display_menu_schema_offers_latest_http_evidence_for_complete_browsing():
    spec = DisplayMenuTool().spec.parameters

    assert spec["properties"]["all_from_latest_http"]["type"] == "boolean"
    assert spec["required"] == []


def test_display_menu_can_publish_every_product_from_latest_http_evidence():
    tool, recorder = _wired(DisplayMenuTool)
    payload = {
        "result": {
            "items": [
                {
                    "menuItems": [
                        {
                            "product": {
                                "slug": "product-a",
                                "name": "Taco gà",
                                "isActive": True,
                                "variants": [
                                    {"slug": "variant-a", "price": 86_000}
                                ],
                            }
                        },
                        {
                            "product": {
                                "slug": "product-b",
                                "name": "Burger gà",
                                "isActive": False,
                                "variants": [
                                    {"slug": "variant-b", "price": 129_000}
                                ],
                            }
                        },
                    ]
                }
            ]
        }
    }

    evidence.reset()
    try:
        with conversation_scope("test-display-complete-menu-evidence"):
            evidence.record(
                "http_request",
                json.dumps(payload),
                200,
                "https://merchant.example/menu/specific/public",
            )
            result = tool.execute(all_from_latest_http=True)
    finally:
        evidence.reset()

    assert result.success is True
    assert recorder.events[0].data == {
        "view": "menu",
        "items": [
            {
                "id": "variant-a",
                "name": "Taco gà",
                "price": 86_000,
                "available": True,
            },
            {
                "id": "variant-b",
                "name": "Burger gà",
                "price": 129_000,
                "available": False,
            },
        ],
    }


def test_display_menu_keeps_explicit_filtered_items_over_full_http_evidence():
    tool, recorder = _wired(DisplayMenuTool)

    evidence.reset()
    try:
        with conversation_scope("test-display-filter-wins"):
            evidence.record(
                "http_request",
                json.dumps(
                    {
                        "result": {
                            "items": [
                                {
                                    "menuItems": [
                                        {
                                            "product": {
                                                "name": "Taco gà",
                                                "variants": [
                                                    {
                                                        "slug": "variant-a",
                                                        "price": 86_000,
                                                    }
                                                ],
                                            }
                                        },
                                        {
                                            "product": {
                                                "name": "Mì Ý tôm",
                                                "variants": [
                                                    {
                                                        "slug": "variant-b",
                                                        "price": 172_000,
                                                    }
                                                ],
                                            }
                                        },
                                    ]
                                }
                            ]
                        }
                    }
                ),
                200,
                "https://merchant.example/menu/specific/public",
            )
            result = tool.execute(
                items=[{"id": "variant-a", "name": "Taco gà", "price": 86_000}],
                all_from_latest_http=True,
            )
    finally:
        evidence.reset()

    assert result.success is True
    assert recorder.events[0].data["items"] == [
        {"id": "variant-a", "name": "Taco gà", "price": 86_000}
    ]


def test_display_menu_rejects_latest_http_mode_without_menu_evidence():
    tool, recorder = _wired(DisplayMenuTool)

    evidence.reset()
    try:
        with conversation_scope("test-display-missing-menu-evidence"):
            result = tool.execute(all_from_latest_http=True)
    finally:
        evidence.reset()

    assert result == ToolResult(
        tool_name="display_menu",
        content="menu_evidence_missing",
        success=False,
    )
    assert recorder.events == []


def test_display_menu_rejects_items_that_carry_no_recognized_field():
    # Rows that survive field-picking down to nothing are the same failure
    # as an empty list -- there is still nothing displayable.
    tool, recorder = _wired(DisplayMenuTool)

    result = tool.execute(items=[{"onclick": "alert(1)"}, {}])

    assert result.success is False
    assert result.content == "items_required"
    assert recorder.events == []


def test_display_update_is_forwarded_to_websocket_clients():
    from openjarvis.server.ws_bridge import _AGENT_EVENTS

    assert EventType.DISPLAY_UPDATE in _AGENT_EVENTS
