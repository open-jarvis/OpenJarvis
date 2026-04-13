"""Shared assertion helpers for energy monitor tests.

These helpers capture common test patterns used across the AMD, Apple,
NVIDIA, and RAPL energy monitor test files, reducing duplication without
hiding vendor-specific mock setup.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# available() helpers
# ---------------------------------------------------------------------------


def assert_available_false_when_lib_missing(mod, monitor_cls, flag_name: str):
    """Assert monitor reports unavailable when its native library flag is False.

    Works for AMD (_AMDSMI_AVAILABLE) and NVIDIA (_PYNVML_AVAILABLE).
    """
    orig = getattr(mod, flag_name)
    setattr(mod, flag_name, False)
    try:
        assert monitor_cls.available() is False
    finally:
        setattr(mod, flag_name, orig)


# ---------------------------------------------------------------------------
# sample() helpers
# ---------------------------------------------------------------------------


def assert_sample_result_basics(result, *, vendor: str, energy_method: str):
    """Assert common sample-result fields present on every vendor."""
    assert result.vendor == vendor
    assert result.energy_method == energy_method
    assert result.duration_seconds >= 0


def assert_empty_sample_result(result, *, vendor: str):
    """Assert the result from a no-device / uninitialized sample."""
    assert result.energy_joules == 0.0
    assert result.duration_seconds >= 0
    assert result.vendor == vendor


# ---------------------------------------------------------------------------
# close() helpers
# ---------------------------------------------------------------------------


def assert_close_sets_uninitialized(monitor):
    """Assert that close() marks the monitor as not initialized."""
    monitor.close()
    assert monitor._initialized is False
