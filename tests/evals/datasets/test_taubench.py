"""Tests for the TauBench optional dependency boundary."""

from __future__ import annotations

import builtins
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from openjarvis.evals.datasets import taubench


def _mock_direct_url(monkeypatch, direct_url):
    distribution = Mock()
    distribution.read_text.return_value = direct_url
    monkeypatch.setattr(
        taubench.metadata, "distribution", Mock(return_value=distribution)
    )


def test_ensure_tau2_accepts_the_pinned_source_revision(monkeypatch):
    monkeypatch.setitem(sys.modules, "tau2", ModuleType("tau2"))
    _mock_direct_url(
        monkeypatch,
        (
            '{"url": "https://github.com/sierra-research/tau2-bench.git", '
            '"vcs_info": {"vcs": "git", '
            f'"commit_id": "{taubench.TAU2_REVISION}"}}}}'
        ),
    )

    taubench._ensure_tau2()


def test_ensure_tau2_requires_explicit_pinned_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "tau2", None)
    monkeypatch.setattr(
        taubench.metadata,
        "distribution",
        Mock(side_effect=taubench.metadata.PackageNotFoundError),
    )

    with pytest.raises(ImportError) as exc_info:
        taubench._ensure_tau2()

    message = str(exc_info.value)
    assert "does not install at runtime" in message
    assert taubench.TAU2_REVISION in message
    assert "uv pip install" in message


@pytest.mark.parametrize(
    "direct_url",
    [
        # Editable install left behind by the previous runtime installer.
        '{"url": "file:///home/user/.openjarvis/cache/tau2-bench", '
        '"dir_info": {"editable": true}}',
        # A git install from an arbitrary upstream revision.
        '{"url": "https://github.com/sierra-research/tau2-bench.git", '
        '"vcs_info": {"vcs": "git", "commit_id": "deadbeef"}}',
        # Registry installs do not carry PEP 610 direct-origin metadata.
        None,
    ],
)
def test_ensure_tau2_rejects_unpinned_install(monkeypatch, direct_url):
    _mock_direct_url(monkeypatch, direct_url)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "tau2":
            raise AssertionError("unverified tau2 package was imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(ImportError) as exc_info:
        taubench._ensure_tau2()

    message = str(exc_info.value)
    assert "does not match" in message
    assert taubench.TAU2_REVISION in message
    assert "--force-reinstall" in message


def test_verify_requirements_reports_install_instruction(monkeypatch):
    monkeypatch.setitem(sys.modules, "tau2", None)
    monkeypatch.setattr(
        taubench.metadata,
        "distribution",
        Mock(side_effect=taubench.metadata.PackageNotFoundError),
    )

    issues = taubench.TauBenchDataset().verify_requirements()

    assert len(issues) == 1
    assert taubench.TAU2_REVISION in issues[0]
