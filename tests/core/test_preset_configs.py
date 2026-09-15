"""Smoke test: every shipped preset config must load cleanly.

Presets are installed via `jarvis init --preset <name>`, which copies
`configs/openjarvis/examples/<name>.toml` to `~/.openjarvis/config.toml`.
A preset that fails to parse via `load_config()` would break first-time
setup, so we validate the whole set on every commit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomllib

from openjarvis.core.config import JarvisConfig, load_config

PRESETS_DIR = (
    Path(__file__).resolve().parents[2] / "configs" / "openjarvis" / "examples"
)


def _preset_paths() -> list[Path]:
    return sorted(PRESETS_DIR.glob("*.toml"))


def test_presets_directory_exists() -> None:
    assert PRESETS_DIR.is_dir(), f"presets dir missing: {PRESETS_DIR}"


def test_at_least_one_preset_ships() -> None:
    assert _preset_paths(), f"no preset .toml files in {PRESETS_DIR}"


@pytest.mark.parametrize(
    "preset_path",
    _preset_paths(),
    ids=lambda p: p.stem,
)
def test_preset_loads(preset_path: Path) -> None:
    cfg = load_config(path=preset_path)
    assert isinstance(cfg, JarvisConfig)
    # A preset must at least name an engine and an agent — those are the two
    # slots `jarvis init` expects to be populated for a working first run.
    assert cfg.engine.default, f"{preset_path.stem}: engine.default is empty"
    assert cfg.agent.default_agent, f"{preset_path.stem}: agent.default_agent is empty"


def test_kiosk_mcp_preset_keeps_browser_tools_off_the_default_agent_surface() -> None:
    """The kiosk fast path stays narrow while Playwright remains connected."""
    preset_path = PRESETS_DIR / "ordering-kiosk-mcp.toml"
    cfg = load_config(path=preset_path)
    raw_toml = tomllib.loads(preset_path.read_text())
    enabled = {name.strip() for name in cfg.tools.enabled.split(",")}
    expected_enabled = {
        "http_request",
        "skill_manage",
        "display_menu",
        "display_cart",
        "display_bill",
        "display_payment_qr",
        "display_clear",
    }
    expected_playwright_tools = {
        "browser_snapshot",
        "browser_find",
        "browser_navigate",
        "browser_navigate_back",
        "browser_tabs",
        "browser_click",
        "browser_type",
        "browser_fill_form",
        "browser_select_option",
        "browser_hover",
        "browser_press_key",
        "browser_wait_for",
        "browser_handle_dialog",
        "browser_drag",
        "browser_drop",
        "browser_resize",
        "browser_close",
        "browser_network_requests",
        "browser_verify_element_visible",
        "browser_verify_text_visible",
        "browser_verify_value",
        "browser_verify_list_visible",
    }
    servers = json.loads(cfg.tools.mcp.servers)
    playwright = next(server for server in servers if server["name"] == "playwright")
    include_tools = playwright["include_tools"]

    assert enabled == expected_enabled
    assert len(enabled) == len(expected_enabled)
    assert not any(name.startswith("browser_") for name in enabled)
    assert "repl" not in enabled
    assert cfg.agent.max_turns == 8
    assert cfg.skills.enabled is True
    assert cfg.skills.active == (
        "trendcoffee-menu,trendcoffee-add-to-cart,trendcoffee-checkout"
    )
    assert set(cfg.tools.model_hidden.split(",")) == {
        "display_menu",
        "display_bill",
        "display_payment_qr",
    }
    assert "http_request" in enabled
    assert set(include_tools) == expected_playwright_tools
    assert len(include_tools) == len(expected_playwright_tools)
    assert cfg.tools.payment_trusted_origins == "https://trendcoffee.net"
    assert "merchants" not in raw_toml
    assert "data_plane" not in raw_toml


def test_kiosk_mcp_active_skills_expose_menu_and_checkout_composites(
    tmp_path: Path,
) -> None:
    from openjarvis.core.events import EventBus
    from openjarvis.skills.manager import SkillManager

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    manager = SkillManager(EventBus(), overlay_dir=tmp_path)
    manager.discover([PRESETS_DIR.parents[2] / "skills"])

    tools = manager.get_skill_tools(active=cfg.skills.active)

    assert {tool.spec.name for tool in tools} == {
        "skill_trendcoffee-menu",
        "skill_trendcoffee-add-to-cart",
        "skill_trendcoffee-checkout",
    }


def test_kiosk_mcp_prompt_routes_menu_reads_through_one_composite_skill() -> None:
    """Luna chooses the composite skill; it never replays the raw procedure."""
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    normalized = " ".join(prompt.split())
    assert "call skill_trendcoffee-menu exactly once" in normalized
    assert 'contains="" only for an explicit complete-menu request' in normalized
    assert "literal search text" in normalized
    assert "terminal display result is authoritative" in normalized
    assert "only in minPrice/maxPrice, never in contains" in normalized
    assert "menu is preloaded for visual browsing" in normalized
    assert "does not itself populate runtime_context.displayed_menu" in normalized
    for catalog_slug in (
        "d07665b001",
        "a87d969ab5",
        "e6cfb79d94",
        "12f10617d2",
        "29e0552928",
        "24dffe01f6",
        "d60c1f2946",
        "8c25bf5866",
    ):
        assert catalog_slug not in prompt
    for raw_procedure in (
        "catalog=",
        "catalog_slug",
        "menuItems",
        "all_from_latest_http",
        "/menu/specific/public",
        "exactly one GET per likely category",
    ):
        assert raw_procedure not in prompt


def test_kiosk_mcp_prompt_grounds_cart_items_in_the_displayed_menu() -> None:
    """An item already on screen must be added without another menu lookup."""
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    normalized = " ".join(prompt.split())
    assert "runtime_context.displayed_menu" in normalized
    assert (
        "Never re-run skill_trendcoffee-menu for an item already in displayed_menu"
        in normalized
    )
    assert "filtered-menu GET needed to resolve it" not in normalized
    assert "necessary fresh menu read, then dispatch" not in normalized


def test_kiosk_mcp_prompt_routes_cold_multi_item_add_through_one_recipe() -> None:
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    normalized = " ".join(prompt.split())
    assert "skill_trendcoffee-add-to-cart" in normalized
    assert "one fresh menu GET and one atomic cart publication" in normalized
    assert "remove and update use the saved line_id" in normalized
    assert "Put every targeted line in one call" in normalized
    assert 'display_cart(action="update", updates=[' in normalized
    assert 'display_cart(action="remove", line_ids=[' in normalized
    assert "set_order_note" in normalized
    assert "set_order_type" in normalized
    assert "set_table" in normalized
    assert "pass draft_cart.order_note as order_note" in normalized


def test_kiosk_mcp_prompt_uses_http_output_and_keeps_provider_contract() -> None:
    """The resolved public prompt must match the preset's HTTP-only surface."""
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    assert re.search(r"\brepl\b", prompt, flags=re.IGNORECASE) is None
    assert "last_result" not in prompt
    for provider_fact in (
        "https://trendcoffee.net/api/latest",
        "GET /branch",
        "GET /catalogs",
        "POST /orders/public",
        "GET /orders/{order_slug}",
        "POST /payment/initiate/public",
        "Any 2xx is success",
        "101006",
        "105002",
        "127000",
        "all 121 items",
        'size["name"]',
        "Every one of those eleven fields is required",
        "`at-table`",
        "`take-out`",
        "`delivery`",
        '"paymentMethod": "bank-transfer"',
        '"orderSlug": "<order_slug>"',
        "`qrCode`, `slug`, `status` and `order`",
        "Omit `qr_code`",
        "Accept: application/json",
        "Content-Type: application/json",
    ):
        assert provider_fact in prompt

    assert "Full catalogue | `GET /products`" not in prompt
    assert re.search(
        r"GET /products.*?do not use it", prompt, flags=re.IGNORECASE | re.DOTALL
    )


