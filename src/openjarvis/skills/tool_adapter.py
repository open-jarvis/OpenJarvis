"""SkillTool — wraps a skill as a tool that agents can invoke."""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from openjarvis.core.types import ToolResult
from openjarvis.skills.executor import SkillExecutor
from openjarvis.skills.types import SkillManifest
from openjarvis.tools._stubs import BaseTool, ToolSpec

_PLACEHOLDER_RE = re.compile(r"\{(\w+(?:\.\w+)*)(?:\|(urlencode))?\}")


def _validate_parameters(
    schema: Dict[str, Any], value: Any, path: str = "arguments"
) -> str:
    schema_type = schema.get("type")
    type_matches = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float))
        and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    if schema_type in type_matches and not type_matches[schema_type](value):
        return f"{path} must be {schema_type}"

    if "enum" in schema and value not in schema["enum"]:
        return f"{path} is not an allowed enum value"

    if schema_type == "object":
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                return f"{path}.{name} is required"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                return f"{path}.{sorted(extra)[0]} is not declared"
        for name, child_schema in properties.items():
            if name in value:
                error = _validate_parameters(
                    child_schema, value[name], f"{path}.{name}"
                )
                if error:
                    return error

    if schema_type == "array":
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                error = _validate_parameters(item_schema, item, f"{path}[{index}]")
                if error:
                    return error

    if schema_type == "string" and len(value) < schema.get("minLength", 0):
        return f"{path} is shorter than minLength"
    if "minimum" in schema and value < schema["minimum"]:
        return f"{path} is below minimum"
    if "maximum" in schema and value > schema["maximum"]:
        return f"{path} is above maximum"
    return ""


