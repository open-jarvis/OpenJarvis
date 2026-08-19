"""COMPARE MATERIALS table building."""

from __future__ import annotations

from typing import Callable, List, Optional

from openjarvis.science_lab.models import ComparisonRow

# A comparator returns the display string for one (material, property) cell,
# or None when the value is unknown ("N/A — dados insuficientes" is rendered
# by the caller, not baked into this module, so CLI/UI can localize it).
PropertyLookup = Callable[[str, str], Optional[str]]

NOT_AVAILABLE = "N/A — dados insuficientes"


def build_comparison_table(
    materials: List[str],
    properties: List[str],
    lookup: PropertyLookup,
) -> List[ComparisonRow]:
    """Build one :class:`ComparisonRow` per material.

    *lookup(material, property_name)* should return a display string for a
    known value, or ``None``/empty for unknown — unknown values are rendered
    as :data:`NOT_AVAILABLE` rather than silently omitted, so the table
    always makes gaps visible.
    """
    rows: List[ComparisonRow] = []
    for material in materials:
        row_properties = {}
        for prop in properties:
            value = lookup(material, prop)
            row_properties[prop] = value if value else NOT_AVAILABLE
        rows.append(ComparisonRow(material=material, properties=row_properties))
    return rows


__all__ = ["NOT_AVAILABLE", "PropertyLookup", "build_comparison_table"]
