"""Tests for bundled skill TOML files."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from openjarvis.core.conversation import agent_turn_scope, conversation_scope
from openjarvis.core.events import EventBus
from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.loader import load_skill
from openjarvis.skills.tool_adapter import SkillTool
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
from openjarvis.tools.display import DisplayCartTool

# Resolve the skills/builtin/ directory relative to the project root.
BUILTIN_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "openjarvis" / "skills" / "data"
)

# Collect all TOML files once so parametrized IDs are readable.
_toml_files = sorted(BUILTIN_DIR.glob("*.toml")) if BUILTIN_DIR.is_dir() else []


def _load_all():
    """Load every bundled skill manifest.

    Returns a list of (path, manifest) tuples.
    """
    results = []
    for toml_path in _toml_files:
        manifest = load_skill(toml_path)
        results.append((toml_path, manifest))
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBundledSkillsLoad:
    """Verify every TOML in skills/builtin/ can be loaded without errors."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_all_bundled_skills_load(self, toml_path: Path):
        manifest = load_skill(toml_path)
        assert manifest is not None


class TestBundledSkillsHaveName:
    """Every bundled skill must declare a non-empty name."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_all_skills_have_name(self, toml_path: Path):
        manifest = load_skill(toml_path)
        assert manifest.name, f"{toml_path.name} has an empty name"
        assert len(manifest.name) > 0


class TestBundledSkillsHaveSteps:
    """Every bundled skill must have at least one step."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_all_skills_have_steps(self, toml_path: Path):
        manifest = load_skill(toml_path)
        assert len(manifest.steps) >= 1, f"{toml_path.name} has no steps"


class TestSkillCount:
    """The builtin directory must contain at least 20 skill files."""

    def test_skill_count(self):
        assert len(_toml_files) >= 20, (
            f"Expected at least 20 bundled skills, found {len(_toml_files)}"
        )


