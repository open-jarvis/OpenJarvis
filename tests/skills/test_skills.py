"""Tests for skill system (Phase 15.2)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.loader import load_skill, load_skill_directory
from openjarvis.skills.types import SkillManifest, SkillStep
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class EchoTool(BaseTool):
    """Simple tool that echoes input."""

    tool_id = "echo"

    @property
    def spec(self):
        return ToolSpec(name="echo", description="Echo input")

    def execute(self, **params):
        return ToolResult(
            tool_name="echo",
            content=params.get("text", ""),
            success=True,
        )


class UpperTool(BaseTool):
    """Simple tool that uppercases input."""

    tool_id = "upper"

    @property
    def spec(self):
        return ToolSpec(name="upper", description="Uppercase input")

    def execute(self, **params):
        return ToolResult(
            tool_name="upper",
            content=params.get("text", "").upper(),
            success=True,
        )


class RecordingHttpTool(BaseTool):
    tool_id = "http_request"

    def __init__(self, result: ToolResult):
        self.result = result
        self.calls = []

    @property
    def spec(self):
        return ToolSpec(name="http_request", description="Recorded HTTP request")

    def execute(self, **params):
        self.calls.append(params)
        return self.result


def _http_result(
    *,
    content: str = '{"result":{"items":[]}}',
    final_url: str = "https://shop.example/search",
    content_type: str = "application/json; charset=utf-8",
    truncated: bool = False,
    status_code: int = 200,
) -> ToolResult:
    return ToolResult(
        tool_name="http_request",
        content=content,
        success=True,
        metadata={
            "status_code": status_code,
            "content_type": content_type,
            "truncated": truncated,
            "final_url": final_url,
        },
    )


def _request_recipe_manifest(arguments_template: str) -> SkillManifest:
    return SkillManifest(
        name="native-search",
        metadata={
            "openjarvis": {
                "request_recipe": {
                    "origin": "https://shop.example",
                    "method": "GET",
                    "read_only": True,
                    "allowed_content_types": ["application/json"],
                }
            }
        },
        steps=[
            SkillStep(
                tool_name="http_request",
                arguments_template=arguments_template,
                output_key="response",
            )
        ],
    )


class TestSkillManifest:
    def test_create_manifest(self):
        manifest = SkillManifest(
            name="test_skill",
            version="0.1.0",
            steps=[SkillStep(tool_name="echo", output_key="result")],
        )
        assert manifest.name == "test_skill"
        assert len(manifest.steps) == 1

    def test_manifest_bytes(self):
        manifest = SkillManifest(name="test", steps=[])
        data = manifest.manifest_bytes()
        assert isinstance(data, bytes)
        assert b"test" in data


def _load_manifest(tmp_path: Path, skill_body: str) -> SkillManifest:
    path = tmp_path / "skill.toml"
    path.write_text(skill_body)
    return load_skill(path)


def _skill_toml(
    schema: object,
    *,
    recipe: str = "",
    checkout: bool = False,
) -> str:
    return f'''\
[skill]
name = "native-search"
checkout = {str(checkout).lower()}
input_schema_json = '{json.dumps(schema)}'

{recipe}

[[skill.steps]]
tool_name = "http_request"
arguments_template = '{{"url":"https://shop.example/search?q={{q|urlencode}}","method":"GET"}}'
'''


_SAFE_REQUEST_RECIPE = """\
[skill.metadata.openjarvis.request_recipe]
origin = "https://shop.example"
method = "GET"
read_only = true
captured_from = "browser_network_requests"
"""


class TestExplicitSkillInputSchema:
    @pytest.mark.parametrize(
        "properties, required",
        [
            ({"q": {"type": "string", "minLength": 1}}, ["q"]),
            (
                {
                    "department_code": {"type": "string"},
                    "day": {"type": "integer", "minimum": 0, "maximum": 6},
                },
                ["department_code", "day"],
            ),
        ],
    )
    def test_loads_declared_property_names_without_translation(
        self, tmp_path: Path, properties: dict, required: list[str]
    ) -> None:
        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

        manifest = _load_manifest(tmp_path, _skill_toml(schema))

        assert manifest.input_schema == schema

    def test_manifest_bytes_sign_schema_and_only_request_recipe_metadata(self):
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
            "additionalProperties": False,
        }
        recipe = {
            "origin": "https://shop.example",
            "method": "GET",
            "read_only": True,
        }
        manifest = SkillManifest(
            name="native-search",
            input_schema=schema,
            metadata={
                "openjarvis": {
                    "request_recipe": recipe,
                    "source": "local",
                },
                "few_shot": {"query": "ignored"},
            },
        )

        signed = json.loads(manifest.manifest_bytes())

        assert signed["input_schema"] == schema
        assert signed["metadata"] == {
            "openjarvis": {"request_recipe": recipe}
        }

    def test_legacy_manifest_bytes_are_unchanged(self):
        manifest = SkillManifest(name="legacy")
        expected = {
            "name": "legacy",
            "version": "0.1.0",
            "description": "",
            "author": "",
            "steps": [],
            "required_capabilities": [],
            "tags": [],
            "depends": [],
        }

        assert manifest.manifest_bytes() == json.dumps(
            expected, sort_keys=True
        ).encode()

    @pytest.mark.parametrize(
        "schema_text",
        [
            "not-json",
            '["not", "an", "object"]',
            '{"type":"array","items":{"type":"string"}}',
            '{"type":"object","properties":{"q":{"type":"string","pattern":"x"}}}',
            '{"type":"object","properties":{},"required":["missing"]}',
        ],
    )
    def test_rejects_invalid_or_unsupported_schema(
        self, tmp_path: Path, schema_text: str
    ) -> None:
        body = f'''\
[skill]
name = "invalid-schema"
input_schema_json = '{schema_text}'
'''

        with pytest.raises(ValueError, match="input_schema"):
            _load_manifest(tmp_path, body)

    def test_checkout_cannot_replace_guarded_schema(self, tmp_path: Path) -> None:
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        }

        with pytest.raises(ValueError, match="checkout"):
            _load_manifest(tmp_path, _skill_toml(schema, checkout=True))

    @pytest.mark.parametrize(
        "origin",
        [
            "https://shop.example/api",
            "https://shop.example?tenant=one",
            "https://shop.example#menu",
            "https://user@shop.example",
        ],
    )
    def test_request_recipe_rejects_non_origin_url(
        self, tmp_path: Path, origin: str
    ) -> None:
        recipe = _SAFE_REQUEST_RECIPE.replace(
            'origin = "https://shop.example"', f'origin = "{origin}"'
        )
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
            "additionalProperties": False,
        }

        with pytest.raises(ValueError, match="origin"):
            _load_manifest(tmp_path, _skill_toml(schema, recipe=recipe))

    @pytest.mark.parametrize(
        "recipe, error",
        [
            (
                _SAFE_REQUEST_RECIPE.replace("read_only = true", "read_only = false"),
                "read_only",
            ),
            (
                _SAFE_REQUEST_RECIPE.replace('method = "GET"', 'method = "POST"'),
                "method",
            ),
            (
                _SAFE_REQUEST_RECIPE.replace('method = "GET"', 'method = "get"'),
                "method",
            ),
        ],
    )
    def test_request_recipe_requires_read_only_get_or_head(
        self, tmp_path: Path, recipe: str, error: str
    ) -> None:
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

        with pytest.raises(ValueError, match=error):
            _load_manifest(tmp_path, _skill_toml(schema, recipe=recipe))

    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    def test_accepts_safe_request_recipe_methods(
        self, tmp_path: Path, method: str
    ) -> None:
        recipe = _SAFE_REQUEST_RECIPE.replace('method = "GET"', f'method = "{method}"')
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

        manifest = _load_manifest(tmp_path, _skill_toml(schema, recipe=recipe))

        assert manifest.metadata["openjarvis"]["request_recipe"]["method"] == method

    def test_request_recipe_requires_closed_top_level_schema(
        self, tmp_path: Path
    ) -> None:
        schema = {"type": "object", "properties": {}, "required": []}

        with pytest.raises(ValueError, match="additionalProperties"):
            _load_manifest(
                tmp_path,
                _skill_toml(schema, recipe=_SAFE_REQUEST_RECIPE),
            )

    def test_toml_markdown_merge_preserves_input_schema(self, tmp_path: Path) -> None:
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
            "additionalProperties": False,
        }
        skill_dir = tmp_path / "native-search"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(_skill_toml(schema))
        (skill_dir / "SKILL.md").write_text(
            "---\nname: native-search\n---\nSearch safely."
        )

        manifest = load_skill_directory(skill_dir)

        assert manifest.input_schema == schema
        assert manifest.markdown_content == "Search safely."


class TestSkillExecutor:
    @staticmethod
    def _filter_expression(source="{response.result.items}"):
        return {
            "$filter": source,
            "as": "row",
            "where": {
                "any": [
                    {"contains_folded": ["{row.label}", "{q}"]},
                    {"contains_folded": ["{row.description}", "{q}"]},
                ]
            },
        }

    @pytest.mark.parametrize(
        "rows",
        [
            [
                {"label": "  CÁ   NƯỚNG  ", "description": "fresh"},
                {"label": "Khoai", "description": "other"},
            ],
            [
                {"label": "CÁ khoa", "description": "morning"},
                {"label": "Khám", "description": "afternoon"},
            ],
        ],
    )
    def test_filter_is_unicode_folded_and_shape_agnostic(self, rows):
        rendered = SkillExecutor._render_json_value(
            self._filter_expression(),
            {"response": {"result": {"items": rows}}, "q": "cá"},
        )

        assert rendered == [rows[0]]

    def test_filter_missing_optional_field_is_false_and_preserves_order_duplicates(
        self,
    ):
        first = {"label": "coffee"}
        rows = [first, {"description": "tea"}, first]

        rendered = SkillExecutor._render_json_value(
            self._filter_expression(),
            {"response": {"result": {"items": rows}}, "q": "coffee"},
        )

        assert rendered == [first, first]
        assert rendered[0] is first
        assert rendered[1] is first

    def test_expect_one_returns_the_only_resolved_row(self):
        row = {"id": "only", "name": "Nước dừa"}

        rendered = SkillExecutor._render_json_value(
            {"$expect_one": "{matches}"},
            {"matches": [row]},
        )

        assert rendered is row

    @pytest.mark.parametrize("matches", [[], [{"id": "a"}, {"id": "b"}]])
    def test_expect_one_rejects_zero_or_ambiguous_rows(self, matches):
        with pytest.raises(ValueError, match="exactly one"):
            SkillExecutor._render_json_value(
                {"$expect_one": "{matches}"},
                {"matches": matches},
            )

    def test_filter_predicates_compose_all_any_contains_and_ranges(self):
        expression = {
            "$filter": "{rows}",
            "as": "row",
            "where": {
                "all": [
                    {"any": [{"contains_folded": ["{row.text}", "{q}"]}]},
                    {"gte": ["{row.amount}", "{minimum}"]},
                    {"lte": ["{row.amount}", "{maximum}"]},
                ]
            },
        }
        rows = [
            {"text": "Coffee", "amount": 2},
            {"text": "Coffee", "amount": 5},
            {"text": "Tea", "amount": 2},
        ]

        rendered = SkillExecutor._render_json_value(
            expression,
            {"rows": rows, "q": "coffee", "minimum": 1, "maximum": 3},
        )

        assert rendered == [rows[0]]

    @pytest.mark.parametrize(
        "expression, error",
        [
            (
                {"$filter": "{rows}", "as": "row", "where": {"unknown": []}},
                "operator",
            ),
            (
                {
                    "$filter": "{rows}",
                    "as": "row",
                    "where": {"gte": ["{row.amount}"]},
                },
                "arity",
            ),
            (
                {"$filter": "{rows}", "as": "row", "where": {"all": True}},
                "arity",
            ),
            (
                {"$filter": "{rows}", "as": "row", "where": True},
                "predicate",
            ),
        ],
    )
    def test_filter_invalid_predicate_fails_closed(self, expression, error):
        with pytest.raises(ValueError, match=error):
            SkillExecutor._render_json_value(
                expression,
                {"rows": [{"amount": 1}]},
            )

    def test_filter_requires_array_source(self):
        with pytest.raises(ValueError, match="array"):
            SkillExecutor._render_json_value(
                self._filter_expression(source="{rows}"),
                {"rows": {"label": "coffee"}, "q": "coffee"},
            )

    def test_unique_non_empty_assertion_is_generic(self):
        SkillExecutor._validate_assertions(
            [{"actual": ["one", "two"], "all_unique_non_empty": True}],
            {},
        )
        for values in (["one", "one"], ["one", ""]):
            with pytest.raises(ValueError, match="unique non-empty"):
                SkillExecutor._validate_assertions(
                    [{"actual": values, "all_unique_non_empty": True}],
                    {},
                )

    def test_coalesce_selects_first_resolved_non_null_value(self):
        expression = {
            "$coalesce": ["{missing}", "{null_value}", "{selected}", "fallback"]
        }

        rendered = SkillExecutor._render_json_value(
            expression,
            {"null_value": None, "selected": "table-73"},
        )

        assert rendered == "table-73"
        assert SkillExecutor._render_json_value(
            {"$coalesce": [False, "fallback"]}, {}
        ) is False

    @pytest.mark.parametrize(
        "expression",
        [
            {"$coalesce": "not-an-array"},
            {"$coalesce": [], "extra": True},
        ],
    )
    def test_coalesce_invalid_shape_fails_closed(self, expression):
        with pytest.raises(ValueError, match="coalesce"):
            SkillExecutor._render_json_value(expression, {})

    @pytest.mark.parametrize(
        "content",
        [
            '{"result":{"items":{}}}',
            '{"result":{}}',
        ],
    )
    def test_request_recipe_structural_fingerprint_fails_closed(self, content):
        http = RecordingHttpTool(_http_result(content=content))
        manifest = _request_recipe_manifest(
            '{"url":"https://shop.example/search","method":"GET"}'
        )
        manifest.metadata["openjarvis"]["request_recipe"]["required_paths_json"] = (
            '[{"path":"result.items","type":"array"}]'
        )

        result = SkillExecutor(ToolExecutor([http])).run(manifest)

        assert not result.success
        assert result.step_results[0].content == "recipe_stale"

    def test_filter_projects_one_thousand_rows_under_generous_ceiling(self):
        rows = [{"label": f"coffee {index}"} for index in range(1_000)]
        started = time.perf_counter()

        rendered = SkillExecutor._render_json_value(
            self._filter_expression(),
            {"response": {"result": {"items": rows}}, "q": "coffee"},
        )

        assert len(rendered) == 1_000
        assert time.perf_counter() - started < 0.1

    def test_executor_has_no_business_field_registry(self):
        source = Path("src/openjarvis/skills/executor.py").read_text()
        for field in ("name", "price", "specialty", "catalog"):
            assert f'"{field}"' not in source

    def test_urlencode_filter_encodes_once_and_keeps_raw_response(self):
        http = RecordingHttpTool(_http_result())
        executor = SkillExecutor(ToolExecutor([http]))
        manifest = _request_recipe_manifest(
            '{"url":"https://shop.example/search?q={q|urlencode}","method":"GET"}'
        )

        result = executor.run(manifest, initial_context={"q": "cá & khoai?"})

        assert result.success
        assert http.calls == [
            {
                "url": "https://shop.example/search?q=c%C3%A1%20%26%20khoai%3F",
                "method": "GET",
            }
        ]
        assert result.context["response"] == '{"result":{"items":[]}}'

    def test_unfiltered_whole_value_preserves_json_type(self):
        assert json.loads(
            SkillExecutor._render_template('{"value":"{q}"}', {"q": 7})
        ) == {"value": 7}

    def test_unknown_template_filter_fails(self):
        with pytest.raises(ValueError, match="filter"):
            SkillExecutor._render_template(
                '{"url":"https://shop.example/search?q={q|unknown}"}',
                {"q": "coffee"},
            )

    @pytest.mark.parametrize(
        "arguments_template",
        [
            '{"url":"https://evil.example/search?q={q|urlencode}","method":"GET"}',
            '{"url":"https://shop.example/search?q={q|urlencode}","method":"POST"}',
            '{"url":"https://{host}/search","method":"GET"}',
            '{"url":"https://shop.example/search","method":"{method}"}',
        ],
    )
    def test_request_boundary_fails_before_http_dispatch(self, arguments_template):
        http = RecordingHttpTool(_http_result())
        executor = SkillExecutor(ToolExecutor([http]))

        result = executor.run(
            _request_recipe_manifest(arguments_template),
            initial_context={"q": "coffee", "host": "shop.example", "method": "GET"},
        )

        assert not result.success
        assert result.step_results[-1].content == "recipe_stale"
        assert http.calls == []

    @pytest.mark.parametrize(
        "http_result, error",
        [
            (_http_result(final_url="https://evil.example/search"), "recipe_stale"),
            (_http_result(content="not-json"), "recipe_stale"),
            (_http_result(truncated=True), "source_unavailable"),
            (_http_result(content_type="text/html"), "recipe_stale"),
            (_http_result(status_code=503), "source_unavailable"),
        ],
    )
    def test_invalid_recipe_response_fails_before_following_step(
        self, http_result: ToolResult, error: str
    ):
        http = RecordingHttpTool(http_result)
        executor = SkillExecutor(ToolExecutor([http, EchoTool()]))
        manifest = _request_recipe_manifest(
            '{"url":"https://shop.example/search","method":"GET"}'
        )
        manifest.steps.append(
            SkillStep(tool_name="echo", arguments_template='{"text":"displayed"}')
        )

        result = executor.run(manifest)

        assert not result.success
        assert len(result.step_results) == 1
        assert result.step_results[0].content == error

    def test_declarative_mapping_builds_body_from_all_current_cart_lines(self):
        template = json.dumps(
            {
                "body": {
                    "$json": {
                        "items": {
                            "$map": "{cart}",
                            "as": "line",
                            "value": {
                                "sku": "{line.variant_id}",
                                "count": "{line.quantity}",
                            },
                        }
                    }
                }
            }
        )
        rendered = SkillExecutor._render_template(
            template,
            {
                "cart": [
                    {"variant_id": "one", "quantity": 2},
                    {"variant_id": "two", "quantity": 3},
                ]
            },
        )
        assert json.loads(json.loads(rendered)["body"]) == {
            "items": [
                {"sku": "one", "count": 2},
                {"sku": "two", "count": 3},
            ]
        }

    def test_checkout_requires_fresh_cart_claim_before_running_steps(self):
        from openjarvis.core.conversation import agent_turn_scope, conversation_scope
        from openjarvis.tools.display import DisplayCartTool

        cart = DisplayCartTool()
        cart._bus = EventBus()
        executor = SkillExecutor(ToolExecutor([cart, EchoTool()]))
        manifest = SkillManifest(
            name="checkout",
            checkout=True,
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text":"amount={draft_cart.total}"}',
                ),
            ],
        )
        with conversation_scope("guarded-skill"):
            cart.execute(
                action="add",
                item={
                    "variant_id": "coffee",
                    "name": "Coffee",
                    "unit_price": 100,
                    "quantity": 1,
                },
            )
            with agent_turn_scope() as nonce:
                rejected = executor.run(
                    manifest, initial_context={"turn_nonce": nonce, "cart_revision": 0}
                )
                assert not rejected.success
                result = executor.run(
                    manifest,
                    initial_context={
                        "turn_nonce": nonce,
                        "cart_revision": 1,
                        "draft_cart": {"total": 1},
                    },
                )
                assert result.success
                assert result.step_results[-1].content == "amount=100"
                assert not executor.run(
                    manifest, initial_context={"turn_nonce": nonce, "cart_revision": 1}
                ).success

    def test_checkout_can_atomically_replace_a_stale_draft(self):
        from openjarvis.core.conversation import agent_turn_scope, conversation_scope
        from openjarvis.tools.display import DisplayCartTool

        cart = DisplayCartTool()
        cart._bus = EventBus()
        executor = SkillExecutor(ToolExecutor([cart, EchoTool()]))
        manifest = SkillManifest(
            name="checkout",
            checkout=True,
            accepts_cart_lines=True,
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text":"amount={draft_cart.total}"}',
                ),
            ],
        )
        fresh_lines = [
            {
                "variant_id": "fries",
                "name": "French fries",
                "unit_price": 25_000,
                "quantity": 3,
                "size": "",
                "note": "",
            }
        ]

        with conversation_scope("replace-stale-draft"):
            cart.execute(
                action="add",
                item={
                    "variant_id": "old-coffee",
                    "name": "Old coffee",
                    "unit_price": 35_000,
                    "quantity": 2,
                },
            )
            with agent_turn_scope() as nonce:
                result = executor.run(
                    manifest,
                    initial_context={"turn_nonce": nonce, "cart_lines": fresh_lines},
                )

            assert result.success
            assert result.step_results[-1].content == "amount=75000"
            snapshot = cart.current_snapshot()
            assert snapshot is not None
            assert cart.current_snapshot() == {
                "revision": 2,
                "lines": [
                    {
                        "line_id": snapshot["lines"][0]["line_id"],
                        **fresh_lines[0],
                        "line_total": 75_000,
                    }
                ],
                "total": 75_000,
                "order_note": "",
                "order_type": "",
                "table": "",
                "table_name": "",
            }

    def test_failed_response_assertion_stops_before_next_step(self):
        manifest = SkillManifest(
            name="validated",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text":"{response}"}',
                    output_key="order",
                    assertions=[
                        {"actual": "{order.amount}", "equals": "{amount}"},
                    ],
                ),
                SkillStep(tool_name="upper", arguments_template='{"text":"payment"}'),
            ],
        )
        executor = self._make_executor()
        for response in ('{"amount":99}', "{}", '{"amount":true}'):
            result = executor.run(
                manifest, initial_context={"response": response, "amount": 1}
            )
            assert not result.success
            assert len(result.step_results) == 1
            assert "assertion" in result.step_results[-1].content.lower()
        result = executor.run(
            manifest, initial_context={"response": '{"amount":1}', "amount": 1}
        )
        assert result.success
        assert len(result.step_results) == 2

    def _make_executor(self):
        tools = [EchoTool(), UpperTool()]
        tool_executor = ToolExecutor(tools)
        return SkillExecutor(tool_executor)

    def test_single_step(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="single",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello"}',
                    output_key="result",
                )
            ],
        )
        result = executor.run(manifest)
        assert result.success
        assert result.context.get("result") == "hello"

    def test_multi_step_pipeline(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="pipeline",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello world"}',
                    output_key="echoed",
                ),
                SkillStep(
                    tool_name="upper",
                    arguments_template='{"text": "{echoed}"}',
                    output_key="uppered",
                ),
            ],
        )
        result = executor.run(manifest)
        assert result.success
        assert result.context.get("uppered") == "HELLO WORLD"

    def test_step_failure_stops_pipeline(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="failing",
            steps=[
                SkillStep(tool_name="nonexistent", output_key="x"),
                SkillStep(tool_name="echo", output_key="y"),
            ],
        )
        result = executor.run(manifest)
        assert not result.success
        assert len(result.step_results) == 1

    def test_initial_context(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="with_ctx",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{greeting}"}',
                    output_key="result",
                )
            ],
        )
        result = executor.run(manifest, initial_context={"greeting": "hi"})
        assert result.success
        assert result.context.get("result") == "hi"

    def test_dotted_json_output_placeholder_propagates_order_id(self):
        """A later step can read a scalar from an earlier JSON tool result."""
        executor = self._make_executor()
        manifest = SkillManifest(
            name="order_pipeline",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template=(
                        '{"text": "{\\"order\\": {\\"id\\": \\"ord-123\\"}}"}'
                    ),
                    output_key="step_0",
                ),
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{step_0.order.id}"}',
                    output_key="step_1",
                ),
            ],
        )

        result = executor.run(manifest)

        assert result.success
        assert result.context["step_1"] == "ord-123"

    def test_embedded_dotted_placeholder_escapes_url_value_once(self):
        """A JSON URL string accepts a dotted value that itself has quotes."""
        rendered = SkillExecutor._render_template(
            '{"url": "https://shop/orders/{step_0.result.id}"}',
            {"step_0": '{"result": {"id": "ord-\\"123\\""}}'},
        )

        assert json.loads(rendered) == {
            "url": 'https://shop/orders/ord-"123"',
        }

    def test_template_escapes_quoted_flat_placeholder_values(self):
        """A normal input string containing quotes remains valid JSON for a step."""
        executor = self._make_executor()
        manifest = SkillManifest(
            name="quoted_input",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{message}"}',
                    output_key="result",
                )
            ],
        )

        result = executor.run(manifest, initial_context={"message": 'say "yes"'})

        assert result.success
        assert result.context["result"] == 'say "yes"'

    def test_unresolved_placeholder_stops_before_the_tool_runs(self):
        executor = self._make_executor()
        manifest = SkillManifest(
            name="stale-learned-read",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{step_0.items.0.name}"}',
                )
            ],
        )

        result = executor.run(manifest)

        assert result.success is False
        assert len(result.step_results) == 1
        assert "Unresolved placeholder" in result.step_results[0].content

    def test_events_emitted(self):
        bus = EventBus(record_history=True)
        tools = [EchoTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor, bus=bus)

        manifest = SkillManifest(
            name="evented",
            steps=[SkillStep(tool_name="echo", arguments_template='{"text": "x"}')],
        )
        executor.run(manifest)
        event_types = {e.event_type for e in bus.history}
        assert EventType.SKILL_EXECUTE_START in event_types
        assert EventType.SKILL_EXECUTE_END in event_types


class TestSkillExecutorCapabilities:
    def _manifest(self):
        return SkillManifest(
            name="capskill",
            required_capabilities=["network:fetch"],
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello"}',
                    output_key="result",
                )
            ],
        )

    def test_no_policy_runs_capability_skills(self):
        """Default construction (no allowed_capabilities) must not enforce —
        this is the pre-enforcement behavior every manager.py call site relies on."""
        executor = SkillExecutor(ToolExecutor([EchoTool()]))
        result = executor.run(self._manifest())
        assert result.success
        assert result.context.get("result") == "hello"

    def test_policy_blocks_missing_capability(self):
        executor = SkillExecutor(ToolExecutor([EchoTool()]), allowed_capabilities=set())
        result = executor.run(self._manifest())
        assert not result.success
        assert len(result.step_results) == 1
        assert "Blocked" in result.step_results[0].content
        assert "network:fetch" in result.step_results[0].content

    def test_policy_allows_granted_capability(self):
        executor = SkillExecutor(
            ToolExecutor([EchoTool()]),
            allowed_capabilities={"network:fetch"},
        )
        result = executor.run(self._manifest())
        assert result.success
        assert result.context.get("result") == "hello"

    def test_blocked_run_publishes_events(self):
        bus = EventBus(record_history=True)
        executor = SkillExecutor(
            ToolExecutor([EchoTool()]), bus=bus, allowed_capabilities=set()
        )
        executor.run(self._manifest())
        event_types = {e.event_type for e in bus.history}
        assert EventType.SKILL_EXECUTE_START in event_types
        assert EventType.SKILL_EXECUTE_END in event_types


class TestSkillStepExtended:
    def test_step_with_skill_name(self):
        step = SkillStep(skill_name="summarize", output_key="result")
        assert step.skill_name == "summarize"
        assert step.tool_name == ""

    def test_step_either_tool_or_skill(self):
        step_tool = SkillStep(tool_name="web_search")
        step_skill = SkillStep(skill_name="summarize")
        assert step_tool.tool_name == "web_search"
        assert step_tool.skill_name == ""
        assert step_skill.skill_name == "summarize"
        assert step_skill.tool_name == ""


class TestSkillManifestExtended:
    def test_manifest_with_tags_and_depends(self):
        manifest = SkillManifest(
            name="test",
            tags=["research"],
            depends=["summarize"],
        )
        assert manifest.tags == ["research"]
        assert manifest.depends == ["summarize"]

    def test_manifest_with_invocation_flags(self):
        manifest = SkillManifest(
            name="test",
            user_invocable=False,
            disable_model_invocation=True,
        )
        assert not manifest.user_invocable
        assert manifest.disable_model_invocation

    def test_manifest_with_markdown_content(self):
        manifest = SkillManifest(
            name="test",
            markdown_content="When asked to research...",
        )
        assert manifest.markdown_content == "When asked to research..."

    def test_manifest_bytes_includes_new_fields(self):
        manifest = SkillManifest(
            name="test",
            tags=["a"],
            depends=["b"],
            steps=[],
        )
        data = manifest.manifest_bytes()
        assert b"tags" in data
        assert b"depends" in data


class TestSkillExecutorSubSkills:
    def test_sub_skill_delegation(self):
        """Executor delegates skill_name steps to a skill resolver."""
        tools = [EchoTool(), UpperTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor)

        child_manifest = SkillManifest(
            name="upper_skill",
            steps=[
                SkillStep(
                    tool_name="upper",
                    arguments_template='{"text": "{text}"}',
                    output_key="uppered",
                ),
            ],
        )

        def resolve_skill(name, context):
            from openjarvis.skills.executor import SkillResult

            if name == "upper_skill":
                return executor.run(child_manifest, initial_context=context)
            return SkillResult(skill_name=name, success=False)

        executor.set_skill_resolver(resolve_skill)

        parent_manifest = SkillManifest(
            name="parent",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "hello"}',
                    output_key="echoed",
                ),
                SkillStep(
                    skill_name="upper_skill",
                    arguments_template='{"text": "{echoed}"}',
                    output_key="result",
                ),
            ],
        )
        result = executor.run(parent_manifest)
        assert result.success
        assert result.context.get("result") == "HELLO"

    def test_sub_skill_failure_stops_pipeline(self):
        tools = [EchoTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor)

        def resolve_skill(name, context):
            from openjarvis.skills.executor import SkillResult

            return SkillResult(skill_name=name, success=False)

        executor.set_skill_resolver(resolve_skill)

        manifest = SkillManifest(
            name="parent",
            steps=[
                SkillStep(skill_name="nonexistent", output_key="x"),
                SkillStep(tool_name="echo", output_key="y"),
            ],
        )
        result = executor.run(manifest)
        assert not result.success
        assert len(result.step_results) == 1


class TestSkillTool:
    def test_skill_as_tool(self):
        from openjarvis.skills.tool_adapter import SkillTool

        tools = [EchoTool()]
        tool_executor = ToolExecutor(tools)
        executor = SkillExecutor(tool_executor)
        manifest = SkillManifest(
            name="tool_skill",
            description="A skill exposed as a tool",
            steps=[
                SkillStep(
                    tool_name="echo",
                    arguments_template='{"text": "{input}"}',
                    output_key="result",
                )
            ],
        )
        skill_tool = SkillTool(manifest, executor)
        assert skill_tool.spec.name == "skill_tool_skill"
        result = skill_tool.execute(input="hello")
        assert result.success
