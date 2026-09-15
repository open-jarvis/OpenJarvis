"""Measure fewer inference boundaries using only existing built-in tools.

HTTP is always a local fake, including the opt-in live-model measurement.
No order or payment is sent to a merchant.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.events import EventBus
from openjarvis.core.types import ToolResult
from openjarvis.skills.manager import SkillManager
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
from openjarvis.tools.display import DisplayPaymentQrTool
from openjarvis.tools.skill_manage import SkillManageTool
from tests.agents.fake_engine import FakeEngine


class FakeShop(BaseTool):
    def __init__(self, origin, identifier):
        self.origin = origin
        self.identifier = identifier
        self.calls = []
        self.fail_read = False
        self.wrong_quantity = False

    @property
    def spec(self):
        return ToolSpec(
            name="http_request",
            description="Call the selected website API.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["url"],
            },
        )

    def execute(self, **params):
        self.calls.append(params)
        assert params["url"].startswith(self.origin + "/")
        path = params["url"][len(self.origin) :]
        if path == "/tables":
            result = [{"name": "73", "slug": "table-73", "status": "available"}]
        elif path == "/orders" and params.get("method") == "POST":
            self.order = json.loads(params["body"])
            result = {self.identifier: "fresh-order"}
        elif path == "/orders/fresh-order":
            if self.fail_read:
                return ToolResult(
                    tool_name="http_request", content="Read failed", success=False
                )
            result = {**self.order, self.identifier: "fresh-order", "total": 300000}
            if self.wrong_quantity:
                result = {**result, "quantity": 99}
        elif path == "/payments":
            assert json.loads(params["body"])["order"] == "fresh-order"
            result = {
                "slug": "fresh-payment",
                "order": "fresh-order",
                "amount": 300000,
                "status": "pending",
                "qrCode": "fixture-qr",
            }
        else:
            raise AssertionError(f"Unexpected fake endpoint: {path}")
        return ToolResult(
            tool_name="http_request",
            content=json.dumps({"result": result}),
            success=True,
            metadata={"status_code": 200, "final_url": params["url"]},
        )


def setup_tools(tmp_path, origin, identifier):
    bus = EventBus()
    shop = FakeShop(origin, identifier)
    display = DisplayPaymentQrTool()
    display._bus = bus
    display._payment_trusted_origins = (("https", origin.split("//")[1], 443),)
    manager = SkillManager(bus, overlay_dir=tmp_path / "overlays")
    skill = SkillManageTool(skills_dir=tmp_path / "skills", skill_manager=manager)
    tools = [shop, display, skill]
    manager.set_tool_executor(ToolExecutor(tools, bus))
    result = skill.execute(
        action="create",
        name="shop-create-read",
        steps=[
            {
                "tool_name": "http_request",
                "output_key": "created",
                "arguments_template": json.dumps(
                    {
                        "url": origin + "/orders",
                        "method": "POST",
                        "body": "{order_body}",
                    }
                ),
            },
            {
                "tool_name": "http_request",
                "arguments_template": json.dumps(
                    {
                        "url": origin + "/orders/{created.result." + identifier + "}",
                        "method": "GET",
                    }
                ),
            },
        ],
    )
    assert result.success, result.content
    return tools, shop


def call(tool_name, **arguments):
    return {"id": "call", "name": tool_name, "arguments": json.dumps(arguments)}


def order_body():
    return json.dumps(
        {
            "variant": "salad-standard",
            "quantity": 2,
            "type": "at-table",
            "table": "table-73",
            "note": "",
        }
    )


@pytest.mark.parametrize(
    "origin,identifier",
    [
        ("https://shop-a.example", "slug"),
        ("https://shop-b.example", "id"),
    ],
)
def test_create_read_returns_fresh_order_in_one_inference_boundary(
    tmp_path,
    origin,
    identifier,
):
    tools, shop = setup_tools(tmp_path, origin, identifier)
    engine = FakeEngine(
        [
            {
                "tool_calls": [
                    call("http_request", url=origin + "/tables", method="GET")
                ]
            },
            {
                "tool_calls": [
                    call(
                        "skill_manage",
                        action="run",
                        name="shop-create-read",
                        context={"order_body": order_body()},
                    )
                ]
            },
            {
                "tool_calls": [
                    call(
                        "http_request",
                        url=origin + "/payments",
                        method="POST",
                        body=json.dumps({"order": "fresh-order"}),
                    )
                ]
            },
            {
                "tool_calls": [
                    call(
                        "display_payment_qr",
                        order_id="fresh-order",
                        payment_slug="fresh-payment",
                        status="pending",
                        total=300000,
                        customer_message=(
                            "Đơn 300.000đ đã được kiểm tra, QR đã hiển thị."
                        ),
                    )
                ],
            },
        ]
    )
    result = OrchestratorAgent(engine, "fake-model", tools=tools).run(
        "Đặt và thanh toán"
    )
    assert result.content
    assert engine.call_count == 4
    assert all(r.success for r in result.tool_results)
    assert [p.get("method") for p in shop.calls] == ["GET", "POST", "GET", "POST"]
    readback = json.loads(result.tool_results[1].content)["result"]
    assert readback[identifier] == "fresh-order"
    assert readback["quantity"] == 2
    assert readback["total"] == 300000


def test_failed_readback_is_returned_to_agent_without_payment(tmp_path):
    tools, shop = setup_tools(tmp_path, "https://shop-a.example", "slug")
    shop.fail_read = True
    result = tools[-1].execute(
        action="run", name="shop-create-read", context={"order_body": order_body()}
    )
    assert not result.success
    assert len(shop.calls) == 2
    assert result.content == "Read failed"


def test_changed_readback_stays_visible_at_the_agent_validation_boundary(tmp_path):
    tools, shop = setup_tools(tmp_path, "https://shop-b.example", "id")
    shop.wrong_quantity = True
    result = tools[-1].execute(
        action="run", name="shop-create-read", context={"order_body": order_body()}
    )
    # Successful HTTP is not semantic validation: the agent must see this
    # discrepancy and decide before any payment call can be made.
    assert result.success
    assert json.loads(result.content)["result"]["quantity"] == 99
    assert len(shop.calls) == 2


@pytest.mark.skipif(
    os.environ.get("OPENJARVIS_CHECKOUT_LIVE_MODEL") != "1",
    reason="Opt-in real model; HTTP and display remain local fakes",
)
def test_live_model_checkout_latency(tmp_path):
    from dotenv import load_dotenv

    from openjarvis.engine.cloud import CloudEngine

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OpenAI key unavailable")
    origin = "https://shop-b.example"
    tools, shop = setup_tools(tmp_path, origin, "id")
    prompt = (
        Path(__file__).resolve().parents[2]
        / "configs/openjarvis/prompts/ordering-kiosk.md"
    ).read_text()
    prompt += f"""
