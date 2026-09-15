"""A QR reaches the customer's screen only if a trusted call returned it."""

from __future__ import annotations

import json
from typing import Any

import pytest

from openjarvis.core.conversation import conversation_scope
from openjarvis.core.events import EventBus
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tools import evidence
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
from openjarvis.tools.display import DisplayCartTool, DisplayPaymentQrTool

_PAYMENT = {
    "order_id": "ORD-1",
    "payment_slug": "PAY-1",
    "status": "pending",
    "qr_code": "QR_REAL_789",
}


@pytest.fixture(autouse=True)
def _clean_store():
    evidence.reset()
    yield
    evidence.reset()


class _Http(BaseTool):
    tool_id = "http"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="http_request",
            description="test double",
            parameters={"type": "object", "properties": {}},
        )

    def execute(self, **params: Any) -> ToolResult:
        return ToolResult(
            tool_name="http_request",
            content=params.get("body", ""),
            success=True,
            metadata={"status_code": params.get("status", 200)},
        )


def _display_tool() -> DisplayPaymentQrTool:
    tool = DisplayPaymentQrTool()
    tool._bus = EventBus()
    tool._payment_trusted_origins = (("https", "trendcoffee.net", 443),)
    return tool


def _observe(executor: ToolExecutor, body: str, status: int, url: str) -> None:
    executor.execute(
        ToolCall(
            id="1",
            name="http_request",
            arguments=json.dumps({"body": body, "status": status, "url": url}),
        )
    )


def test_a_qr_a_trusted_call_returned_is_published():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(
            executor,
            '{"qrCode": "QR_REAL_789"}',
            201,
            "https://trendcoffee.net/api/latest/payment/initiate/public",
        )
        result = tool.execute(**_PAYMENT)

    assert result.success is True


@pytest.mark.parametrize("display_available", [True, False])
def test_customer_message_is_released_only_after_display_succeeds(display_available):
    tool = _display_tool()
    if not display_available:
        tool._bus = None
    with conversation_scope("customer-message"):
        _observe(
            ToolExecutor([_Http()]), '{"qrCode": "QR_REAL_789"}', 201,
            "https://trendcoffee.net/api/latest/payment/initiate/public",
        )
        result = tool.execute(**_PAYMENT, customer_message="QR đã hiển thị.")
    assert result.success is display_available
    assert result.metadata.get("customer_message") == (
        "QR đã hiển thị." if display_available else None
    )


@pytest.mark.parametrize("display_available", [True, False])
def test_verified_payment_settles_the_current_conversation_cart(display_available):
    cart = DisplayCartTool()
    cart._bus = EventBus()
    payment = _display_tool()
    if not display_available:
        payment._bus = None
    payment._cart_settler = getattr(cart, "settle_current", lambda: None)

    with conversation_scope("settled-cart"):
        added = cart.execute(
            action="add",
            item={
                "variant_id": "latte",
                "name": "Cà phê sữa",
                "size": "tiêu chuẩn",
                "unit_price": 40_000,
                "quantity": 2,
                "note": "",
            },
        )
        _observe(
            ToolExecutor([_Http()]),
            '{"qrCode": "QR_REAL_789"}',
            201,
            "https://trendcoffee.net/api/latest/payment/initiate/public",
        )
        payment.execute(**_PAYMENT, customer_message="QR đã sẵn sàng.")
        viewed = cart.execute(action="view")

    assert added.success
    assert json.loads(viewed.content)["cart"] == {
        "lines": [],
        "total": 0,
        "order_note": "",
        "order_type": "",
        "table": "",
        "table_name": "",
    }


def test_a_trusted_payment_response_can_supply_qr_without_copying_it_through_llm():
    """Large base64 QR values stay in evidence instead of tool-call arguments."""
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(
            executor,
            '{"result":{"qrCode":"QR_REAL_789"}}',
            200,
            "https://trendcoffee.net/api/latest/payment/initiate/public",
        )
        result = tool.execute(
            order_id="ORD-1",
            payment_slug="PAY-1",
            status="pending",
        )

    assert result.success is True


