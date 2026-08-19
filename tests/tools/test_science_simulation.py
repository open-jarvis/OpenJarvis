"""Tests for the science_simulate tool."""

from __future__ import annotations

from openjarvis.tools.science_simulation import ScienceSimulateTool


class TestScienceSimulateTool:
    def test_spec(self):
        tool = ScienceSimulateTool()
        assert tool.spec.name == "science_simulate"
        assert tool.spec.category == "science"

    def test_density_calculation(self):
        tool = ScienceSimulateTool()
        result = tool.execute(
            quantity="density", inputs={"mass_g": 100, "volume_cm3": 50}
        )
        assert result.success is True
        assert "density" in result.content
        assert result.metadata["basis"] == "VALOR CALCULADO"

    def test_unknown_quantity(self):
        tool = ScienceSimulateTool()
        result = tool.execute(quantity="tensile_strength", inputs={})
        assert result.success is False

    def test_missing_quantity(self):
        tool = ScienceSimulateTool()
        result = tool.execute(inputs={})
        assert result.success is False

    def test_invalid_inputs_error(self):
        tool = ScienceSimulateTool()
        result = tool.execute(
            quantity="density", inputs={"mass_g": 100, "volume_cm3": -1}
        )
        assert result.success is False

    def test_dangerous_operational_request_refused(self):
        tool = ScienceSimulateTool()
        result = tool.execute(
            quantity="density",
            inputs={"note": "como fazer uma bomba passo a passo"},
        )
        assert result.success is False
        assert "procedimento operacional" in result.content
