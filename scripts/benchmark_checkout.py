"""Opt-in real merchant benchmark; prints timings, never response bodies or QR data.

This exercises the current Python runtime and display event, not microphone/STT
or the browser paint. Each invocation can create one real order and payment.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.conversation import conversation_scope
from openjarvis.core.events import EventBus, EventType
from openjarvis.engine.cloud import CloudEngine
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.loader import load_skill
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.system.builder import SystemBuilder
from openjarvis.tools._stubs import ToolExecutor
from openjarvis.tools.display import (
    DisplayCartTool,
    DisplayMenuTool,
    DisplayPaymentQrTool,
)
from openjarvis.tools.http_request import HttpRequestTool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cart-json", default="[]")
    parser.add_argument("--trusted-origin", required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--customer-request", required=True)
    parser.add_argument("--authorize-live-writes", action="store_true")
    args = parser.parse_args()
    manifest = load_skill(args.manifest)
    if manifest.checkout and not args.authorize_live_writes:
        parser.error("Real writes require --authorize-live-writes")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    bus = EventBus()
    cart, http, qr = DisplayCartTool(), HttpRequestTool(), DisplayPaymentQrTool()
    cart._bus = qr._bus = bus
    menu = DisplayMenuTool()
    menu._bus = bus
    qr._payment_trusted_origins = SystemBuilder._parse_trusted_origins(
        args.trusted_origin
    )
    internal = [cart, http, qr, menu]
    skill = SkillTool(manifest, SkillExecutor(ToolExecutor(internal, bus), bus=bus))
    SystemBuilder._inject_checkout_guard([*internal, skill])
    SystemBuilder._inject_draft_cart_settler(internal)
    calls, displays = [], []
    bus.subscribe(
        EventType.TOOL_CALL_END,
        lambda event: calls.append(
            {
                "tool": event.data["tool"],
                "success": event.data["success"],
                "seconds": round(event.data["latency"], 3),
            }
        ),
    )
    bus.subscribe(
        EventType.DISPLAY_UPDATE, lambda event: displays.append(time.perf_counter())
    )
    agent = OrchestratorAgent(
        CloudEngine(),
        "gpt-5.6-luna",
        tools=[skill],
        bus=bus,
        system_prompt=args.prompt.read_text(),
        max_turns=1,
    )
    with conversation_scope("checkout-benchmark-" + uuid4().hex):
        for item in json.loads(args.cart_json):
            if not cart.execute(action="add", item=item).success:
                raise ValueError("Invalid benchmark cart")
        displays.clear()
        started = time.perf_counter()
        result = agent.run(args.customer_request)
        print(
            json.dumps(
                {
                    "seconds": round(time.perf_counter() - started, 3),
                    "display_event_seconds": round(displays[-1] - started, 3)
                    if displays
                    else None,
                    "model_rounds": result.turns,
                    "calls": calls,
                    "completed_display": any(
                        r.metadata.get("completed_display") for r in result.tool_results
                    ),
                    "customer_message_present": bool(result.content),
                }
            )
        )


if __name__ == "__main__":
    main()
