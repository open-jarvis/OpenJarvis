"""Tests for RaplEnergyMonitor -- mock sysfs (no real RAPL required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.telemetry.energy_rapl import (
    RaplEnergyMonitor,
    _discover_domains,
)

_PLAT = "openjarvis.telemetry.energy_rapl.platform.system"
_BASE = "openjarvis.telemetry.energy_rapl._RAPL_BASE"


# ---------------------------------------------------------------------------
# Helpers: build a fake sysfs directory
# ---------------------------------------------------------------------------


def _create_rapl_domain(
    base: Path,
    name: str,
    dir_name: str,
    energy_uj: int = 100000,
    max_energy_uj: int = 262143328850,
) -> Path:
    """Create a single RAPL domain directory with required files."""
    domain_dir = base / dir_name
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "name").write_text(name)
    (domain_dir / "energy_uj").write_text(str(energy_uj))
    (domain_dir / "max_energy_range_uj").write_text(str(max_energy_uj))
    return domain_dir


def _build_fake_sysfs(tmp_path: Path) -> Path:
    """Build a fake /sys/class/powercap/intel-rapl tree.

    Creates:
      intel-rapl:0/          (package-0)
      intel-rapl:0/intel-rapl:0:0/  (dram)
    """
    rapl_base = tmp_path / "intel-rapl"
    rapl_base.mkdir()

    _create_rapl_domain(
        rapl_base,
        "package-0",
        "intel-rapl:0",
        energy_uj=500000,
        max_energy_uj=262143328850,
    )
    _create_rapl_domain(
        rapl_base,
        "dram",
        "intel-rapl:0/intel-rapl:0:0",
        energy_uj=100000,
        max_energy_uj=65535999603,
    )
    return rapl_base


# ---------------------------------------------------------------------------
# Tests: available()
# ---------------------------------------------------------------------------


class TestAvailable:
    def test_available_false_on_non_linux(self):
        with patch(_PLAT, return_value="Darwin"):
            assert RaplEnergyMonitor.available() is False

    def test_available_false_when_no_sysfs(self):
        with (
            patch(_PLAT, return_value="Linux"),
            patch(_BASE, Path("/nonexistent")),
        ):
            assert RaplEnergyMonitor.available() is False


# ---------------------------------------------------------------------------
# Tests: energy_method()
# ---------------------------------------------------------------------------


class TestEnergyMethod:
    def test_returns_rapl(self):
        monitor = RaplEnergyMonitor.__new__(RaplEnergyMonitor)
        assert monitor.energy_method() == "rapl"


# ---------------------------------------------------------------------------
# Tests: domain discovery
# ---------------------------------------------------------------------------


class TestDomainDiscovery:
    def test_discovers_domains_from_sysfs(self, tmp_path):
        rapl_base = _build_fake_sysfs(tmp_path)
        domains = _discover_domains(rapl_base)

        assert len(domains) == 2
        names = [d.name for d in domains]
        assert "package-0" in names
        assert "dram" in names

    def test_discovers_no_domains_from_empty_dir(self, tmp_path):
        rapl_base = tmp_path / "intel-rapl"
        rapl_base.mkdir()
        domains = _discover_domains(rapl_base)
        assert len(domains) == 0

    def test_discovers_no_domains_from_nonexistent_dir(self):
        domains = _discover_domains(Path("/nonexistent/intel-rapl"))
        assert len(domains) == 0


# ---------------------------------------------------------------------------
# Tests: sample() normal counter delta
# ---------------------------------------------------------------------------


class TestSampleNormalDelta:
    def test_normal_counter_delta(self, tmp_path):
        """Start reading, then update energy files, verify delta."""
        rapl_base = _build_fake_sysfs(tmp_path)

        with patch(_PLAT, return_value="Linux"):
            monitor = RaplEnergyMonitor(
                poll_interval_ms=50,
                rapl_base=rapl_base,
            )
            assert monitor._initialized is True
            assert len(monitor._domains) == 2

        # Set start values
        pkg_energy = rapl_base / "intel-rapl:0" / "energy_uj"
        dram_energy = rapl_base / "intel-rapl:0" / "intel-rapl:0:0" / "energy_uj"
        pkg_energy.write_text("500000")
        dram_energy.write_text("100000")

        with monitor.sample() as result:
            # Simulate energy consumption during block
            pkg_energy.write_text("600000")
            dram_energy.write_text("120000")

        # package delta: 600000 - 500000 = 100000 uJ = 0.1 J (cpu)
        # dram delta: 120000 - 100000 = 20000 uJ = 0.02 J
        # total: 120000 uJ = 0.12 J
        assert result.cpu_energy_joules == pytest.approx(100000 / 1e6)
        assert result.dram_energy_joules == pytest.approx(20000 / 1e6)
        assert result.energy_joules == pytest.approx(120000 / 1e6)
        assert result.vendor == "cpu_rapl"
        assert result.energy_method == "rapl"
        assert result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# Tests: sample() counter wrap-around
# ---------------------------------------------------------------------------


class TestSampleWrapAround:
    def test_counter_wrap_around(self, tmp_path):
        """When end < start, uses max_energy_range_uj."""
        rapl_base = tmp_path / "intel-rapl"
        rapl_base.mkdir()

        max_energy = 1000000
        _create_rapl_domain(
            rapl_base,
            "package-0",
            "intel-rapl:0",
            energy_uj=900000,
            max_energy_uj=max_energy,
        )

        with patch(_PLAT, return_value="Linux"):
            monitor = RaplEnergyMonitor(
                poll_interval_ms=50,
                rapl_base=rapl_base,
            )
            assert monitor._initialized is True

        pkg_energy = rapl_base / "intel-rapl:0" / "energy_uj"
        pkg_energy.write_text("900000")

        with monitor.sample() as result:
            # Counter wraps: end=200000 < start=900000
            pkg_energy.write_text("200000")

        # wrap = (max - start) + end = 100000 + 200000 = 300000 uJ
        expected_uj = (max_energy - 900000) + 200000
        assert result.energy_joules == pytest.approx(expected_uj / 1e6)
        assert result.cpu_energy_joules == pytest.approx(
            expected_uj / 1e6,
        )


# ---------------------------------------------------------------------------
# Tests: sample() domain categorization
# ---------------------------------------------------------------------------


class TestSampleDomainCategorization:
    def test_package_domains_categorized_as_cpu(self, tmp_path):
        rapl_base = _build_fake_sysfs(tmp_path)

        with patch(_PLAT, return_value="Linux"):
            monitor = RaplEnergyMonitor(
                poll_interval_ms=50,
                rapl_base=rapl_base,
            )

        # Set start values
        pkg_energy = rapl_base / "intel-rapl:0" / "energy_uj"
        dram_energy = rapl_base / "intel-rapl:0" / "intel-rapl:0:0" / "energy_uj"
        pkg_energy.write_text("1000")
        dram_energy.write_text("2000")

        with monitor.sample() as result:
            pkg_energy.write_text("5000")
            dram_energy.write_text("3000")

        # package-0 delta (4000 uJ) -> cpu_energy_joules
        assert result.cpu_energy_joules == pytest.approx(4000 / 1e6)
        # dram delta (1000 uJ) -> dram_energy_joules
        assert result.dram_energy_joules == pytest.approx(1000 / 1e6)


# ---------------------------------------------------------------------------
# Tests: close()
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_clears_domains(self, tmp_path):
        rapl_base = _build_fake_sysfs(tmp_path)

        with patch(_PLAT, return_value="Linux"):
            monitor = RaplEnergyMonitor(
                poll_interval_ms=50,
                rapl_base=rapl_base,
            )
            assert len(monitor._domains) == 2
            assert monitor._initialized is True

        monitor.close()

        assert monitor._domains == []
        assert monitor._initialized is False
