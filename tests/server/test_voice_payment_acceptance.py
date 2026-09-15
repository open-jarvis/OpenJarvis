"""Opt-in Luna acceptance through Voice -> native runtime -> real Agent.

Only the model is remote. Merchant mutations and settlement are local fixtures.
This does not stand in for microphone, WebRTC, playback or bank settlement.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import LLMTextFrame
from pipecat.processors.aggregators.llm_context import LLMContext

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.agents.runtime import NativeAgentRuntime
from openjarvis.core.conversation import conversation_scope
from openjarvis.core.types import ToolResult
from openjarvis.server.voice.llm import OpenJarvisLLMService, agent_input
from tests.agents.test_checkout_procedure import setup_tools


@pytest.mark.anyio
@pytest.mark.skipif(
    os.environ.get("OPENJARVIS_CHECKOUT_LIVE_MODEL") != "1",
    reason="Opt-in Luna API; merchant and settlement stay local",
)
async def test_luna_voice_checkout_then_pending_and_paid(tmp_path, monkeypatch):
    from dotenv import load_dotenv

    from openjarvis.engine.cloud import CloudEngine

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=True)
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.fail("Luna API key unavailable", pytrace=False)

    origin = "https://shop-b.example"
    tools, shop = setup_tools(tmp_path, origin, "id")
    execute = shop.execute
    payment_status = "pending"

    def merchant(**params):
        if params["url"] == origin + "/orders/fresh-order":
            shop.calls.append(params)
            return ToolResult(
                tool_name="http_request",
                content=json.dumps(
                    {
                        "result": {
                            **shop.order,
                            "id": "fresh-order",
                            "total": 300000,
                            "payment": {"status": payment_status},
                        }
                    }
                ),
                success=True,
                metadata={"status_code": 200, "final_url": params["url"]},
            )
        return execute(**params)

    monkeypatch.setattr(shop, "execute", merchant)
    prompt = (root / "configs/openjarvis/prompts/ordering-kiosk.md").read_text()
    prompt += f"""
The selected website is {origin}. These are verified fixture contracts:
GET /tables returns result array of name, slug, status. Check table 73.
POST /orders takes variant, quantity, type, table, note; returns result.id.
GET /orders/{{id}} returns the order, total and payment.status under result.
POST /payments takes {{"order":"<id>"}}; returns result.slug, order, amount,
status, qrCode. Show display_payment_qr after validating the response.
Known procedure shop-create-read creates with context.order_body (JSON string)
and reads the fresh result.id. Use it after current customer confirmation.
Verified menu: Salad, variant salad-standard, unit price 150000 VND.
All merchant tools are local fixtures. A payment status query needs a fresh
GET /orders/{{id}} using this conversation's order, never another order/payment.
"""
    engine = CloudEngine()
    requests = []
    create = engine._openai_client.responses.create

    def checked_create(**kwargs):
        assert kwargs["model"] == "gpt-5.6-luna"
        assert kwargs["reasoning"] == {"effort": "high"}
        requests.append((kwargs["model"], kwargs["reasoning"]["effort"]))
        return create(**kwargs)

    monkeypatch.setattr(engine._openai_client.responses, "create", checked_create)
    agent = OrchestratorAgent(
        engine, "gpt-5.6-luna", tools=tools, system_prompt=prompt, max_turns=8
    )
    binding = NativeAgentRuntime(agent).bind(model="gpt-5.6-luna")
    service = OpenJarvisLLMService(binding)
    context = LLMContext()
    timings = []

    async def speak(text):
        context.add_message({"role": "user", "content": text})
        query, history = agent_input(context)
        started = time.perf_counter()
        frames = [frame async for frame in service.stream_agent(query, history)]
        answer = "".join(f.text for f in frames if isinstance(f, LLMTextFrame))
        timings.append(round(time.perf_counter() - started, 3))
        assert answer.strip()
        context.add_message({"role": "assistant", "content": answer})
        return answer

    try:
        with conversation_scope(uuid.uuid4().hex):
            await speak(
                "2 Salad tại bàn 73, không ghi chú, xác nhận đặt và hiện QR ngay"
            )
            writes = [p for p in shop.calls if p.get("method") == "POST"]
            assert [p["url"] for p in writes] == [
                origin + "/orders",
                origin + "/payments",
            ]
            assert any(p["url"].endswith("/orders/fresh-order") for p in shop.calls)
            for status in ("pending", "paid"):
                payment_status = status
                before = len(shop.calls)
                answer = await speak(
                    "Kiểm tra thanh toán đơn vừa rồi, đọc cả mã trạng thái API giúp tôi"
                )
                fresh = shop.calls[before:]
                assert len(fresh) == 1
                assert fresh[0]["url"] == origin + "/orders/fresh-order"
                assert fresh[0].get("method", "GET") == "GET"
                assert status in answer.lower()
            assert len([p for p in shop.calls if p.get("method") == "POST"]) == 2
            assert requests
            print(
                json.dumps(
                    {
                        "model": "gpt-5.6-luna",
                        "effort": "high",
                        "seconds_per_turn": timings,
                        "model_calls": len(requests),
                        "merchant_writes": 2,
                        "status_reads": 2,
                    }
                )
            )
    finally:
        engine.close()