def test_qr_code_is_optional_in_the_agent_tool_schema():
    required = DisplayPaymentQrTool().spec.parameters["required"]

    assert required == ["order_id", "payment_slug", "status", "customer_message"]


def test_a_qr_fetched_by_a_different_executor_is_still_accepted():
    """A saved skill runs its steps on its own executor.

    With an instance-owned buffer the guard would refuse a genuine QR here,
    and the refusal would look like the agent failing to observe anything.
    """
    skill_executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(
            skill_executor,
            '{"qrCode": "QR_REAL_789"}',
            201,
            "https://trendcoffee.net/x",
        )
        result = tool.execute(**_PAYMENT)

    assert result.success is True


def test_a_qr_no_tool_ever_returned_is_refused():
    tool = _display_tool()

    with conversation_scope("a"):
        result = tool.execute(**_PAYMENT)

    assert result.success is False
    assert result.content == "payment_evidence_missing"


def test_a_qr_from_an_untrusted_host_is_refused():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(executor, '{"qrCode": "QR_REAL_789"}', 200, "https://evil.example/x")
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_a_qr_from_http_on_the_trusted_host_is_refused():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(executor, '{"qrCode": "QR_REAL_789"}', 200, "http://trendcoffee.net/x")
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_a_qr_from_the_wrong_https_port_is_refused():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(
            executor,
            '{"qrCode": "QR_REAL_789"}',
            200,
            "https://trendcoffee.net:444/x",
        )
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_http_origin_is_accepted_only_when_explicitly_configured():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()
    tool._payment_trusted_origins = (("http", "trendcoffee.net", 80),)

    with conversation_scope("a"):
        _observe(executor, '{"qrCode": "QR_REAL_789"}', 200, "http://trendcoffee.net/x")
        result = tool.execute(**_PAYMENT)

    assert result.success is True


def test_a_qr_from_a_non_2xx_response_is_refused():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("a"):
        _observe(
            executor, '{"qrCode": "QR_REAL_789"}', 500, "https://trendcoffee.net/x"
        )
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_a_qr_that_only_a_browser_tool_saw_is_refused():
    """The injection case the tool-name scoping exists for."""

    class _Browser(_Http):
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name="browser_snapshot",
                description="test double",
                parameters={"type": "object", "properties": {}},
            )

    executor = ToolExecutor([_Browser()])
    tool = _display_tool()

    with conversation_scope("a"):
        executor.execute(
            ToolCall(
                id="1",
                name="browser_snapshot",
                arguments=json.dumps(
                    {
                        "body": "page says QR_REAL_789",
                        "status": 200,
                        "url": "https://trendcoffee.net/x",
                    }
                ),
            )
        )
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_another_conversations_qr_is_refused():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()

    with conversation_scope("customer-a"):
        _observe(
            executor, '{"qrCode": "QR_REAL_789"}', 201, "https://trendcoffee.net/x"
        )
    with conversation_scope("customer-b"):
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_no_trusted_origins_configured_refuses_everything():
    executor = ToolExecutor([_Http()])
    tool = _display_tool()
    tool._payment_trusted_origins = ()

    with conversation_scope("a"):
        _observe(
            executor, '{"qrCode": "QR_REAL_789"}', 201, "https://trendcoffee.net/x"
        )
        result = tool.execute(**_PAYMENT)

    assert result.success is False


def test_payment_qr_includes_total_when_provided_or_extracted():
    from openjarvis.core.events import EventType

    executor = ToolExecutor([_Http()])
    tool = _display_tool()
    published = []
    tool._bus.subscribe(
        EventType.DISPLAY_UPDATE, lambda event: published.append(event.data)
    )

    with conversation_scope("a"):
        _observe(
            executor,
            '{"result":{"qrCode":"QR_REAL_789","amount":40000}}',
            201,
            "https://trendcoffee.net/api/latest/payment/initiate/public",
        )
        result = tool.execute(
            order_id="ORD-1",
            payment_slug="PAY-1",
            status="pending",
        )

    assert result.success is True
    assert len(published) == 1
    assert published[0]["total"] == 40000
