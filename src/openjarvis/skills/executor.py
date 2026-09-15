"""SkillExecutor — runs skill steps sequentially through ToolExecutor."""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.skills.security import validate_capabilities
from openjarvis.skills.types import SkillManifest
from openjarvis.tools._stubs import ToolExecutor


@dataclass(slots=True)
class SkillResult:
    skill_name: str = ""
    success: bool = True
    step_results: List[ToolResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


# Resolver callback: given a skill name and the current context, returns a SkillResult.
SkillResolver = Callable[[str, Dict[str, Any]], SkillResult]
_MISSING = object()


def _url_origin(url: object) -> str:
    if not isinstance(url, str):
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}{f':{port}' if port is not None else ''}"


class SkillExecutor:
    """Execute a skill manifest step-by-step.

    Each step's arguments_template supports ``{key}`` placeholders
    that are resolved from the context dict (populated by prior step outputs).
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        *,
        bus: Optional[EventBus] = None,
        allowed_capabilities: Optional[Set[str]] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._bus = bus
        self._skill_resolver: Optional[SkillResolver] = None
        # None means "no capability policy" — every skill runs, matching the
        # behavior before capability enforcement existed. Pass a set (even an
        # empty one) to enforce: skills whose required_capabilities are not a
        # subset of it are blocked before any step runs.
        self._allowed_capabilities: Optional[Set[str]] = allowed_capabilities

    def set_skill_resolver(self, resolver: SkillResolver) -> None:
        """Register a callback used to delegate ``skill_name`` steps."""
        self._skill_resolver = resolver

    def run(
        self,
        manifest: SkillManifest,
        *,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """Execute all steps, reserving a checkout draft before any side effect."""
        if not manifest.checkout:
            return self._run_steps(manifest, initial_context=initial_context)
        ctx = dict(initial_context or {})
        cart = self._tool_executor.get_tool("display_cart")
        try:
            if cart is None or not hasattr(cart, "begin_checkout"):
                raise ValueError("checkout requires the runtime draft cart")
            ctx["draft_cart"] = cart.begin_checkout(
                ctx.get("turn_nonce", ""),
                ctx.get("cart_revision"),
                manifest.manifest_bytes(),
                replacement_lines=(
                    ctx.get("cart_lines") if manifest.accepts_cart_lines else None
                ),
                order_type=ctx.get("order_type"),
                order_note=ctx.get("order_note"),
                table=ctx.get("table"),
            )
        except ValueError as exc:
            return SkillResult(
                skill_name=manifest.name,
                success=False,
                step_results=[
                    ToolResult(
                        tool_name=manifest.name, content=str(exc), success=False
                    ),
                ],
            )
        try:
            return self._run_steps(manifest, initial_context=ctx)
        finally:
            cart.end_checkout()

    def _run_steps(
        self,
        manifest: SkillManifest,
        *,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        """Run dependent tool calls in order, validating each response locally."""
        missing = (
            validate_capabilities(manifest, self._allowed_capabilities)
            if self._allowed_capabilities is not None
            else []
        )
        if missing:
            if self._bus:
                self._bus.publish(
                    EventType.SKILL_EXECUTE_START,
                    {"skill": manifest.name, "steps": len(manifest.steps)},
                )
                self._bus.publish(
                    EventType.SKILL_EXECUTE_END,
                    {"skill": manifest.name, "success": False},
                )
            return SkillResult(
                skill_name=manifest.name,
                success=False,
                step_results=[
                    ToolResult(
                        tool_name=manifest.name,
                        content=(
                            f"Blocked: skill '{manifest.name}' requires "
                            f"capabilities {missing} that were not granted "
                            "for this session."
                        ),
                        success=False,
                    )
                ],
                context=dict(initial_context or {}),
            )

        ctx: Dict[str, Any] = dict(initial_context or {})
        all_results: List[ToolResult] = []
        openjarvis_metadata = manifest.metadata.get("openjarvis", {})
        recipe = (
            openjarvis_metadata.get("request_recipe")
            if isinstance(openjarvis_metadata, dict)
            else None
        )

        if self._bus:
            self._bus.publish(
                EventType.SKILL_EXECUTE_START,
                {"skill": manifest.name, "steps": len(manifest.steps)},
            )

        for i, step in enumerate(manifest.steps):
            step_id = step.tool_name or step.skill_name

            if manifest.checkout:
                from openjarvis.core.conversation import turn_nonce_is_active

                if not turn_nonce_is_active(ctx.get("turn_nonce", "")):
                    all_results.append(
                        ToolResult(
                            tool_name=step_id,
                            content="checkout turn expired",
                            success=False,
                        )
                    )
                    break

            # Render template
            try:
                rendered = self._render_template(step.arguments_template, ctx)
            except Exception as exc:
                result = ToolResult(
                    tool_name=step_id,
                    content=f"Template rendering error: {exc}",
                    success=False,
                )
                all_results.append(result)
                break

            if recipe is not None and step.tool_name == "http_request":
                if not self._request_matches_recipe(
                    step.arguments_template, rendered, recipe
                ):
                    all_results.append(
                        ToolResult(
                            tool_name=step_id,
                            content="recipe_stale",
                            success=False,
                        )
                    )
                    break

            if step.skill_name:
                # Delegate to sub-skill resolver
                result = self._run_sub_skill(
                    step.skill_name, rendered, ctx, manifest.name, i
                )
            else:
                # Execute via tool executor
                tool_call = ToolCall(
                    id=f"skill_{manifest.name}_{i}",
                    name=step.tool_name,
                    arguments=rendered,
                )
                result = self._tool_executor.execute(tool_call)

            if recipe is not None and step.tool_name == "http_request":
                recipe_error = self._recipe_response_error(result, recipe)
                if recipe_error:
                    result = ToolResult(
                        tool_name=step_id,
                        content=recipe_error,
                        success=False,
                        metadata=dict(result.metadata),
                    )

            all_results.append(result)

            if not result.success:
                break

            # Store output in context
            if step.output_key:
                ctx[step.output_key] = result.content

            try:
                self._validate_assertions(step.assertions, ctx)
            except (ValueError, TypeError) as exc:
                all_results[-1] = ToolResult(
                    tool_name=step_id,
                    content=f"Response assertion failed at step {i}: {exc}",
                    success=False,
                )
                break

        success = all(r.success for r in all_results)

        if self._bus:
            self._bus.publish(
                EventType.SKILL_EXECUTE_END,
                {"skill": manifest.name, "success": success},
            )

        return SkillResult(
            skill_name=manifest.name,
            success=success,
            step_results=all_results,
            context=ctx,
        )

    @staticmethod
    def _request_matches_recipe(
        arguments_template: str, rendered: str, recipe: object
    ) -> bool:
        if not isinstance(recipe, dict):
            return False
        try:
            template_request = json.loads(arguments_template)
            request = json.loads(rendered)
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(template_request, dict) or not isinstance(request, dict):
            return False

        template_url = template_request.get("url")
        template_method = template_request.get("method")
        if not isinstance(template_url, str) or not isinstance(template_method, str):
            return False
        template_parts = urllib.parse.urlsplit(template_url)
        if (
            not template_parts.scheme
            or not template_parts.netloc
            or "{" in template_parts.scheme
            or "}" in template_parts.scheme
            or "{" in template_parts.netloc
            or "}" in template_parts.netloc
            or "{" in template_method
            or "}" in template_method
        ):
            return False

        method = request.get("method")
        if not isinstance(method, str):
            return False
        method = method.upper()
        return (
            method in {"GET", "HEAD"}
            and method == recipe.get("method")
            and _url_origin(request.get("url")) == _url_origin(recipe.get("origin"))
        )

    @staticmethod
    def _recipe_response_error(result: ToolResult, recipe: object) -> str:
        if not result.success or not isinstance(recipe, dict):
            return "source_unavailable"
        metadata = result.metadata
        status_code = metadata.get("status_code")
        if (
            not isinstance(status_code, int)
            or isinstance(status_code, bool)
            or not 200 <= status_code < 300
        ):
            return "source_unavailable"
        if metadata.get("truncated") is not False:
            return "source_unavailable"

        allowed_types = recipe.get("allowed_content_types", ["application/json"])
        content_type = metadata.get("content_type")
        if (
            not isinstance(allowed_types, list)
            or not all(isinstance(item, str) for item in allowed_types)
            or not isinstance(content_type, str)
            or not any(content_type.startswith(item) for item in allowed_types)
        ):
            return "recipe_stale"
        if _url_origin(metadata.get("final_url")) != _url_origin(recipe.get("origin")):
            return "recipe_stale"
        try:
            response_body = json.loads(result.content)
        except (json.JSONDecodeError, TypeError):
            return "recipe_stale"
        required_paths = recipe.get("required_paths_json")
        if required_paths is not None:
            try:
                fingerprints = json.loads(required_paths)
            except (json.JSONDecodeError, TypeError):
                return "recipe_stale"
            if not isinstance(fingerprints, list):
                return "recipe_stale"
            for fingerprint in fingerprints:
                if (
                    not isinstance(fingerprint, dict)
                    or set(fingerprint) != {"path", "type"}
                    or not isinstance(fingerprint["path"], str)
                    or not isinstance(fingerprint["type"], str)
                ):
                    return "recipe_stale"
                actual = (
                    SkillExecutor._resolve_placeholder(
                        fingerprint["path"], response_body
                    )
                    if isinstance(response_body, dict)
                    else _MISSING
                )
                if actual is _MISSING or not SkillExecutor._matches_json_type(
                    actual, fingerprint["type"]
                ):
                    return "recipe_stale"
        return ""

    @staticmethod
    def _matches_json_type(value: Any, expected: str) -> bool:
        checks = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int)
            and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float))
            and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        return expected in checks and checks[expected](value)

    def _run_sub_skill(
        self,
        skill_name: str,
        rendered_args: str,
        parent_ctx: Dict[str, Any],
        parent_skill: str,
        step_index: int,
    ) -> ToolResult:
        """Invoke the skill resolver and convert its result to a ToolResult."""
        if self._skill_resolver is None:
            return ToolResult(
                tool_name=skill_name,
                content=f"No skill resolver registered for sub-skill '{skill_name}'",
                success=False,
            )

        # Parse rendered args and merge into a copy of the parent context
        try:
            args: Dict[str, Any] = json.loads(rendered_args)
        except json.JSONDecodeError:
            args = {}

        child_ctx = {**parent_ctx, **args}

        sub_result: SkillResult = self._skill_resolver(skill_name, child_ctx)

        # Expose the final context value under the first output_key, or the
        # last step's content, as the synthetic "content" of this ToolResult.
        content: Any = ""
        if sub_result.context:
            # Return the last stored value from the child's context that is
            # not already in the parent context (i.e. the output of the sub-skill).
            new_keys = [k for k in sub_result.context if k not in parent_ctx]
            if new_keys:
                content = sub_result.context[new_keys[-1]]
            else:
                content = (
                    list(sub_result.context.values())[-1] if sub_result.context else ""
                )
        elif sub_result.step_results:
            content = sub_result.step_results[-1].content

        return ToolResult(
            tool_name=skill_name,
            content=content,
            success=sub_result.success,
            metadata=(
                dict(sub_result.step_results[-1].metadata)
                if sub_result.success and sub_result.step_results
                else {}
            ),
        )

    @staticmethod
    def _validate_assertions(assertions: Any, ctx: Dict[str, Any]) -> None:
        """Evaluate a small data-only contract before dispatching the next step."""
        if not isinstance(assertions, list):
            raise ValueError("assertions must be a list")
        for assertion in assertions:
            if not isinstance(assertion, dict):
                raise ValueError("assertion requires actual and equals")
            if set(assertion) == {"actual", "all_unique_non_empty"}:
                if assertion["all_unique_non_empty"] is not True:
                    raise ValueError("all_unique_non_empty must be true")
                actual = SkillExecutor._render_json_value(assertion["actual"], ctx)
                if not isinstance(actual, list):
                    raise ValueError("all_unique_non_empty requires an array")
                identities = [json.dumps(item, sort_keys=True) for item in actual]
                if any(item in {None, ""} for item in actual) or len(
                    identities
                ) != len(set(identities)):
                    raise ValueError("values must be unique non-empty identities")
                continue
            if set(assertion) != {"actual", "equals"}:
                raise ValueError("assertion requires actual and equals")
            actual = SkillExecutor._render_json_value(assertion["actual"], ctx)
            expected = SkillExecutor._render_json_value(assertion["equals"], ctx)
            # JSON comparison distinguishes booleans from numbers, including
            # within nested objects; never include merchant values in errors.
            if json.dumps(actual, sort_keys=True) != json.dumps(
                expected, sort_keys=True
            ):
                raise ValueError("values do not match")

    @staticmethod
    def _render_template(template: str, ctx: Dict[str, Any]) -> str:
        """Render simple or dotted placeholders while preserving JSON syntax."""
        try:
            parsed = json.loads(template)
        except json.JSONDecodeError:
            return SkillExecutor._render_legacy_template(template, ctx)
        rendered = SkillExecutor._render_json_value(parsed, ctx)
        return json.dumps(rendered, ensure_ascii=False)

    @staticmethod
    def _render_json_value(value: Any, ctx: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            if set(value) == {"$json"}:
                return json.dumps(
                    SkillExecutor._render_json_value(value["$json"], ctx),
                    ensure_ascii=False,
                )
            if "$coalesce" in value:
                operands = value["$coalesce"]
                if set(value) != {"$coalesce"} or not isinstance(
                    operands, list
                ) or not operands:
                    raise ValueError("invalid coalesce expression")
                for operand in operands:
                    try:
                        resolved = SkillExecutor._render_json_value(operand, ctx)
                    except ValueError as exc:
                        if str(exc).startswith("Unresolved placeholder:"):
                            continue
                        raise
                    if resolved is not None:
                        return resolved
                return None
            if "$expect_one" in value:
                if set(value) != {"$expect_one"}:
                    raise ValueError("invalid expect_one expression")
                rows = SkillExecutor._render_json_value(value["$expect_one"], ctx)
                if not isinstance(rows, list) or len(rows) != 1:
                    raise ValueError("expect_one requires exactly one result")
                return rows[0]
            if "$map" in value:
                if set(value) != {"$map", "as", "value"} or not isinstance(
                    value["as"], str
                ):
                    raise ValueError("invalid map expression")
                rows = SkillExecutor._render_json_value(value["$map"], ctx)
                if not isinstance(rows, list):
                    raise ValueError("map source must be an array")
                return [
                    SkillExecutor._render_json_value(
                        value["value"], {**ctx, value["as"]: row}
                    )
                    for row in rows
                ]
            if "$filter" in value:
                if set(value) != {"$filter", "as", "where"} or not isinstance(
                    value["as"], str
                ):
                    raise ValueError("invalid filter expression")
                rows = SkillExecutor._render_json_value(value["$filter"], ctx)
                if not isinstance(rows, list):
                    raise ValueError("filter source must be an array")
                return [
                    row
                    for row in rows
                    if SkillExecutor._evaluate_predicate(
                        value["where"], {**ctx, value["as"]: row}
                    )
                ]
            return {
                key: SkillExecutor._render_json_value(child, ctx)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [SkillExecutor._render_json_value(child, ctx) for child in value]
        if not isinstance(value, str):
            return value

        full_placeholder = re.fullmatch(
            r"\{(\w+(?:\.\w+)*)(?:\|(\w+))?\}", value
        )
        if full_placeholder:
            resolved = SkillExecutor._resolve_placeholder(
                full_placeholder.group(1), ctx
            )
            if resolved is _MISSING:
                raise ValueError(f"Unresolved placeholder: {full_placeholder.group(1)}")
            filter_name = full_placeholder.group(2)
            if filter_name is None:
                return resolved
            if filter_name != "urlencode":
                raise ValueError(f"Unknown template filter: {filter_name}")
            return urllib.parse.quote(str(resolved), safe="")

        def _replace(match: re.Match) -> str:
            resolved = SkillExecutor._resolve_placeholder(match.group(1), ctx)
            if resolved is _MISSING:
                raise ValueError(f"Unresolved placeholder: {match.group(1)}")
            filter_name = match.group(2)
            if filter_name is not None:
                if filter_name != "urlencode":
                    raise ValueError(f"Unknown template filter: {filter_name}")
                return urllib.parse.quote(str(resolved), safe="")
            if isinstance(resolved, str):
                return resolved
            return json.dumps(resolved, ensure_ascii=False)

        return re.sub(
            r"\{(\w+(?:\.\w+)*)(?:\|(\w+))?\}", _replace, value
        )

    @staticmethod
    def _evaluate_predicate(predicate: Any, ctx: Dict[str, Any]) -> bool:
        if not isinstance(predicate, dict) or len(predicate) != 1:
            raise ValueError("predicate must contain exactly one operator")
        operator, operands = next(iter(predicate.items()))
        if operator in {"all", "any"}:
            if not isinstance(operands, list) or not operands:
                raise ValueError(f"{operator} predicate has invalid arity")
            results = [
                SkillExecutor._evaluate_predicate(child, ctx) for child in operands
            ]
            return all(results) if operator == "all" else any(results)
        if operator not in {"contains_folded", "gte", "lte"}:
            raise ValueError(f"unsupported predicate operator: {operator}")
        if not isinstance(operands, list) or len(operands) != 2:
            raise ValueError(f"{operator} predicate has invalid arity")

        resolved = []
        for operand in operands:
            try:
                resolved.append(SkillExecutor._render_json_value(operand, ctx))
            except ValueError as exc:
                if str(exc).startswith("Unresolved placeholder:"):
                    return False
                raise
        left, right = resolved
        if operator == "contains_folded":
            if not isinstance(left, str) or not isinstance(right, str):
                return False
            def normalize(text: str) -> str:
                return " ".join(unicodedata.normalize("NFKC", text).casefold().split())

            return normalize(right) in normalize(left)

        if (
            not isinstance(left, (int, float))
            or isinstance(left, bool)
            or not isinstance(right, (int, float))
            or isinstance(right, bool)
        ):
            return False
        return left >= right if operator == "gte" else left <= right

    @staticmethod
    def _render_legacy_template(template: str, ctx: Dict[str, Any]) -> str:
        """Keep legacy placeholder behavior for non-JSON templates."""

        def _replace(match: re.Match) -> str:
            value = SkillExecutor._resolve_placeholder(match.group(1), ctx)
            if value is _MISSING:
                raise ValueError(f"Unresolved placeholder: {match.group(1)}")
            filter_name = match.group(2)
            if filter_name is not None:
                if filter_name != "urlencode":
                    raise ValueError(f"Unknown template filter: {filter_name}")
                return urllib.parse.quote(str(value), safe="")
            rendered = json.dumps(value, ensure_ascii=False)
            inside_json_string = (
                match.start() > 0
                and match.end() < len(template)
                and template[match.start() - 1] == '"'
                and template[match.end()] == '"'
            )
            if isinstance(value, str) and inside_json_string:
                return rendered[1:-1]
            return rendered

        return re.sub(
            r"\{(\w+(?:\.\w+)*)(?:\|(\w+))?\}", _replace, template
        )

    @staticmethod
    def _resolve_placeholder(key: str, ctx: Dict[str, Any]) -> Any:
        root, *path = key.split(".")
        value = ctx.get(root, _MISSING)
        if value is _MISSING:
            return _MISSING
        if path and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return _MISSING
        for segment in path:
            if isinstance(value, dict) and segment in value:
                value = value[segment]
            elif (
                isinstance(value, list)
                and segment.isdigit()
                and int(segment) < len(value)
            ):
                value = value[int(segment)]
            else:
                return _MISSING
        return value


__all__ = ["SkillExecutor", "SkillResolver", "SkillResult"]
