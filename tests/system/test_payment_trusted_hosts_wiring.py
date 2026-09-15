"""payment_trusted_origins parses into the exact tuple display_payment_qr gets.

Unit-level on purpose: SystemBuilder.build() is expensive to stand up and
these two static methods are the entire path from config string to tool
attribute -- no need to build a whole system to pin it down.
"""

from __future__ import annotations

import pytest

from openjarvis.system.builder import SystemBuilder
from openjarvis.tools.display import (
    DisplayCartTool,
    DisplayMenuTool,
    DisplayPaymentQrTool,
)


def test_parse_trusted_origins_blank_is_empty():
    assert SystemBuilder._parse_trusted_origins("") == ()


def test_parse_trusted_origins_normalizes_scheme_host_and_effective_port():
    assert SystemBuilder._parse_trusted_origins(
        " HTTPS://TrendCoffee.net , https://B.example:8443 "
    ) == (
        ("https", "trendcoffee.net", 443),
        ("https", "b.example", 8443),
    )


def test_parse_trusted_origins_drops_empty_entries():
    assert SystemBuilder._parse_trusted_origins(
        "https://a.example,,http://b.example,"
    ) == (("https", "a.example", 443), ("http", "b.example", 80))


def test_parse_trusted_origins_all_commas_is_empty():
    assert SystemBuilder._parse_trusted_origins(",") == ()


def test_parse_trusted_origins_rejects_host_only_values():
    with pytest.raises(ValueError, match="scheme"):
        SystemBuilder._parse_trusted_origins("trendcoffee.net")


def test_inject_payment_trusted_origins_reaches_the_payment_tool():
    tool = DisplayPaymentQrTool()
    origins = (("https", "trendcoffee.net", 443),)

    SystemBuilder._inject_payment_trusted_origins(tool, origins)

    assert tool._payment_trusted_origins == origins


def test_inject_payment_trusted_origins_skips_a_non_payment_display_tool():
    tool = DisplayMenuTool()

    SystemBuilder._inject_payment_trusted_origins(
        tool, (("https", "trendcoffee.net", 443),)
    )

    assert not hasattr(tool, "_payment_trusted_origins")


def test_inject_draft_cart_settler_connects_payment_to_the_cart_owner():
    cart = DisplayCartTool()
    payment = DisplayPaymentQrTool()

    SystemBuilder._inject_draft_cart_settler([cart, payment])

    assert payment._cart_settler == cart.settle_current


def test_checkout_guard_blocks_raw_writes_before_network_dispatch():
    from openjarvis.tools.http_request import HttpRequestTool

    cart = DisplayCartTool()
    http = HttpRequestTool()
    SystemBuilder._inject_checkout_guard([cart, http])
    result = http.execute(
        url="https://merchant.example/orders", method="POST", body="{}"
    )
    assert not result.success
    assert "checkout_confirmation_required" in result.content


def test_model_filter_keeps_internal_primitives_registered():
    from openjarvis.tools._stubs import ToolExecutor
    from openjarvis.tools.http_request import HttpRequestTool

    http, cart = HttpRequestTool(), DisplayCartTool()
    internal = ToolExecutor([http, cart])
    visible = SystemBuilder._model_visible_tools([http, cart], "http_request")
    assert [t.spec.name for t in visible] == ["display_cart"]
    assert internal.get_tool("http_request") is http


def test_configured_checkout_rejects_a_different_contract():
    from openjarvis.core.conversation import agent_turn_scope, conversation_scope
    from openjarvis.core.events import EventBus
    from openjarvis.skills.executor import SkillExecutor
    from openjarvis.skills.tool_adapter import SkillTool
    from openjarvis.skills.types import SkillManifest
    from openjarvis.tools._stubs import ToolExecutor

    cart = DisplayCartTool()
    cart._bus = EventBus()
    manifest = SkillManifest(name="active", checkout=True)
    skill = SkillTool(manifest, SkillExecutor(ToolExecutor([cart])))
    SystemBuilder._inject_checkout_guard([cart, skill])
    with conversation_scope("contract"):
        cart.execute(
            action="add",
            item={
                "variant_id": "coffee",
                "name": "Coffee",
                "quantity": 1,
                "unit_price": 100,
            },
        )
        with agent_turn_scope() as nonce:
            with pytest.raises(ValueError, match="contract"):
                cart.begin_checkout(nonce, 1, b"different")
            assert (
                cart.begin_checkout(nonce, 1, manifest.manifest_bytes())["total"] == 100
            )
            cart.end_checkout()
