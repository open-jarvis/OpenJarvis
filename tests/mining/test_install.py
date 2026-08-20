"""Tests for openjarvis.mining._install."""

from __future__ import annotations

import importlib.util
import sys
import types

import pytest


@pytest.mark.parametrize(
    "missing_module", ["pearl_mining", "pearl_gateway", "miner_base"]
)
def test_pearl_packages_available_returns_false_when_any_one_missing(
    missing_module, monkeypatch
):
    """Returns False if ANY of the three packages is absent."""
    from openjarvis.mining import _install

    # Stub the two that should be present, leave the third missing.
    present = {"pearl_mining", "pearl_gateway", "miner_base"} - {missing_module}
    for name in present:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.delitem(sys.modules, missing_module, raising=False)
    monkeypatch.setattr(_install, "_module_importable", lambda n: n != missing_module)

    assert _install.pearl_packages_available() is False


def test_pearl_packages_available_returns_true_when_all_present():
    """When all three are importable, returns True."""
    from openjarvis.mining import _install

    fakes = {
        name: types.ModuleType(name)
        for name in ("pearl_mining", "pearl_gateway", "miner_base")
    }
    with pytest.MonkeyPatch().context() as mp:
        for name, mod in fakes.items():
            mp.setitem(sys.modules, name, mod)
        assert _install.pearl_packages_available() is True


def test_install_hint_is_actionable():
    """The hint string must include the extra name and a clear next step."""
    from openjarvis.mining._install import install_hint

    h = install_hint()
    assert "mining-pearl-cpu" in h
    assert "uv sync" in h, "hint must mention `uv sync` (the project's installer)"


def test_module_importable_returns_false_on_value_error(monkeypatch):
    """If find_spec raises ValueError, the helper treats the module as missing."""
    from openjarvis.mining import _install

    def boom(name):
        raise ValueError("simulated partially-initialised package")

    monkeypatch.setattr(importlib.util, "find_spec", boom)
    # Make sure the module name is NOT in sys.modules, so we hit the find_spec path.
    monkeypatch.delitem(sys.modules, "_nonexistent_test_pkg", raising=False)
    assert _install._module_importable("_nonexistent_test_pkg") is False