Current selected website is {origin}, not the default website. Verified contract:
GET {origin}/tables returns result array of name/slug/status. Table 73 must be checked.
POST {origin}/orders accepts variant, quantity, type, table, note, returns result.id.
GET {origin}/orders/{{id}} returns those fields plus total and id under result.
POST {origin}/payments accepts JSON {{"order":"<id>"}} and returns result with
slug, order, amount, status, qrCode. Use display_payment_qr after checking payment.
Known procedure shop-create-read is prepared for this website: it creates from
context.order_body (JSON string) and reads the fresh result.id, returning the order.
Previously observed menu: Salad, variant salad-standard, unit price 150000 VND.
The customer has now confirmed exactly 2 portions, at table 73, no notes, pay now.
No cart or bill is requested. All merchant tools are isolated fixtures.
"""
    engine = CloudEngine()
    agent = OrchestratorAgent(
        engine, "gpt-5.6-luna", tools=tools, system_prompt=prompt, max_turns=8
    )
    started = time.perf_counter()
    try:
        result = agent.run(
            "2 Salad tại bàn 73, không ghi chú, đặt và hiện QR thanh toán ngay"
        )
    except Exception as exc:
        pytest.fail(
            f"Live model unavailable: {type(exc).__name__}, "
            f"status={getattr(exc, 'status_code', None)}",
            pytrace=False,
        )
    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {
                "seconds": round(elapsed, 3),
                "turns": result.turns,
                "tools": [r.tool_name for r in result.tool_results],
                "http_calls": len(shop.calls),
                "usage": result.metadata,
            }
        )
    )
    assert result.content
    assert all(r.success for r in result.tool_results), result.content
    assert any(r.tool_name == "display_payment_qr" for r in result.tool_results)
    assert len(shop.calls) == 4
    assert result.turns <= 4
    assert elapsed < 15