class TestStepsHaveToolNames:
    """Every step in every bundled skill must have a non-empty tool_name."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_steps_have_tool_names(self, toml_path: Path):
        manifest = load_skill(toml_path)
        for i, step in enumerate(manifest.steps):
            assert step.tool_name, f"{toml_path.name} step {i} has empty tool_name"


def test_workspace_checkout_accepts_atomic_cart_replacement() -> None:
    manifest = load_skill(
        Path(__file__).resolve().parents[2]
        / "skills"
        / "trendcoffee-checkout.toml"
    )

    assert manifest.checkout is True
    assert manifest.accepts_cart_lines is True


_CHECKOUT_SKILL = (
    Path(__file__).resolve().parents[2] / "skills" / "trendcoffee-checkout.toml"
)
_ADD_TO_CART_SKILL = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "trendcoffee-add-to-cart.toml"
)


class _SequenceRecording(BaseTool):
    def __init__(self, name: str, results: list[ToolResult]):
        self.tool_id = name
        self.results = list(results)
        self.calls: list[dict] = []

    @property
    def spec(self):
        return ToolSpec(name=self.tool_id, description="recorded sequence")

    def execute(self, **params):
        self.calls.append(params)
        return self.results[len(self.calls) - 1]


def _run_batch_add(menu_items: list[dict], requests: list[dict]):
    response = ToolResult(
        tool_name="http_request",
        content=json.dumps(
            {"result": {"items": [{"menuItems": menu_items}], "hasNext": False}}
        ),
        success=True,
        metadata={
            "status_code": 200,
            "final_url": "https://trendcoffee.net/api/latest/menu/specific/public",
            "content_type": "application/json",
            "truncated": False,
        },
    )
    http = _SequenceRecording("http_request", [response])
    cart = DisplayCartTool()
    bus = EventBus()
    cart._bus = bus
    tool = SkillTool(
        load_skill(_ADD_TO_CART_SKILL),
        SkillExecutor(ToolExecutor([cart, http], bus)),
    )
    events = []
    bus.subscribe("display_update", events.append)
    with conversation_scope("trendcoffee-batch-add"):
        result = tool.execute(items=requests, customer_message="Đã thêm vào giỏ.")
        snapshot = cart.current_snapshot()
    return tool, result, http, snapshot, events


def test_workspace_batch_add_reads_once_and_mutates_the_cart_once() -> None:
    menu_items = [
        {
            "product": {
                "name": "Coca Cola",
                "isActive": True,
                "variants": [
                    {
                        "slug": "cola-standard",
                        "price": 25_000,
                        "size": {"name": "tiêu chuẩn"},
                    }
                ],
            }
        },
        {
            "product": {
                "name": "Nước dừa",
                "isActive": True,
                "variants": [
                    {
                        "slug": "coconut-standard",
                        "price": 35_000,
                        "size": {"name": "tiêu chuẩn"},
                    }
                ],
            }
        },
    ]

    tool, result, http, snapshot, events = _run_batch_add(
        menu_items,
        [
            {"contains": "coca cola", "quantity": 1, "note": ""},
            {"contains": "nước dừa", "quantity": 2, "note": "ít đá"},
        ],
    )

    assert set(tool.spec.parameters["properties"]) == {"items", "customer_message"}
    assert result.success
    assert len(http.calls) == 1
    assert http.calls[0]["method"] == "GET"
    assert snapshot is not None
    assert [
        (line["variant_id"], line["quantity"], line["note"])
        for line in snapshot["lines"]
    ] == [
        ("cola-standard", 1, ""),
        ("coconut-standard", 2, "ít đá"),
    ]
    assert len(events) == 1


def test_workspace_batch_add_rejects_an_ambiguous_match_before_cart_mutation() -> None:
    menu_items = [
        {
            "product": {
                "name": "Cà phê sữa",
                "isActive": True,
                "variants": [
                    {"slug": "milk", "price": 40_000, "size": {"name": "chuẩn"}}
                ],
            }
        },
        {
            "product": {
                "name": "Cà phê muối",
                "isActive": True,
                "variants": [
                    {"slug": "salt", "price": 45_000, "size": {"name": "chuẩn"}}
                ],
            }
        },
    ]

    _tool, result, http, snapshot, events = _run_batch_add(
        menu_items,
        [{"contains": "cà phê", "quantity": 1, "note": ""}],
    )

    assert not result.success
    assert "exactly one" in result.content
    assert len(http.calls) == 1
    assert snapshot is not None
    assert snapshot["lines"] == []
    assert events == []


def test_workspace_batch_add_rejects_an_unavailable_match() -> None:
    menu_items = [
        {
            "product": {
                "name": "Nước dừa",
                "isActive": False,
                "variants": [
                    {
                        "slug": "coconut-standard",
                        "price": 35_000,
                        "size": {"name": "tiêu chuẩn"},
                    }
                ],
            }
        }
    ]

    _tool, result, http, snapshot, events = _run_batch_add(
        menu_items,
        [{"contains": "nước dừa", "quantity": 1, "note": ""}],
    )

    assert not result.success
    assert result.content == "invalid_cart_items"
    assert len(http.calls) == 1
    assert snapshot is not None
    assert snapshot["lines"] == []
    assert events == []


def _run_checkout(
    *,
    response_type: str,
    response_table: str | None = "table-73",
    requested_type: str = "at-table",
    requested_table: str = "table-73",
    requested_order_note: str = "Làm nhanh giúp mình",
):
    cart_line = {
        "variant_id": "coffee-standard",
        "name": "Coffee",
        "unit_price": 100_000,
        "quantity": 2,
        "size": "standard",
        "note": "",
    }
    returned_table = (
        {
            "name": "73",
            "slug": response_table,
            "status": "available",
            "location": "floor-1",
            "createdAt": "2026-09-12T00:00:00Z",
        }
        if response_table is not None
        else None
    )
    created = ToolResult(
        tool_name="http_request",
        content=json.dumps(
            {
                "result": {
                    "slug": "order-1",
                    "status": "pending",
                    "subtotal": 200_000,
                    "type": response_type,
                    "description": requested_order_note,
                    "table": returned_table,
                    "orderItems": [
                        {
                            "variant": {"slug": "coffee-standard"},
                            "quantity": 2,
                            "note": "",
                        }
                    ],
                }
            }
        ),
        success=True,
    )
    payment = ToolResult(
        tool_name="http_request",
        content=json.dumps(
            {
                "result": {
                    "slug": "payment-1",
                    "amount": 200_000,
                    "paymentMethod": "bank-transfer",
                    "statusCode": "pending",
                }
            }
        ),
        success=True,
    )
    http = _SequenceRecording("http_request", [created, payment])
    bill = _SequenceRecording(
        "display_bill",
        [ToolResult(tool_name="display_bill", content="bill", success=True)],
    )
    display = _SequenceRecording(
        "display_payment_qr",
        [
            ToolResult(
                tool_name="display_payment_qr",
                content="displayed",
                success=True,
                metadata={"completed_display": True},
            )
        ],
    )
    cart = DisplayCartTool()
    tool = SkillTool(
        load_skill(_CHECKOUT_SKILL),
        SkillExecutor(ToolExecutor([cart, http, bill, display])),
    )
    with conversation_scope(
        f"checkout-{requested_type}-{requested_table}-{response_type}-{response_table}"
    ):
        with agent_turn_scope() as nonce:
            result = tool.execute(
                order_type=requested_type,
                order_note=requested_order_note,
                table=requested_table,
                customer_message="Payment ready",
                turn_nonce=nonce,
                cart_lines=[cart_line],
            )
    return tool, result, http, bill, display


def test_workspace_checkout_infers_order_and_guarded_cart_parameters() -> None:
    manifest = load_skill(_CHECKOUT_SKILL)
    parameters = SkillTool(manifest, SkillExecutor(ToolExecutor([]))).spec.parameters

    assert manifest.input_schema == {}
    assert set(parameters["properties"]) == {
        "order_type",
        "order_note",
        "table",
        "customer_message",
        "turn_nonce",
        "cart_revision",
        "cart_lines",
    }
    assert set(parameters["required"]) == {
        "order_type",
        "order_note",
        "table",
        "customer_message",
        "turn_nonce",
    }
    assert parameters["oneOf"] == [
        {"required": ["cart_revision"]},
        {"required": ["cart_lines"]},
    ]


def test_workspace_checkout_sends_selected_at_table_type_and_slug() -> None:
    _tool, result, http, bill, display = _run_checkout(response_type="at-table")

    assert result.success is True
    assert len(http.calls) == 2
    create_body = json.loads(http.calls[0]["body"])
    assert create_body["type"] == "at-table"
    assert create_body["table"] == "table-73"
    assert create_body["description"] == "Làm nhanh giúp mình"
    assert create_body["orderItems"] == [
        {
            "quantity": 2,
            "variant": "coffee-standard",
            "promotion": None,
            "note": "",
        }
    ]
    assert bill.calls == [
        {
            "order_id": "order-1",
            "status": "pending",
            "order_type": "at-table",
            "branch": "ba9355f797",
            "lines": [
                {
                    "line_id": bill.calls[0]["lines"][0]["line_id"],
                    "name": "Coffee",
                    "size": "standard",
                    "note": "",
                    "quantity": 2,
                    "unit_price": 100_000,
                    "line_total": 200_000,
                }
            ],
            "total": 200_000,
        }
    ]
    assert display.calls == [
        {
            "order_id": "order-1",
            "payment_slug": "payment-1",
            "status": "pending",
            "order_type": "at-table",
            "branch": "ba9355f797",
            "table_name": "73",
            "lines": bill.calls[0]["lines"],
            "total": 200_000,
            "customer_message": "Payment ready",
        }
    ]


def test_workspace_checkout_stops_before_payment_on_order_type_mismatch() -> None:
    _tool, result, http, bill, display = _run_checkout(response_type="take-out")

    assert result.success is False
    assert len(http.calls) == 1
    assert bill.calls == []
    assert display.calls == []


def test_workspace_checkout_stops_before_payment_on_table_slug_mismatch() -> None:
    _tool, result, http, bill, display = _run_checkout(
        response_type="at-table",
        response_table="different-table",
    )

    assert result.success is False
    assert len(http.calls) == 1
    assert bill.calls == []
    assert display.calls == []


def test_workspace_take_out_checkout_accepts_null_returned_table() -> None:
    _tool, result, http, bill, display = _run_checkout(
        response_type="take-out",
        response_table=None,
        requested_type="take-out",
        requested_table="",
    )

    assert result.success is True
    assert len(http.calls) == 2
    assert len(bill.calls) == 1
    assert len(display.calls) == 1


def test_workspace_checkout_rejects_draft_type_mismatch_before_provider_write() -> None:
    cart = DisplayCartTool()
    cart._bus = EventBus()
    http = _SequenceRecording("http_request", [])
    bill = _SequenceRecording("display_bill", [])
    qr = _SequenceRecording("display_payment_qr", [])
    tool = SkillTool(
        load_skill(_CHECKOUT_SKILL),
        SkillExecutor(ToolExecutor([cart, http, bill, qr])),
    )

    with conversation_scope("checkout-draft-type-mismatch"):
        cart.execute(
            action="add",
            item={
                "variant_id": "coffee-standard",
                "name": "Coffee",
                "unit_price": 100_000,
                "quantity": 1,
            },
        )
        cart.execute(action="set_order_type", order_type="at-table")
        noted = cart.execute(action="set_order_note", order_note="Không đường")
        with agent_turn_scope() as nonce:
            result = tool.execute(
                order_type="take-out",
                order_note="Không đường",
                table="",
                customer_message="Payment ready",
                turn_nonce=nonce,
                cart_revision=noted.metadata["cart_revision"],
            )

    assert not result.success
    assert "order type" in result.content
    assert http.calls == []
    assert bill.calls == []
    assert qr.calls == []


def test_workspace_checkout_rejects_draft_table_mismatch_before_write() -> None:
    cart = DisplayCartTool()
    cart._bus = EventBus()
    http = _SequenceRecording("http_request", [])
    bill = _SequenceRecording("display_bill", [])
    qr = _SequenceRecording("display_payment_qr", [])
    tool = SkillTool(
        load_skill(_CHECKOUT_SKILL),
        SkillExecutor(ToolExecutor([cart, http, bill, qr])),
    )

    with conversation_scope("checkout-draft-table-mismatch"):
        cart.execute(
            action="add",
            item={
                "variant_id": "coffee-standard",
                "name": "Coffee",
                "unit_price": 100_000,
                "quantity": 1,
            },
        )
        selected = cart.execute(
            action="set_table",
            table="table-73",
            table_name="73",
        )
        assert selected.success
        with agent_turn_scope() as nonce:
            result = tool.execute(
                order_type="at-table",
                order_note="",
                table="different-table",
                customer_message="Payment ready",
                turn_nonce=nonce,
                cart_revision=selected.metadata["cart_revision"],
            )

    assert not result.success
    assert "table" in result.content
    assert http.calls == []
    assert bill.calls == []
    assert qr.calls == []


_MENU_SKILL = Path(__file__).resolve().parents[2] / "skills" / "trendcoffee-menu.toml"
_MENU_ENTRIES = [
    {
        "product": {
            "name": "Trà sữa khoai môn",
            "description": "",
            "catalog": {"name": "món trà"},
            "isActive": True,
            "variants": [{"slug": "v-taro", "price": 45000}],
        }
    },
    {
        "product": {
            "name": "Bánh mì",
            "description": "Nhân KHOAI lang",
            "catalog": {"name": "món bánh"},
            "isActive": True,
            "variants": [{"slug": "v-bread", "price": 30000}],
        }
    },
    {
        "product": {
            "name": "Cà phê sữa",
            "catalog": {"name": "cà phê"},
            "isActive": False,
            "variants": [{"slug": "v-coffee", "price": 29000}],
        }
    },
]

_CATEGORY_MENU_ENTRIES = [
    {
        "product": {
            "name": "Bánh mì",
            "description": "",
            "catalog": {"name": "món bánh"},
            "isActive": True,
            "variants": [{"slug": "v-bread", "price": 30_000}],
        }
    },
    {
        "product": {
            "name": "Americano",
            "description": "",
            "catalog": {"name": "cà phê"},
            "isActive": True,
            "variants": [{"slug": "v-americano", "price": 35_000}],
        }
    },
    {
        "product": {
            "name": "Bơ dầm",
            "description": "",
            "catalog": {"name": "sinh tố"},
            "isActive": True,
            "variants": [{"slug": "v-avocado", "price": 45_000}],
        }
    },
    {
        "product": {
            "name": "Cơm gà",
            "description": "",
            "catalog": {"name": "món ăn"},
            "isActive": True,
            "variants": [{"slug": "v-rice", "price": 65_000}],
        }
    },
]


class _Recording(BaseTool):
    def __init__(self, name: str, result: ToolResult):
        self.tool_id = name
        self.result = result
        self.calls: list[dict] = []

    @property
    def spec(self):
        return ToolSpec(name=self.tool_id, description="recorded")

    def execute(self, **params):
        self.calls.append(params)
        return self.result


def _run_menu(params: dict, *, has_next: bool = False, entries=None):
    body = json.dumps(
        {
            "result": {
                "hasNext": has_next,
                "items": [{"menuItems": _MENU_ENTRIES if entries is None else entries}],
            }
        },
        ensure_ascii=False,
    )
    http = _Recording(
        "http_request",
        ToolResult(
            tool_name="http_request",
            content=body,
            success=True,
            metadata={
                "status_code": 200,
                "content_type": "application/json; charset=utf-8",
                "truncated": False,
                "final_url": "https://trendcoffee.net/api/latest/menu/specific/public",
            },
        ),
    )
    display = _Recording(
        "display_menu",
        ToolResult(
            tool_name="display_menu",
            content='{"shown":"menu","count":0,"complete":true}',
            success=True,
            metadata={"completed_display": True, "customer_message": "derived"},
        ),
    )
    tool = SkillTool(
        load_skill(_MENU_SKILL), SkillExecutor(ToolExecutor([http, display]))
    )
    return tool, tool.execute(**params), http, display, body


def test_menu_recipe_exposes_only_native_inputs_and_fixed_request_contract() -> None:
    manifest = load_skill(_MENU_SKILL)
    parameters = SkillTool(manifest, SkillExecutor(ToolExecutor([]))).spec.parameters
    recipe = manifest.metadata["openjarvis"]["request_recipe"]

    assert parameters["type"] == "object"
    assert set(parameters["properties"]) == {"contains", "minPrice", "maxPrice"}
    assert set(parameters["required"]) == {"contains", "minPrice", "maxPrice"}
    assert parameters["additionalProperties"] is False
    assert parameters["properties"]["contains"] == {"type": "string"}
    assert parameters["properties"]["minPrice"] == {"type": "integer", "minimum": 0}
    assert parameters["properties"]["maxPrice"] == {"type": "integer", "minimum": 0}
    assert recipe["origin"] == "https://trendcoffee.net"
    assert recipe["method"] == "GET"
    assert recipe["read_only"] is True
    assert recipe["allowed_content_types"] == ["application/json"]
    assert json.loads(recipe["required_paths_json"]) == [
        {"path": "result.items", "type": "array"},
        {"path": "result.hasNext", "type": "boolean"},
    ]
    assert [step.tool_name for step in manifest.steps] == [
        "http_request",
        "display_menu",
    ]
    assert "customer_message" not in manifest.steps[-1].arguments_template


def test_menu_recipe_binds_native_price_and_filters_text_locally() -> None:
    _, result, http, display, body = _run_menu(
        {"contains": "khoai", "minPrice": 20000, "maxPrice": 50000}
    )

    assert result.success is True
    [request] = http.calls
    assert request["timeout"] == 5
    url = urllib.parse.urlsplit(request["url"])
    query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
    assert request["method"] == "GET"
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "trendcoffee.net",
        "/api/latest/menu/specific/public",
    )
    assert query["minPrice"] == ["20000"]
    assert query["maxPrice"] == ["50000"]
    assert query["catalog"] == [""]
    assert not {"q", "query", "search", "keyword", "contains"} & set(query)
    assert "khoai" not in request["url"]

    [published] = display.calls
    assert published == {
        "items": [
            {
                "id": "v-taro",
                "name": "Trà sữa khoai môn",
                "price": 45000,
                "available": True,
            },
            {"id": "v-bread", "name": "Bánh mì", "price": 30000, "available": True},
        ],
        "result_complete": True,
    }
    assert result.metadata["completed_display"] is True
    assert body not in result.content
    assert "menuItems" not in result.content


@pytest.mark.parametrize(
    ("contains", "expected_id"),
    [
        ("món bánh", "v-bread"),
        ("cà phê", "v-americano"),
        ("sinh tố", "v-avocado"),
        ("món ăn", "v-rice"),
    ],
)
def test_menu_recipe_filters_categories_using_catalog_name(
    contains: str, expected_id: str
) -> None:
    _, result, _, display, _ = _run_menu(
        {"contains": contains, "minPrice": 0, "maxPrice": 300000},
        entries=_CATEGORY_MENU_ENTRIES,
    )

    assert result.success is True
    assert [item["id"] for item in display.calls[0]["items"]] == [expected_id]


def test_menu_recipe_empty_contains_publishes_every_row_in_provider_order() -> None:
    _, result, _, display, _ = _run_menu(
        {"contains": "", "minPrice": 0, "maxPrice": 300000}
    )

    assert result.success is True
    assert [item["id"] for item in display.calls[0]["items"]] == [
        "v-taro",
        "v-bread",
        "v-coffee",
    ]


def test_menu_recipe_rejects_array_contains_before_io() -> None:
    _, result, http, display, _ = _run_menu(
        {"contains": ["món bánh", "MÓN TRÀ"], "minPrice": 0, "maxPrice": 300000}
    )

    assert result.success is False
    assert result.content.startswith("invalid_skill_arguments")
    assert http.calls == []
    assert display.calls == []


@pytest.mark.parametrize(
    ("has_next", "entries"),
    [
        (True, None),
        (False, [_MENU_ENTRIES[0], _MENU_ENTRIES[0]]),
    ],
    ids=["incomplete", "duplicate-identity"],
)
def test_menu_recipe_asserts_completeness_and_identity_before_display(
    has_next, entries
) -> None:
    _, result, http, display, _ = _run_menu(
        {"contains": "", "minPrice": 0, "maxPrice": 300000},
        has_next=has_next,
        entries=entries,
    )

    assert len(http.calls) == 1
    assert result.success is False
    assert display.calls == []


def test_menu_recipe_rejects_model_authored_message_before_io() -> None:
    _, result, http, display, _ = _run_menu(
        {
            "contains": "",
            "minPrice": 0,
            "maxPrice": 300000,
            "customer_message": "đang tìm",
        }
    )

    assert result.success is False
    assert result.content.startswith("invalid_skill_arguments")
    assert http.calls == []
    assert display.calls == []
