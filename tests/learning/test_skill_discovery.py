"""Tests for SkillDiscovery — mining recurring tool sequences from traces."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

import pytest

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.learning.agents.skill_discovery import SkillDiscovery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _Step:
    step_type: str = "tool_call"
    tool_name: str = ""
    name: str = ""  # fallback


@dataclass
class _StepEnum:
    """Step with an enum-like step_type that has a .value attribute."""

    class _StepType:
        def __init__(self, val: str) -> None:
            self.value = val

        def __str__(self) -> str:
            return self.value

    step_type: object = None
    tool_name: str = ""

    def __post_init__(self) -> None:
        if self.step_type is None:
            self.step_type = self._StepType("tool_call")


@dataclass
class _Trace:
    query: str = ""
    outcome: float = 1.0
    steps: list = field(default_factory=list)


def _make_trace(tools: List[str], outcome: float = 1.0, query: str = "") -> _Trace:
    steps = [_Step(step_type="tool_call", tool_name=t) for t in tools]
    return _Trace(query=query, outcome=outcome, steps=steps)


def _make_dict_trace(tools: List[str], outcome: float = 1.0, query: str = "") -> dict:
    steps = [{"step_type": "tool_call", "tool_name": t} for t in tools]
    return {"query": query, "outcome": outcome, "steps": steps}


def _completed_transaction_trace(*, headers: dict | None = None) -> Trace:
    """A completed order whose verification uses the produced order id."""
    return Trace(
        query="Place a latte order",
        result="Your order is confirmed.",
        steps=[
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=1.0,
                input={
                    "tool": "http_request",
                    "arguments": {
                        "method": "POST",
                        "url": "https://shop.example/orders",
                        "headers": headers or {"X-Request-ID": "safe"},
                        "body": {"drink": "latte"},
                    },
                },
                output={
                    "success": True,
                    "result": json.dumps({"order": {"id": "ord-123"}}),
                },
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=2.0,
                input={"tool": "memory_store", "arguments": {"key": "ignored"}},
                output={"success": True, "result": "saved"},
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=3.0,
                input={
                    "tool": "http_request",
                    "arguments": {
                        "method": "GET",
                        "url": "https://shop.example/orders/ord-123",
                        "body": {"order_id": "ord-123", "note": 'say "yes"'},
                    },
                },
                output={"success": True, "result": '{"status": "confirmed"}'},
            ),
        ],
    )


def _completed_menu_trace(*, headers: dict | None = None) -> Trace:
    """A cold read whose changed request, replay, render, and display correspond."""
    today = datetime.now().astimezone().date().isoformat()
    before_url = f"https://shop.example/menu?date={today}&q="
    observed_url = f"https://shop.example/menu?date={today}&q=Fresh%20noodles"
    request_headers = headers or {"Accept": "application/json"}
    response = {
        "items": [
            {"id": "noodles-1", "name": "Fresh noodles", "price": 59_000}
        ],
        "hasNext": False,
    }
    return Trace(
        query="Show me the food menu",
        result="Here is the food menu.",
        steps=[
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=1.0,
                input={
                    "tool": "browser_network_requests",
                    "arguments": {"includeStatic": False},
                },
                output={
                    "success": True,
                    "result": json.dumps(
                        {
                            "requests": [
                                {
                                    "method": "GET",
                                    "url": before_url,
                                    "headers": request_headers,
                                }
                            ]
                        }
                    ),
                },
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=2.0,
                input={
                    "tool": "browser_fill_form",
                    "arguments": {
                        "selector": "#search",
                        "value": "Fresh noodles",
                    },
                },
                output={"success": True, "result": "filled"},
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=3.0,
                input={
                    "tool": "browser_network_requests",
                    "arguments": {"includeStatic": False},
                },
                output={
                    "success": True,
                    "result": json.dumps(
                        {
                            "requests": [
                                {
                                    "method": "GET",
                                    "url": before_url,
                                    "headers": request_headers,
                                },
                                {
                                    "method": "GET",
                                    "url": observed_url,
                                    "headers": request_headers,
                                },
                            ]
                        }
                    ),
                },
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=4.0,
                input={
                    "tool": "http_request",
                    "arguments": {
                        "method": "GET",
                        "url": observed_url,
                        "headers": request_headers,
                    },
                },
                output={
                    "success": True,
                    "result": json.dumps(response),
                },
                metadata={
                    "status_code": 200,
                    "content_type": "application/json; charset=utf-8",
                    "truncated": False,
                    "final_url": observed_url,
                },
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=5.0,
                input={
                    "tool": "browser_verify_list_visible",
                    "arguments": {"selector": "[data-result-item]"},
                },
                output={
                    "success": True,
                    "result": json.dumps(
                        {
                            "count": 1,
                            "items": [
                                {"id": "noodles-1", "text": "Fresh noodles"}
                            ],
                            "has_pagination": False,
                            "complete": {"path": "hasNext", "equals": False},
                        }
                    ),
                },
            ),
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=6.0,
                input={
                    "tool": "display_menu",
                    "arguments": {
                        "items": [
                            {
                                "id": "noodles-1",
                                "name": "Fresh noodles",
                                "price": 59_000,
                            }
                        ],
                        "result_complete": True,
                    },
                },
                output={"success": True, "result": "displayed"},
            ),
        ],
    )


def _menu_step(trace: Trace, tool_name: str, occurrence: int = 0) -> TraceStep:
    return [
        step
        for step in trace.steps
        if step.input.get("tool") == tool_name
    ][occurrence]


def _sync_menu_correspondence(trace: Trace) -> None:
    replay = _menu_step(trace, "http_request")
    response = json.loads(replay.output["result"])
    response["complete"] = False
    replay.output["result"] = json.dumps(response)
    display_arguments = _menu_step(trace, "display_menu").input["arguments"]
    display_arguments["result_complete"] = True
    items = display_arguments["items"]
    _menu_step(trace, "browser_verify_list_visible").output["result"] = json.dumps(
        {
            "count": len(items),
            "items": [
                {"id": item["id"], "text": item["name"]} for item in items
            ],
            "has_pagination": False,
            "complete": {"path": "complete", "equals": False},
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    def test_interrupted_diagnostics_do_not_raise_successful_recipe_frequency(self):
        traces = [_make_dict_trace(["web_search", "calculator"]) for _ in range(2)]
        interrupted = _make_dict_trace(["web_search", "calculator"], outcome=0.0)
        interrupted["metadata"] = {"status": "interrupted"}
        traces.append(interrupted)
        assert SkillDiscovery(min_frequency=3).analyze_traces(traces) == []

    def test_empty_traces(self):
        sd = SkillDiscovery()
        result = sd.analyze_traces([])
        assert result == []
        assert sd.discovered_skills == []

    def test_single_trace_below_threshold(self):
        """One trace cannot meet min_frequency=3."""
        sd = SkillDiscovery(min_frequency=3)
        traces = [_make_trace(["web_search", "file_write"], outcome=1.0)]
        result = sd.analyze_traces(traces)
        assert result == []

    def test_recurring_sequence(self):
        """3+ traces with same 2-tool sequence should be discovered."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.5)
        traces = [
            _make_trace(["web_search", "file_write"], outcome=0.9, query=f"q{i}")
            for i in range(5)
        ]
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        # The web_search_file_write sequence should appear
        names = [s.name for s in result]
        assert "web_search_file_write" in names
        skill = [s for s in result if s.name == "web_search_file_write"][0]
        assert skill.frequency == 5
        assert skill.tool_sequence == ["web_search", "file_write"]
        assert skill.avg_outcome >= 0.5

    def test_outcome_threshold(self):
        """Low-outcome sequences should be filtered out."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.8)
        traces = [_make_trace(["a", "b"], outcome=0.3) for _ in range(5)]
        result = sd.analyze_traces(traces)
        assert result == []

    def test_sequence_length_limits(self):
        """Sequences shorter than min or longer than max should be excluded."""
        # Only length-1 tools (below min_sequence_length=2)
        sd = SkillDiscovery(
            min_frequency=2,
            min_sequence_length=2,
            max_sequence_length=3,
        )
        short_traces = [_make_trace(["a"], outcome=1.0) for _ in range(5)]
        result = sd.analyze_traces(short_traces)
        assert result == []

        # Long sequence: with max_sequence_length=2, a 4-tool sequence
        # should only produce subsequences of length 2
        sd2 = SkillDiscovery(
            min_frequency=3,
            min_sequence_length=2,
            max_sequence_length=2,
        )
        long_traces = [_make_trace(["a", "b", "c", "d"], outcome=1.0) for _ in range(3)]
        result2 = sd2.analyze_traces(long_traces)
        # All discovered skills should have exactly 2 tools
        for skill in result2:
            assert len(skill.tool_sequence) == 2

    def test_to_skill_manifests(self):
        """Verify manifest dict format has expected keys."""
        sd = SkillDiscovery(min_frequency=2, min_outcome=0.0)
        traces = [_make_trace(["calc", "save"], outcome=0.9) for _ in range(3)]
        sd.analyze_traces(traces)
        manifests = sd.to_skill_manifests()
        assert len(manifests) >= 1
        m = manifests[0]
        assert "name" in m
        assert "description" in m
        assert "steps" in m
        assert "metadata" in m
        assert m["metadata"]["auto_discovered"] is True
        assert m["metadata"]["frequency"] >= 2
        assert isinstance(m["steps"], list)
        for step in m["steps"]:
            assert "tool" in step
            assert "params" in step

    def test_sort_by_quality(self):
        """Higher frequency*outcome skills should come first."""
        sd = SkillDiscovery(min_frequency=2, min_outcome=0.0)
        # Group A: high freq, high outcome
        traces_a = [_make_trace(["alpha", "beta"], outcome=1.0) for _ in range(10)]
        # Group B: low freq, low outcome
        traces_b = [_make_trace(["gamma", "delta"], outcome=0.3) for _ in range(2)]
        result = sd.analyze_traces(traces_a + traces_b)
        assert len(result) >= 2
        # First should be the higher quality one
        assert result[0].name == "alpha_beta"
        q0 = result[0].frequency * result[0].avg_outcome
        q1 = result[1].frequency * result[1].avg_outcome
        assert q0 >= q1

    def test_dict_traces(self):
        """Test with dict-format traces instead of objects."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.5)
        traces = [
            _make_dict_trace(
                ["read", "compute", "write"],
                outcome=0.8,
                query=f"task {i}",
            )
            for i in range(4)
        ]
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        # At minimum, 2-tool subsequences should be found
        all_tools = []
        for skill in result:
            all_tools.extend(skill.tool_sequence)
        assert "read" in all_tools or "compute" in all_tools

    def test_example_inputs_captured(self):
        """Example queries should be stored (up to 3)."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.5)
        traces = [
            _make_trace(
                ["search", "summarize"],
                outcome=0.9,
                query=f"Find info about topic {i}",
            )
            for i in range(5)
        ]
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        skill = result[0]
        assert len(skill.example_inputs) > 0
        # Max 3 examples stored
        assert len(skill.example_inputs) <= 3
        assert all("Find info about topic" in q for q in skill.example_inputs)

    def test_enum_step_type(self):
        """Steps with enum-style step_type (has .value) should work."""
        sd = SkillDiscovery(min_frequency=3, min_outcome=0.0)
        traces = []
        for i in range(4):
            steps = [
                _StepEnum(tool_name="tool_a"),
                _StepEnum(tool_name="tool_b"),
            ]
            traces.append(_Trace(query=f"q{i}", outcome=0.9, steps=steps))
        result = sd.analyze_traces(traces)
        assert len(result) >= 1
        names = [s.name for s in result]
        assert "tool_a_tool_b" in names


class TestTransactionTraceParameterization:
    def test_classifies_only_a_completed_verified_transaction(self):
        """A missing verification or failed tool must prevent learning."""
        discovery = SkillDiscovery()
        trace = _completed_transaction_trace()

        assert discovery.is_successful_transaction(trace) is True

        trace.steps[-1].output["success"] = False
        assert discovery.is_successful_transaction(trace) is False

    def test_rejects_a_failed_tool_after_the_read_verification(self):
        """Verification does not excuse a later failed tool call in the trace."""
        discovery = SkillDiscovery()
        trace = _completed_transaction_trace()
        trace.steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=4.0,
                input={"tool": "display_text", "arguments": {"text": "failed"}},
                output={"success": False, "result": "display failed"},
            )
        )

        assert discovery.is_successful_transaction(trace) is False

    def test_parameterizes_order_id_and_omits_learning_bookkeeping(self):
        """Later exact JSON scalar values become replayable dotted output paths."""
        discovery = SkillDiscovery()
        trace = _completed_transaction_trace()

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        assert re.fullmatch(r"learned-transaction-[0-9a-f]{12}", manifest.name)
        assert [step.tool_name for step in manifest.steps] == [
            "http_request",
            "http_request",
        ]
        assert [step.output_key for step in manifest.steps] == ["step_0", "step_1"]
        assert "{step_0.order.id}" in manifest.steps[1].arguments_template
        assert 'say \\"yes\\"' in manifest.steps[1].arguments_template
        assert manifest.metadata["openjarvis"]["source"] == "learned"
        assert manifest.metadata["intent"] == "place a latte order"
        assert discovery.parameterize_trace(trace).name == manifest.name

    def test_omits_cold_browser_discovery_from_the_warm_transaction(self):
        discovery = SkillDiscovery()
        trace = _completed_transaction_trace()
        trace.steps.insert(
            0,
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=0.5,
                input={
                    "tool": "browser_network_requests",
                    "arguments": {"includeStatic": False},
                },
                output={"success": True, "result": "found order endpoint"},
            ),
        )

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        assert [step.tool_name for step in manifest.steps] == [
            "http_request",
            "http_request",
        ]

    def test_keeps_incidental_numeric_and_boolean_arguments_literal(self):
        """Only distinctive string results may become cross-step bindings."""
        discovery = SkillDiscovery()
        trace = _completed_transaction_trace()
        trace.steps[0].output["result"] = json.dumps(
            {"order": {"id": "ord-123"}, "count": 2, "approved": True}
        )
        trace.steps[-1].input["arguments"]["body"].update(
            {"quantity": 2, "confirmed": True}
        )

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        arguments = json.loads(manifest.steps[1].arguments_template)
        assert arguments["body"]["order_id"] == "{step_0.order.id}"
        assert arguments["body"]["quantity"] == 2
        assert arguments["body"]["confirmed"] is True

    @pytest.mark.parametrize(
        "header_name",
        [
            "Authorization",
            "cookie",
            "SET-COOKIE",
            "x-API-key",
            "Proxy-Authorization",
        ],
    )
    def test_rejects_case_insensitive_secret_headers(self, header_name: str):
        """Persisted credential headers are never copied into learned manifests."""
        discovery = SkillDiscovery()
        trace = _completed_transaction_trace(headers={header_name: "secret"})

        assert discovery.is_successful_transaction(trace) is False
        assert discovery.parameterize_trace(trace) is None


class TestReadDisplayTraceParameterization:
    def test_does_not_learn_a_local_cart_mutation_as_a_read_recipe(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.query = "Add two pizzas to my cart"
        trace.steps[-1].input = {
            "tool": "display_cart",
            "arguments": {
                "action": "add",
                "item": {
                    "variant_id": "pizza-standard",
                    "name": "Pizza Truyền Thống Ý",
                    "size": "tiêu chuẩn",
                    "unit_price": 107_000,
                    "quantity": 2,
                    "note": "",
                },
            },
        }

        assert discovery.is_successful_read_display(trace) is False
        assert discovery.parameterize_trace(trace) is None

    def test_learns_a_completed_read_that_was_displayed(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        assert re.fullmatch(r"learned-read-[0-9a-f]{12}", manifest.name)
        assert [step.tool_name for step in manifest.steps] == [
            "http_request",
            "display_menu",
        ]
        arguments = json.loads(manifest.steps[0].arguments_template)
        assert arguments == {
            "method": "GET",
            "url": "https://shop.example/menu?date={today}&q={q|urlencode}",
            "headers": {"Accept": "application/json"},
        }
        assert manifest.input_schema["properties"] == {
            "q": {"type": "string", "minLength": 1}
        }
        assert manifest.metadata["openjarvis"]["request_recipe"] == {
            "origin": "https://shop.example",
            "method": "GET",
            "read_only": True,
            "captured_from": "browser_network_requests",
            "allowed_content_types": ["application/json"],
            "required_paths_json": (
                '[{"path": "items", "type": "array"}, '
                '{"path": "hasNext", "type": "boolean"}]'
            ),
        }
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert display_arguments == {
            "items": [
                {
                    "id": "{step_0.items.0.id}",
                    "name": "{step_0.items.0.name}",
                    "price": "{step_0.items.0.price}",
                }
            ],
            "result_complete": True,
        }
        assert manifest.metadata["requires_fresh_confirmation"] is False

    def test_learns_multiple_fresh_reads_that_feed_one_filtered_display(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.query = "goi y cac mon co dau tay"
        _menu_step(trace, "http_request").output["result"] = json.dumps(
            {"items": [{"name": "Strawberry matcha latte", "price": 60_000}]}
        )
        trace.steps.insert(
            2,
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=2.5,
                input={
                    "tool": "http_request",
                    "arguments": {
                        "method": "GET",
                        "url": "https://shop.example/menu?category=smoothie",
                    },
                },
                output={
                    "success": True,
                    "result": json.dumps(
                        {"items": [{"name": "Yaourt Dâu Đá Xay", "price": 65_000}]}
                    ),
                },
            ),
        )
        trace.steps[-1].input["arguments"] = {
            "items": [
                {"name": "Strawberry matcha latte", "price": 60_000},
                {"name": "Yaourt Dâu Đá Xay", "price": 65_000},
            ]
        }

        manifest = discovery.parameterize_trace(trace)

        assert manifest is None

    def test_learns_an_evidence_native_complete_menu_display(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.steps[-1].input["arguments"] = {"all_from_latest_http": True}

        manifest = discovery.parameterize_trace(trace)

        assert manifest is None

    def test_omits_an_optional_display_value_not_grounded_in_the_read(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.steps[-1].input["arguments"]["items"][0]["badge"] = "chef pick"

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert "badge" not in display_arguments["items"][0]

    def test_duplicate_prices_are_grounded_to_the_matching_product_record(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").output["result"] = json.dumps(
            {
                "result": {
                    "items": [
                        {
                            "product": {
                                "slug": "tea-1",
                                "name": "Tea one",
                                "variants": [{"price": 49_000}],
                            }
                        },
                        {
                            "product": {
                                "slug": "tea-2",
                                "name": "Tea two",
                                "variants": [{"price": 49_000}],
                            }
                        },
                    ]
                }
            }
        )
        trace.steps[-1].input["arguments"] = {
            "items": [
                {"id": "tea-1", "name": "Tea one", "price": 49_000},
                {"id": "tea-2", "name": "Tea two", "price": 49_000},
            ]
        }
        _sync_menu_correspondence(trace)

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert display_arguments["items"][0]["price"] == (
            "{step_0.result.items.0.product.variants.0.price}"
        )
        assert display_arguments["items"][1]["price"] == (
            "{step_0.result.items.1.product.variants.0.price}"
        )

    def test_duplicate_prices_ground_correctly_when_anchor_key_has_stray_whitespace(
        self,
    ):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").output["result"] = json.dumps(
            {
                "result": {
                    "items": [
                        {
                            "product": {
                                "name": "Chicken popcorn ",
                                "variants": [{"price": 86_000}],
                                "isActive": True,
                            }
                        },
                        {
                            "product": {
                                "name": "Taco ga",
                                "variants": [{"price": 86_000}],
                                "isActive": True,
                            }
                        },
                    ]
                }
            }
        )
        trace.steps[-1].input["arguments"] = {
            "items": [
                {"id": "Chicken popcorn", "name": "Chicken popcorn", "price": 86_000},
                {"id": "Taco ga", "name": "Taco ga", "price": 86_000},
            ]
        }
        _sync_menu_correspondence(trace)

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert display_arguments["items"][0]["price"] == (
            "{step_0.result.items.0.product.variants.0.price}"
        )
        assert display_arguments["items"][1]["price"] == (
            "{step_0.result.items.1.product.variants.0.price}"
        )

    def test_display_name_composed_from_product_fields_is_fully_grounded(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").output["result"] = json.dumps(
            {
                "result": {
                    "items": [
                        {
                            "product": {
                                "slug": "water-1",
                                "name": "Sparkling water",
                                "description": "Vikoda",
                                "variants": [{"price": 55_000}],
                            }
                        }
                    ]
                }
            }
        )
        trace.steps[-1].input["arguments"] = {
            "items": [
                {
                    "id": "water-1",
                    "name": "Sparkling water (Vikoda)",
                    "price": 55_000,
                }
            ]
        }
        _sync_menu_correspondence(trace)

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert display_arguments["items"][0]["name"] == (
            "{step_0.result.items.0.product.name} "
            "({step_0.result.items.0.product.description})"
        )

    def test_duplicate_name_and_description_prefers_the_name_field(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").output["result"] = json.dumps(
            {
                "items": [{
                    "product": {
                    "slug": "smoothie-1",
                    "name": "Berry smoothie",
                    "description": "Berry smoothie",
                    "price": 65_000,
                    }
                }]
            }
        )
        trace.steps[-1].input["arguments"] = {
            "items": [
                {
                    "id": "smoothie-1",
                    "name": "Berry smoothie",
                    "price": 65_000,
                }
            ]
        }
        _sync_menu_correspondence(trace)

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert display_arguments["items"][0]["name"] == (
            "{step_0.items.0.product.name}"
        )

    def test_unverifiable_name_suffix_falls_back_to_the_grounded_product_name(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").output["result"] = json.dumps(
            {
                "items": [{
                    "product": {
                    "slug": "cake-1",
                    "name": "Salted egg croissant",
                    "description": "Bánh croissant than tre kim sa",
                    "price": 65_000,
                    }
                }]
            }
        )
        trace.steps[-1].input["arguments"] = {
            "items": [
                {
                    "id": "cake-1",
                    "name": "Salted egg croissant (croissant than tre kim sa)",
                    "price": 65_000,
                }
            ]
        }
        _sync_menu_correspondence(trace)

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        display_arguments = json.loads(manifest.steps[1].arguments_template)
        assert display_arguments["items"][0]["name"] == (
            "{step_0.items.0.product.name}"
        )

    def test_learns_despite_a_failed_skill_manage_recall_before_the_read(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.steps.insert(
            0,
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=0.5,
                input={
                    "tool": "skill_manage",
                    "arguments": {"action": "run", "name": "learned-read-deleted"},
                },
                output={
                    "success": False,
                    "result": "Skill run failed: not found",
                },
            ),
        )

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        assert [step.tool_name for step in manifest.steps] == [
            "http_request",
            "display_menu",
        ]

    def test_does_not_learn_a_read_that_was_not_displayed(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.steps.pop()

        assert discovery.parameterize_trace(trace) is None

    def test_does_not_learn_multiple_reads_that_cannot_all_be_returned(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        trace.steps.insert(4, _menu_step(trace, "http_request"))

        assert discovery.parameterize_trace(trace) is None

    def test_rejects_secret_headers_from_read_skills(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace(headers={"Authorization": "secret"})

        assert discovery.parameterize_trace(trace) is None

    def test_parallel_end_metadata_wins_over_a_stale_step_input(self):
        discovery = SkillDiscovery()
        trace = _completed_menu_trace()
        read = _menu_step(trace, "http_request")
        read.input["arguments"]["url"] = "https://shop.example/wrong"
        read.metadata["arguments"] = {
            "method": "GET",
            "url": (
                "https://shop.example/menu?date="
                f"{datetime.now().astimezone().date().isoformat()}"
                "&q=Fresh%20noodles"
            ),
            "headers": {"Accept": "application/json"},
        }

        manifest = discovery.parameterize_trace(trace)

        assert manifest is not None
        arguments = json.loads(manifest.steps[0].arguments_template)
        assert arguments["url"] == "https://shop.example/menu?date={today}&q={q|urlencode}"

    @pytest.mark.parametrize("occurrence", [0, 1])
    def test_rejects_when_either_network_snapshot_is_missing(self, occurrence):
        trace = _completed_menu_trace()
        trace.steps.remove(_menu_step(trace, "browser_network_requests", occurrence))

        assert SkillDiscovery().parameterize_trace(trace) is None

    def test_rejects_when_observed_request_did_not_change(self):
        trace = _completed_menu_trace()
        before = _menu_step(trace, "browser_network_requests", 0)
        after = _menu_step(trace, "browser_network_requests", 1)
        after.output["result"] = before.output["result"]

        assert SkillDiscovery().parameterize_trace(trace) is None

    @pytest.mark.parametrize(
        "field, value",
        [
            ("method", "HEAD"),
            ("url", "https://other.example/menu?q=Fresh%20noodles"),
            ("url", "https://shop.example/other?q=Fresh%20noodles"),
        ],
    )
    def test_rejects_when_direct_replay_differs_from_observed_request(
        self, field, value
    ):
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").input["arguments"][field] = value

        assert SkillDiscovery().parameterize_trace(trace) is None

    @pytest.mark.parametrize(
        "verification",
        [
            {"count": 2, "items": [{"id": "noodles-1", "text": "Fresh noodles"}]},
            {"count": 1, "items": [{"id": "other", "text": "Fresh noodles"}]},
        ],
    )
    def test_rejects_browser_results_that_do_not_correspond(self, verification):
        trace = _completed_menu_trace()
        verification["has_pagination"] = False
        verification["complete"] = {"path": "hasNext", "equals": False}
        _menu_step(trace, "browser_verify_list_visible").output["result"] = json.dumps(
            verification
        )

        assert SkillDiscovery().parameterize_trace(trace) is None

    @pytest.mark.parametrize(
        "failure", ["truncated", "non_json", "incomplete", "no_id"]
    )
    def test_rejects_incomplete_or_unidentified_replay(self, failure):
        trace = _completed_menu_trace()
        replay = _menu_step(trace, "http_request")
        if failure == "truncated":
            replay.metadata["truncated"] = True
        elif failure == "non_json":
            replay.output["result"] = "not-json"
        else:
            body = json.loads(replay.output["result"])
            if failure == "incomplete":
                body["hasNext"] = True
            else:
                body["items"][0].pop("id")
            replay.output["result"] = json.dumps(body)

        assert SkillDiscovery().parameterize_trace(trace) is None

    def test_rejects_display_items_not_grounded_in_replay(self):
        trace = _completed_menu_trace()
        _menu_step(trace, "display_menu").input["arguments"]["items"][0]["id"] = (
            "invented"
        )

        assert SkillDiscovery().parameterize_trace(trace) is None

    def test_rejects_cross_origin_final_url(self):
        trace = _completed_menu_trace()
        _menu_step(trace, "http_request").metadata["final_url"] = (
            "https://other.example/menu"
        )

        assert SkillDiscovery().parameterize_trace(trace) is None

    def test_narration_without_evidence_is_never_a_recipe(self):
        trace = Trace(query="menu", result="Đã tìm thấy món", steps=[])

        assert SkillDiscovery().parameterize_trace(trace) is None