class SkillTool(BaseTool):
    """Wraps a SkillManifest as a BaseTool that agents can invoke.

    Follows the same adapter pattern as MCPToolAdapter.

    Parameters
    ----------
    manifest:
        The skill manifest to wrap.
    executor:
        A :class:`SkillExecutor` used to run the skill pipeline.
    skill_manager:
        Optional skill manager (reserved for sub-skill delegation).
    """

    tool_id: str

    def __init__(
        self,
        manifest: SkillManifest,
        executor: SkillExecutor,
        *,
        skill_manager: Optional[Any] = None,
    ) -> None:
        self._manifest = manifest
        self._executor = executor
        self._skill_manager = skill_manager
        self.tool_id = f"skill_{manifest.name}"
        self._parameters = self._build_parameters()

    # ------------------------------------------------------------------
    # Parameter extraction
    # ------------------------------------------------------------------

    def _build_parameters(self) -> Dict[str, Any]:
        """Auto-extract input parameters from the manifest.

        For pipeline skills, scan each step's ``arguments_template`` for
        ``{placeholder}`` patterns.  Subtract the ``output_key`` values
        produced by *prior* steps so only externally-supplied parameters
        are exposed.

        For instruction-only skills (no steps), expose a single optional
        ``task`` parameter.
        """
        if self._manifest.input_schema:
            return copy.deepcopy(self._manifest.input_schema)

        if not self._manifest.steps:
            # Instruction-only / markdown-only skill
            return {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Optional task description or context.",
                    }
                },
            }

        produced: Set[str] = {"today"}
        if self._manifest.checkout:
            produced.add("draft_cart")
        input_params: List[str] = []
        seen: Set[str] = set()

        for step in self._manifest.steps:
            # Find all {placeholder} tokens in this step's template
            placeholders = _PLACEHOLDER_RE.findall(step.arguments_template)
            aliases = set(re.findall(r'"as"\s*:\s*"(\w+)"', step.arguments_template))
            for ph, _filter in placeholders:
                root = ph.split(".", 1)[0]
                if root not in produced and root not in seen and root not in aliases:
                    input_params.append(root)
                    seen.add(root)

            # After processing this step, its output_key becomes available
            # for subsequent steps and should NOT be surfaced as an input
            if step.output_key:
                produced.add(step.output_key)

        properties: Dict[str, Any] = {}
        for param in input_params:
            properties[param] = {
                "type": "string",
                "description": f"Input value for '{param}'.",
            }

        if self._manifest.checkout:
            properties["turn_nonce"] = {"type": "string"}
            properties["cart_revision"] = {"type": "integer"}
            if self._manifest.accepts_cart_lines:
                properties["cart_lines"] = {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "variant_id": {"type": "string"},
                            "name": {"type": "string"},
                            "unit_price": {"type": "integer"},
                            "quantity": {"type": "integer", "minimum": 1},
                            "size": {"type": "string"},
                            "note": {"type": "string"},
                        },
                        "required": [
                            "variant_id",
                            "name",
                            "unit_price",
                            "quantity",
                        ],
                    },
                }

        parameters = {
            "type": "object",
            "properties": properties,
        }
        if self._manifest.checkout:
            parameters["required"] = [
                name
                for name in properties
                if name not in {"cart_revision", "cart_lines"}
            ]
            if self._manifest.accepts_cart_lines:
                parameters["oneOf"] = [
                    {"required": ["cart_revision"]},
                    {"required": ["cart_lines"]},
                ]
            else:
                parameters["required"].append("cart_revision")
        return parameters

    def agent_context(self) -> Dict[str, Any]:
        if not self._manifest.checkout:
            steps = self._manifest.steps
            if not any(step.tool_name == "display_menu" for step in steps):
                return {}
            get_tool = getattr(self._executor._tool_executor, "get_tool", None)
            menu = get_tool("display_menu") if callable(get_tool) else None
            provider = getattr(menu, "agent_context", None)
            return provider() if callable(provider) else {}
        cart = self._executor._tool_executor.get_tool("display_cart")
        context = cart.agent_context() if cart is not None else {}
        if self._manifest.accepts_cart_lines and not context:
            return {"draft_cart": None}
        return context

    # ------------------------------------------------------------------
    # Result metadata
    # ------------------------------------------------------------------

    def _build_result_metadata(self, *, steps_run: int) -> Dict[str, Any]:
        """Build the metadata dict attached to ToolResult.

        Includes the skill name, source provenance, and kind so downstream
        consumers (TraceCollector, SkillOptimizer) can bucket invocations.
        """
        oj_meta = self._manifest.metadata.get("openjarvis", {}) or {}
        source = oj_meta.get("source", "user")
        kind = "executable" if self._manifest.steps else "instructional"
        return {
            "skill": self._manifest.name,
            "skill_source": source,
            "skill_kind": kind,
            "steps": steps_run,
        }

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=f"skill_{self._manifest.name}",
            description=self._manifest.description or f"Skill: {self._manifest.name}",
            parameters=self._parameters,
            category="skill",
            required_capabilities=self._manifest.required_capabilities,
        )

    def execute(self, **params: Any) -> ToolResult:
        """Execute the skill.

        If the manifest has pipeline steps, run them via the executor and
        collect the last step's output.  If ``markdown_content`` is present,
        append it to the content.  Returns a combined :class:`ToolResult`.
        """
        tool_name = self.spec.name
        error = _validate_parameters(self._parameters, params)
        if error:
            return ToolResult(
                tool_name=tool_name,
                content=f"invalid_skill_arguments: {error}",
                success=False,
                metadata=self._build_result_metadata(steps_run=0),
            )
        content_parts: List[str] = []
        display_metadata: Dict[str, Any] = {}

        if self._manifest.steps:
            # Build initial context from all supplied params
            initial_ctx: Dict[str, Any] = {
                **params,
                "today": datetime.now().astimezone().date().isoformat(),
            }

            result = self._executor.run(self._manifest, initial_context=initial_ctx)

            if not result.success:
                # Propagate failure immediately
                error_content = (
                    result.step_results[-1].content
                    if result.step_results
                    else "Pipeline failed with no step results."
                )
                return ToolResult(
                    tool_name=tool_name,
                    content=error_content,
                    success=False,
                    metadata=self._build_result_metadata(
                        steps_run=len(result.step_results)
                    ),
                )

            # Use the last step's output as the primary content
            if result.step_results:
                last_step = result.step_results[-1]
                if last_step.tool_name.startswith("display_") or last_step.metadata.get(
                    "completed_display"
                ):
                    display_metadata = {
                        key: last_step.metadata[key]
                        for key in (
                            "customer_message",
                            "completed_display",
                            "continue_agent",
                            "result_complete",
                            "projected_count",
                            "published_count",
                        )
                        if key in last_step.metadata
                    }
                    display_metadata["completed_display"] = True
                    if (
                        "customer_message" not in display_metadata
                        and last_step.tool_name != "display_menu"
                    ):
                        message = params.get("customer_message")
                        if isinstance(message, str) and message.strip():
                            display_metadata["customer_message"] = message.strip()
                last_output = (
                    result.context.get(
                        # Prefer the keyed output if available
                        self._manifest.steps[-1].output_key,
                        last_step.content,
                    )
                    if self._manifest.steps[-1].output_key
                    else last_step.content
                )
                content_parts.append(str(last_output))

        # Append markdown content if present (hybrid or instruction-only)
        if self._manifest.markdown_content:
            content_parts.append(self._manifest.markdown_content)

        combined = "\n\n".join(filter(None, content_parts))

        return ToolResult(
            tool_name=tool_name,
            content=combined,
            success=True,
            metadata={
                **self._build_result_metadata(steps_run=len(self._manifest.steps)),
                **display_metadata,
            },
        )


__all__ = ["SkillTool"]
