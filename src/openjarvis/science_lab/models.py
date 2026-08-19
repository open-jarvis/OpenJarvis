"""Plain dataclasses for Science Lab data (no pydantic — matches repo convention)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

# The four labels every quantitative claim must be tagged with — never invent
# a number without one of these.
BASIS_EXPERIMENTAL = "DADO EXPERIMENTAL"
BASIS_CALCULATED = "VALOR CALCULADO"
BASIS_ESTIMATE = "ESTIMATIVA"
BASIS_HYPOTHESIS = "HIPÓTESE"

VALID_BASES = (
    BASIS_EXPERIMENTAL,
    BASIS_CALCULATED,
    BASIS_ESTIMATE,
    BASIS_HYPOTHESIS,
)


@dataclass(slots=True)
class TargetProperty:
    """One property the user's desired material must exhibit."""

    name: str
    target_value: str = ""
    unit: str = ""
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "target_value": self.target_value,
            "unit": self.unit,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TargetProperty":
        return cls(
            name=str(d.get("name", "")),
            target_value=str(d.get("target_value", "")),
            unit=str(d.get("unit", "")),
            rationale=str(d.get("rationale", "")),
        )


@dataclass(slots=True)
class PropertyAnalysis:
    """Structured requirements derived from a free-text objective."""

    objective: str
    target_properties: List[TargetProperty] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "target_properties": [p.to_dict() for p in self.target_properties],
            "constraints": list(self.constraints),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PropertyAnalysis":
        return cls(
            objective=str(d.get("objective", "")),
            target_properties=[
                TargetProperty.from_dict(p)
                for p in d.get("target_properties", []) or []
            ],
            constraints=list(d.get("constraints", []) or []),
        )


@dataclass(slots=True)
class Hypothesis:
    """A single candidate scientific explanation/mechanism."""

    id: str
    mechanism: str
    key_properties: Dict[str, str] = field(default_factory=dict)
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "mechanism": self.mechanism,
            "key_properties": dict(self.key_properties),
            "pros": list(self.pros),
            "cons": list(self.cons),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Hypothesis":
        return cls(
            id=str(d.get("id", "")),
            mechanism=str(d.get("mechanism", "")),
            key_properties=dict(d.get("key_properties", {}) or {}),
            pros=list(d.get("pros", []) or []),
            cons=list(d.get("cons", []) or []),
        )


@dataclass(slots=True)
class SimulationResult:
    """A single calculated/estimated quantity, always tagged with its basis."""

    quantity: str
    value: float
    unit: str
    basis: str  # one of VALID_BASES
    formula: str = ""
    inputs: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.basis not in VALID_BASES:
            raise ValueError(
                f"Invalid basis {self.basis!r}; must be one of {VALID_BASES}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quantity": self.quantity,
            "value": self.value,
            "unit": self.unit,
            "basis": self.basis,
            "formula": self.formula,
            "inputs": dict(self.inputs),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SimulationResult":
        return cls(
            quantity=str(d.get("quantity", "")),
            value=float(d.get("value", 0.0)),
            unit=str(d.get("unit", "")),
            basis=str(d.get("basis", BASIS_ESTIMATE)),
            formula=str(d.get("formula", "")),
            inputs=dict(d.get("inputs", {}) or {}),
        )


@dataclass(slots=True)
class ComparisonRow:
    """One material's row in a COMPARE MATERIALS table."""

    material: str
    properties: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"material": self.material, "properties": dict(self.properties)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ComparisonRow":
        return cls(
            material=str(d.get("material", "")),
            properties=dict(d.get("properties", {}) or {}),
        )


@dataclass(slots=True)
class ConfidenceScore:
    """A 0.0-1.0 confidence value plus a stated basis — never presented as certainty."""

    value: float
    basis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "basis": self.basis}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConfidenceScore":
        return cls(value=float(d.get("value", 0.0)), basis=str(d.get("basis", "")))


@dataclass(slots=True)
class ScienceProject:
    """A named, savable science project (objective, hypotheses, simulations)."""

    name: str
    objective: str
    target_properties: List[TargetProperty] = field(default_factory=list)
    hypotheses: List[Hypothesis] = field(default_factory=list)
    simulations: List[SimulationResult] = field(default_factory=list)
    comparison: List[ComparisonRow] = field(default_factory=list)
    confidence: ConfidenceScore = field(default_factory=lambda: ConfidenceScore(0.0))
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "objective": self.objective,
            "target_properties": [p.to_dict() for p in self.target_properties],
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "simulations": [s.to_dict() for s in self.simulations],
            "comparison": [c.to_dict() for c in self.comparison],
            "confidence": self.confidence.to_dict(),
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScienceProject":
        return cls(
            name=str(d.get("name", "")),
            objective=str(d.get("objective", "")),
            target_properties=[
                TargetProperty.from_dict(p)
                for p in d.get("target_properties", []) or []
            ],
            hypotheses=[Hypothesis.from_dict(h) for h in d.get("hypotheses", []) or []],
            simulations=[
                SimulationResult.from_dict(s) for s in d.get("simulations", []) or []
            ],
            comparison=[
                ComparisonRow.from_dict(c) for c in d.get("comparison", []) or []
            ],
            confidence=ConfidenceScore.from_dict(d.get("confidence", {}) or {}),
            notes=str(d.get("notes", "")),
            created_at=datetime.fromisoformat(d["created_at"])
            if d.get("created_at")
            else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(d["updated_at"])
            if d.get("updated_at")
            else datetime.now(timezone.utc),
        )


__all__ = [
    "BASIS_CALCULATED",
    "BASIS_ESTIMATE",
    "BASIS_EXPERIMENTAL",
    "BASIS_HYPOTHESIS",
    "VALID_BASES",
    "ComparisonRow",
    "ConfidenceScore",
    "Hypothesis",
    "PropertyAnalysis",
    "ScienceProject",
    "SimulationResult",
    "TargetProperty",
]
