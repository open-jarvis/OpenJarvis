"""Tests for install-method detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.cli._install_detect import InstallInfo, detect_install


def _patch_pkg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``openjarvis.__file__`` at ``tmp_path / openjarvis / __init__.py``."""
    pkg_dir = tmp_path / "openjarvis"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    init = pkg_dir / "__init__.py"
    init.write_text("__version__ = '0.0.0+test'\n")

    import openjarvis

    monkeypatch.setattr(openjarvis, "__file__", str(init))
    return init


def test_editable_git_install_detected(tmp_path, monkeypatch):
    # Layout: <tmp>/repo/.git, <tmp>/repo/pyproject.toml,
    #         <tmp>/repo/src/openjarvis/__init__.py
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='openjarvis'\n")
    src = repo / "src"
    _patch_pkg_file(src, monkeypatch)

    info = detect_install()
    assert info.kind == "editable-git"
    assert "git pull" in info.upgrade_command
    assert "uv sync" in info.upgrade_command
    assert info.repo_root == repo


def test_uv_tool_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "share" / "uv" / "tools" / "openjarvis" / "lib" / "python3.12"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "uv-tool"
    assert info.upgrade_command == "uv tool upgrade openjarvis"


def test_pypi_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "pypi"
    assert info.upgrade_command == "pip install --upgrade openjarvis"


def test_unknown_install_falls_back_to_pypi(tmp_path, monkeypatch):
    fake = tmp_path / "somewhere" / "weird"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command == "pip install --upgrade openjarvis"


def test_missing_openjarvis_file_falls_back_to_pypi(monkeypatch):
    """openjarvis unimportable / no __file__ — still get a sane default."""
    with patch("openjarvis.cli._install_detect.Path") as mock_path:
        mock_path.side_effect = Exception("boom")
        info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command == "pip install --upgrade openjarvis"


def test_returns_install_info_dataclass():
    info = detect_install()
    assert isinstance(info, InstallInfo)
    assert info.kind in {"pypi", "uv-tool", "editable-git", "unknown"}
    assert info.upgrade_command
