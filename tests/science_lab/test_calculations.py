"""Tests for pure Science Lab calculation helpers."""

from __future__ import annotations

import pytest

from openjarvis.science_lab.calculations import (
    calculate,
    estimate_concentration,
    estimate_density,
    estimate_density_mixture,
    estimate_molar_concentration,
    estimate_ph_dilution,
    estimate_viscosity_mixture,
    reference_value,
)
from openjarvis.science_lab.models import (
    BASIS_CALCULATED,
    BASIS_ESTIMATE,
    BASIS_EXPERIMENTAL,
)


class TestEstimateDensity:
    def test_basic(self):
        result = estimate_density(mass_g=100, volume_cm3=50)
        assert result.value == 2.0
        assert result.unit == "g/cm^3"
        assert result.basis == BASIS_CALCULATED

    def test_zero_volume_raises(self):
        with pytest.raises(ValueError):
            estimate_density(mass_g=100, volume_cm3=0)

    def test_negative_volume_raises(self):
        with pytest.raises(ValueError):
            estimate_density(mass_g=100, volume_cm3=-1)

    def test_negative_mass_raises(self):
        with pytest.raises(ValueError):
            estimate_density(mass_g=-1, volume_cm3=10)


class TestEstimateConcentration:
    def test_basic(self):
        result = estimate_concentration(solute_mass_g=5, solution_volume_ml=100)
        assert result.value == 5.0
        assert result.unit == "% w/v"
        assert result.basis == BASIS_CALCULATED

    def test_zero_volume_raises(self):
        with pytest.raises(ValueError):
            estimate_concentration(solute_mass_g=5, solution_volume_ml=0)


class TestEstimateMolarConcentration:
    def test_basic(self):
        # 58.44 g/mol NaCl, 5.844g in 1L -> 0.1 mol/L
        result = estimate_molar_concentration(
            solute_mass_g=5.844, molar_mass_g_per_mol=58.44, solution_volume_l=1.0
        )
        assert abs(result.value - 0.1) < 1e-9
        assert result.basis == BASIS_CALCULATED

    def test_zero_molar_mass_raises(self):
        with pytest.raises(ValueError):
            estimate_molar_concentration(
                solute_mass_g=1, molar_mass_g_per_mol=0, solution_volume_l=1
            )


class TestEstimateViscosityMixture:
    def test_pure_a(self):
        result = estimate_viscosity_mixture(
            viscosity_a_cp=10.0, fraction_a=1.0, viscosity_b_cp=1.0
        )
        assert abs(result.value - 10.0) < 1e-9
        assert result.basis == BASIS_ESTIMATE

    def test_pure_b(self):
        result = estimate_viscosity_mixture(
            viscosity_a_cp=10.0, fraction_a=0.0, viscosity_b_cp=1.0
        )
        assert abs(result.value - 1.0) < 1e-9

    def test_out_of_range_fraction_raises(self):
        with pytest.raises(ValueError):
            estimate_viscosity_mixture(
                viscosity_a_cp=10.0, fraction_a=1.5, viscosity_b_cp=1.0
            )

    def test_nonpositive_viscosity_raises(self):
        with pytest.raises(ValueError):
            estimate_viscosity_mixture(
                viscosity_a_cp=0, fraction_a=0.5, viscosity_b_cp=1.0
            )


class TestEstimateDensityMixture:
    def test_midpoint(self):
        result = estimate_density_mixture(
            density_a=2.0, fraction_a_by_volume=0.5, density_b=1.0
        )
        assert abs(result.value - 1.5) < 1e-9
        assert result.basis == BASIS_ESTIMATE


class TestEstimatePhDilution:
    def test_acid_dilution_moves_toward_neutral(self):
        result = estimate_ph_dilution(
            initial_ph=2.0, initial_volume_ml=100, water_added_ml=900
        )
        assert result.value > 2.0
        assert result.basis == BASIS_ESTIMATE

    def test_neutral_stays_neutral(self):
        result = estimate_ph_dilution(
            initial_ph=7.0, initial_volume_ml=100, water_added_ml=900
        )
        assert result.value == 7.0

    def test_negative_water_raises(self):
        with pytest.raises(ValueError):
            estimate_ph_dilution(
                initial_ph=2.0, initial_volume_ml=100, water_added_ml=-1
            )


class TestReferenceValue:
    def test_known_material(self):
        result = reference_value("water", "density")
        assert result is not None
        assert result.value == 1.0
        assert result.basis == BASIS_EXPERIMENTAL

    def test_unknown_material(self):
        assert reference_value("unobtainium", "density") is None

    def test_unknown_quantity(self):
        assert reference_value("water", "tensile_strength") is None

    def test_case_insensitive(self):
        result = reference_value("WATER", "density")
        assert result is not None


class TestCalculateDispatch:
    def test_dispatches_to_density(self):
        result = calculate("density", mass_g=10, volume_cm3=5)
        assert result.value == 2.0

    def test_unknown_quantity_raises(self):
        with pytest.raises(ValueError, match="Unknown quantity"):
            calculate("tensile_strength", mass_g=10)
