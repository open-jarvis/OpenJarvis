"""Pure, deterministic theoretical calculations — no LLM calls, no invented numbers.

Every function returns a :class:`SimulationResult` with an explicit ``basis``.
This module never emits ``BASIS_EXPERIMENTAL`` on its own — that label is
reserved for values pulled from :data:`REFERENCE_DATA` (a small table of
well-known constants). Everything this module computes is either
``BASIS_CALCULATED`` (closed-form formula) or ``BASIS_ESTIMATE`` (a
mixing-rule/heuristic approximation). Unknown/uncomputable quantities raise
``ValueError`` rather than fabricating a confident-looking number.
"""

from __future__ import annotations

from typing import Dict, Optional

from openjarvis.science_lab.models import (
    BASIS_CALCULATED,
    BASIS_ESTIMATE,
    BASIS_EXPERIMENTAL,
    SimulationResult,
)

# A handful of well-known reference values (g/cm^3 for density, cP for
# viscosity at ~20-25C) that calculations may cite as experimental inputs.
# Deliberately small — this is not meant to be a materials database.
REFERENCE_DATA: Dict[str, Dict[str, float]] = {
    "water": {"density": 1.0, "viscosity": 1.0},
    "glycerol": {"density": 1.261, "viscosity": 1412.0},
    "ethanol": {"density": 0.789, "viscosity": 1.2},
    "honey": {"density": 1.42, "viscosity": 10000.0},
}


def reference_value(material: str, quantity: str) -> Optional[SimulationResult]:
    """Look up a known constant, tagged ``BASIS_EXPERIMENTAL``, or ``None``."""
    material_key = material.strip().lower()
    data = REFERENCE_DATA.get(material_key)
    if data is None or quantity not in data:
        return None
    unit = (
        "g/cm^3" if quantity == "density" else "cP" if quantity == "viscosity" else ""
    )
    return SimulationResult(
        quantity=quantity,
        value=data[quantity],
        unit=unit,
        basis=BASIS_EXPERIMENTAL,
        formula=f"reference table lookup ({material_key})",
        inputs={},
    )


def estimate_density(mass_g: float, volume_cm3: float) -> SimulationResult:
    """density = mass / volume (a direct closed-form calculation)."""
    if volume_cm3 <= 0:
        raise ValueError("volume_cm3 must be positive")
    if mass_g < 0:
        raise ValueError("mass_g must be non-negative")
    value = mass_g / volume_cm3
    return SimulationResult(
        quantity="density",
        value=value,
        unit="g/cm^3",
        basis=BASIS_CALCULATED,
        formula="density = mass / volume",
        inputs={"mass_g": mass_g, "volume_cm3": volume_cm3},
    )


def estimate_concentration(
    solute_mass_g: float, solution_volume_ml: float
) -> SimulationResult:
    """concentration (w/v %) = 100 * solute_mass / solution_volume."""
    if solution_volume_ml <= 0:
        raise ValueError("solution_volume_ml must be positive")
    if solute_mass_g < 0:
        raise ValueError("solute_mass_g must be non-negative")
    value = 100.0 * solute_mass_g / solution_volume_ml
    return SimulationResult(
        quantity="concentration",
        value=value,
        unit="% w/v",
        basis=BASIS_CALCULATED,
        formula="concentration = 100 * solute_mass / solution_volume",
        inputs={
            "solute_mass_g": solute_mass_g,
            "solution_volume_ml": solution_volume_ml,
        },
    )


def estimate_molar_concentration(
    solute_mass_g: float, molar_mass_g_per_mol: float, solution_volume_l: float
) -> SimulationResult:
    """molarity = moles / liters, moles = mass / molar mass."""
    if solution_volume_l <= 0:
        raise ValueError("solution_volume_l must be positive")
    if molar_mass_g_per_mol <= 0:
        raise ValueError("molar_mass_g_per_mol must be positive")
    if solute_mass_g < 0:
        raise ValueError("solute_mass_g must be non-negative")
    moles = solute_mass_g / molar_mass_g_per_mol
    value = moles / solution_volume_l
    return SimulationResult(
        quantity="molar_concentration",
        value=value,
        unit="mol/L",
        basis=BASIS_CALCULATED,
        formula="molarity = (mass / molar_mass) / volume_L",
        inputs={
            "solute_mass_g": solute_mass_g,
            "molar_mass_g_per_mol": molar_mass_g_per_mol,
            "solution_volume_l": solution_volume_l,
        },
    )


