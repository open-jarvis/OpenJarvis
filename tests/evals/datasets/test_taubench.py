"""Tests for the TauBench optional dependency boundary."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from openjarvis.evals.datasets import taubench


def test_ensure_tau2_accepts_an_installed_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "tau2", ModuleType("tau2"))

    taubench._ensure_tau2()


def test_ensure_tau2_requires_explicit_pinned_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "tau2", None)

    with pytest.raises(ImportError) as exc_info:
        taubench._ensure_tau2()

    message = str(exc_info.value)
    assert "does not install at runtime" in message
    assert taubench.TAU2_REVISION in message
    assert "uv pip install" in message


def test_verify_requirements_reports_install_instruction(monkeypatch):
    monkeypatch.setitem(sys.modules, "tau2", None)

    issues = taubench.TauBenchDataset().verify_requirements()

    assert len(issues) == 1
    assert taubench.TAU2_REVISION in issues[0]
