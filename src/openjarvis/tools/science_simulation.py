"""Standalone science calculation tool — for voice/chat follow-ups like

"simule essa mistura" without re-running the full Science Lab pipeline.
"""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.science_lab import calculations
from openjarvis.science_lab.safety_classifier import classify
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("science_simulate")
class ScienceSimulateTool(BaseTool):
    """Run a single named theoretical calculation from ``science_lab.calculations``."""

    tool_id = "science_simulate"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="science_simulate",
            description=(
                "Run a theoretical materials-science calculation (density, "
                "concentration, viscosity mixture, etc.) with explicit numeric "
                "inputs. Always tags the result with its basis (VALOR CALCULADO "
                "or ESTIMATIVA)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "quantity": {
                        "type": "string",
                        "enum": sorted(calculations.CALCULATIONS.keys()),
                        "description": "Which calculation to run.",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Numeric keyword inputs for the calculation.",
                    },
                },
                "required": ["quantity", "inputs"],
            },
            category="science",
        )

    def execute(self, **params: Any) -> ToolResult:
        # Defense-in-depth: re-check for dangerous operational content even
        # on a standalone simulation call (the primary gate is in
        # ScienceLabAgent.run(), before hypothesis generation is even
        # reached; this catches a benign-looking objective followed by an
        # operational follow-up call directly against this tool).
        quantity = params.get("quantity", "")
        inputs = params.get("inputs", {}) or {}
        classification = classify(f"{quantity} {inputs}")
        if classification.should_refuse:
            return ToolResult(
                tool_name="science_simulate",
                content=classification.refusal_text,
                success=False,
            )
        if not quantity:
            return ToolResult(
                tool_name="science_simulate",
                content="No quantity provided.",
                success=False,
            )
        try:
            result = calculations.calculate(quantity, **inputs)
        except (ValueError, TypeError) as exc:
            return ToolResult(
                tool_name="science_simulate", content=f"Error: {exc}", success=False
            )
        content = (
            f"{result.quantity} = {result.value:.4g} {result.unit} [{result.basis}]"
        )
        return ToolResult(
            tool_name="science_simulate",
            content=content,
            success=True,
            metadata=result.to_dict(),
        )


__all__ = ["ScienceSimulateTool"]