def estimate_viscosity_mixture(
    viscosity_a_cp: float,
    fraction_a: float,
    viscosity_b_cp: float,
) -> SimulationResult:
    """Logarithmic mixing rule (Arrhenius/Kendall-Monroe-style approximation).

    ln(mu_mix) = fraction_a * ln(mu_a) + (1 - fraction_a) * ln(mu_b)

    This is a well-known heuristic, not an exact law — always tagged
    ``BASIS_ESTIMATE``, never ``BASIS_CALCULATED``.
    """
    import math

    if not (0.0 <= fraction_a <= 1.0):
        raise ValueError("fraction_a must be between 0.0 and 1.0")
    if viscosity_a_cp <= 0 or viscosity_b_cp <= 0:
        raise ValueError("viscosities must be positive")
    ln_mix = fraction_a * math.log(viscosity_a_cp) + (1 - fraction_a) * math.log(
        viscosity_b_cp
    )
    value = math.exp(ln_mix)
    return SimulationResult(
        quantity="viscosity_mixture",
        value=value,
        unit="cP",
        basis=BASIS_ESTIMATE,
        formula="ln(mu_mix) = x_a*ln(mu_a) + (1-x_a)*ln(mu_b)  [log mixing rule]",
        inputs={
            "viscosity_a_cp": viscosity_a_cp,
            "fraction_a": fraction_a,
            "viscosity_b_cp": viscosity_b_cp,
        },
    )


def estimate_density_mixture(
    density_a: float,
    fraction_a_by_volume: float,
    density_b: float,
) -> SimulationResult:
    """Ideal (volume-additive) mixing rule for density — an estimate, not exact.

    Real mixtures often show volume contraction/expansion on mixing, which
    this linear rule does not capture.
    """
    if not (0.0 <= fraction_a_by_volume <= 1.0):
        raise ValueError("fraction_a_by_volume must be between 0.0 and 1.0")
    if density_a <= 0 or density_b <= 0:
        raise ValueError("densities must be positive")
    value = fraction_a_by_volume * density_a + (1 - fraction_a_by_volume) * density_b
    return SimulationResult(
        quantity="density_mixture",
        value=value,
        unit="g/cm^3",
        basis=BASIS_ESTIMATE,
        formula="rho_mix = x_a*rho_a + (1-x_a)*rho_b  [ideal volume-additive mixing]",
        inputs={
            "density_a": density_a,
            "fraction_a_by_volume": fraction_a_by_volume,
            "density_b": density_b,
        },
    )


def estimate_ph_dilution(
    initial_ph: float, initial_volume_ml: float, water_added_ml: float
) -> SimulationResult:
    """Rough dilution-based pH shift estimate for strong acids/bases only.

    Assumes the solute is a strong acid (pH < 7) or strong base (pH > 7) so
    concentration scales linearly with dilution; this does NOT hold for weak
    acids/bases or buffered solutions — always tagged ``BASIS_ESTIMATE``.
    """
    if initial_volume_ml <= 0:
        raise ValueError("initial_volume_ml must be positive")
    if water_added_ml < 0:
        raise ValueError("water_added_ml must be non-negative")
    dilution_factor = initial_volume_ml / (initial_volume_ml + water_added_ml)
    import math

    if initial_ph < 7:
        # [H+] scales with dilution_factor; pH = -log10([H+])
        h_shift = -math.log10(dilution_factor) if dilution_factor > 0 else 0.0
        value = initial_ph + h_shift
    elif initial_ph > 7:
        oh_shift = -math.log10(dilution_factor) if dilution_factor > 0 else 0.0
        value = initial_ph - oh_shift
    else:
        value = 7.0
    return SimulationResult(
        quantity="ph_after_dilution",
        value=value,
        unit="pH",
        basis=BASIS_ESTIMATE,
        formula="strong-acid/base linear dilution approx. (invalid for weak/buffered)",
        inputs={
            "initial_ph": initial_ph,
            "initial_volume_ml": initial_volume_ml,
            "water_added_ml": water_added_ml,
        },
    )


# Dispatch table used by ScienceSimulateTool — keeps the tool a thin
# parameter-unpacking layer over this module's pure functions.
CALCULATIONS = {
    "density": estimate_density,
    "concentration": estimate_concentration,
    "molar_concentration": estimate_molar_concentration,
    "viscosity_mixture": estimate_viscosity_mixture,
    "density_mixture": estimate_density_mixture,
    "ph_after_dilution": estimate_ph_dilution,
}


def calculate(quantity: str, **inputs: float) -> SimulationResult:
    """Dispatch to the calculation function named *quantity*.

    Raises ``ValueError`` for an unknown quantity (never silently guesses).
    """
    func = CALCULATIONS.get(quantity)
    if func is None:
        raise ValueError(
            f"Unknown quantity: {quantity!r}. Available: {sorted(CALCULATIONS.keys())}"
        )
    return func(**inputs)


__all__ = [
    "CALCULATIONS",
    "REFERENCE_DATA",
    "calculate",
    "estimate_concentration",
    "estimate_density",
    "estimate_density_mixture",
    "estimate_molar_concentration",
    "estimate_ph_dilution",
    "estimate_viscosity_mixture",
    "reference_value",
]