def test_kiosk_mcp_prompt_can_list_available_tables_for_at_table_orders() -> None:
    """A dine-in customer must get live choices instead of an invented limitation."""
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    table_policy = prompt.split("## Available tables for at-table orders", 1)[1].split(
        "## ", 1
    )[0]
    assert "GET /tables?branch=ba9355f797" in table_policy
    assert '`status` is exactly `"available"`' in table_policy
    assert "table name" in table_policy
    assert "table slug" in table_policy
    assert "guess `/tables/public`" in table_policy


def test_kiosk_mcp_prompt_routes_supported_order_types_through_checkout_skill() -> None:
    """The guarded composite receives the confirmed type and provider table slug."""
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    normalized = " ".join(prompt.split())
    assert '`order_type="take-out"` with `table=""`' in normalized
    assert "store its table slug and human name in draft_cart" in normalized
    assert "reuse draft_cart.table at confirmation" in normalized
    assert "do not perform a second mandatory table GET" in normalized
    assert "Delivery is not supported by this prepared checkout skill" in normalized
    assert "take-out-only procedure" not in normalized
    assert (
        "current confirmation for the draft and take-out order type"
        not in normalized
    )


def test_kiosk_mcp_preset_learns_turns_without_training_a_model() -> None:
    """Turn learning is the point; model training is not part of this preset."""
    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")

    assert cfg.learning.enabled is True
    assert cfg.learning.auto_update is True
    assert cfg.learning.training_enabled is False
    # Prepared active procedures are direct tools; the learned catalog remains
    # available through skill_manage without exposing every learned schema.
    assert cfg.skills.enabled is True
    assert cfg.skills.active == (
        "trendcoffee-menu,trendcoffee-add-to-cart,trendcoffee-checkout"
    )


def test_kiosk_mcp_prompt_gates_a_learned_skill_on_a_current_confirmation() -> None:
    """Replaying a past order without asking again is the failure to prevent."""
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    assert "skill_manage" in prompt
    assert "same intent" in prompt
    assert re.search(
        r"confirmed.*?in this conversation", prompt, flags=re.IGNORECASE | re.DOTALL
    )
    assert re.search(
        r"past confirmation is never a current one", prompt, flags=re.IGNORECASE
    )


def test_kiosk_mcp_prompt_separates_cold_discovery_from_warm_live_reads() -> None:
    from openjarvis.system.agent_construction import resolve_agent_system_prompt

    cfg = load_config(path=PRESETS_DIR / "ordering-kiosk-mcp.toml")
    prompt = resolve_agent_system_prompt(cfg.agent)

    assert prompt is not None
    assert "Cold discovery" in prompt
    assert "browser_network_requests" in prompt
    assert "learned-read-" in prompt
    assert re.search(r"still.*fresh.*HTTP", prompt, flags=re.IGNORECASE | re.DOTALL)
    assert "display_menu" in prompt
    assert re.search(
        r"never run.*learned-read.*cart", prompt, flags=re.IGNORECASE | re.DOTALL
    )
    assert re.search(
        r"canonical.*supersedes.*learned-read",
        prompt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert re.search(
        r"previous timeout.*not evidence.*menu has no data",
        prompt,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert re.search(
        r'contains="".*only.*complete-menu', prompt, flags=re.IGNORECASE | re.DOTALL
    )
