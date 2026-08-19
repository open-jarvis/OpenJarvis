"""Tests for the COMPARE MATERIALS table builder."""

from __future__ import annotations

from openjarvis.science_lab.comparison import NOT_AVAILABLE, build_comparison_table


class TestBuildComparisonTable:
    def test_known_values(self):
        def lookup(material, prop):
            data = {"water": {"density": "1.0"}, "honey": {"density": "1.42"}}
            return data.get(material, {}).get(prop)

        rows = build_comparison_table(["water", "honey"], ["density"], lookup)
        assert len(rows) == 2
        assert rows[0].material == "water"
        assert rows[0].properties["density"] == "1.0"
        assert rows[1].properties["density"] == "1.42"

    def test_unknown_value_renders_not_available(self):
        rows = build_comparison_table(
            ["mystery"], ["tensile_strength"], lambda m, p: None
        )
        assert rows[0].properties["tensile_strength"] == NOT_AVAILABLE

    def test_row_count_matches_materials(self):
        rows = build_comparison_table(["a", "b", "c"], ["x"], lambda m, p: "v")
        assert len(rows) == 3

    def test_column_presence(self):
        rows = build_comparison_table(["a"], ["density", "viscosity"], lambda m, p: "v")
        assert set(rows[0].properties.keys()) == {"density", "viscosity"}
