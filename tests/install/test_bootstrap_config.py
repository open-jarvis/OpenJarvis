"""Tests for openjarvis.cli._bootstrap.write_initial_config."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from openjarvis.cli import _bootstrap
from openjarvis.core.config import GpuInfo, HardwareInfo


def test_writes_minimal_local_config(tmp_openjarvis_home: Path) -> None:
    hw = HardwareInfo(
        platform="linux",
        cpu_brand="AMD EPYC",
        cpu_count=16,
        ram_gb=32.0,
        gpu=GpuInfo(vendor="nvidia", name="RTX 4090", vram_gb=24.0, count=1),
    )
    _bootstrap.write_initial_config(hardware=hw, engine="ollama", model="qwen3.5:2b")
    cfg_path = tmp_openjarvis_home / "config.toml"
    assert cfg_path.exists()
    data = tomllib.loads(cfg_path.read_text())
    assert data["engine"]["default"] == "ollama"
    assert data["intelligence"]["default_model"] == "qwen3.5:2b"
    assert data["agent"]["default_agent"] == "simple"


def test_writes_cloud_config(tmp_openjarvis_home: Path) -> None:
    hw = HardwareInfo(platform="darwin", cpu_brand="Apple M2", cpu_count=8, ram_gb=16.0)
    cloud = _bootstrap.CloudProvider(
        provider="anthropic",
        env_var="ANTHROPIC_API_KEY",
        api_key="sk-ant-test",
    )
    _bootstrap.write_initial_config(
        hardware=hw, engine="cloud", model="claude-opus-4-6", cloud=cloud
    )
    data = tomllib.loads((tmp_openjarvis_home / "config.toml").read_text())
    assert data["engine"]["default"] == "cloud"
    assert data["intelligence"]["default_model"] == "claude-opus-4-6"
    assert data["intelligence"]["provider"] == "anthropic"


def test_includes_install_provenance(tmp_openjarvis_home: Path, monkeypatch) -> None:
    monkeypatch.setattr(_bootstrap, "_now_iso", lambda: "2026-05-03T12:00:00Z")
    monkeypatch.setattr(_bootstrap, "_installer_version", lambda: "0.1.1")
    hw = HardwareInfo(platform="linux", cpu_brand="x", cpu_count=1, ram_gb=4.0)
    _bootstrap.write_initial_config(hardware=hw, engine="ollama", model="qwen3.5:2b")
    data = tomllib.loads((tmp_openjarvis_home / "config.toml").read_text())
    assert data["installed_at"] == "2026-05-03T12:00:00Z"
    assert data["installer_version"] == "0.1.1"


def test_writes_seed_files_if_absent(tmp_openjarvis_home: Path) -> None:
    hw = HardwareInfo(platform="linux", cpu_brand="x", cpu_count=1, ram_gb=4.0)
    _bootstrap.write_initial_config(hardware=hw, engine="ollama", model="qwen3.5:2b")
    assert (tmp_openjarvis_home / "SOUL.md").exists()
    assert (tmp_openjarvis_home / "MEMORY.md").exists()
    assert (tmp_openjarvis_home / "USER.md").exists()
    assert (tmp_openjarvis_home / "skills").is_dir()


def test_does_not_overwrite_existing_seeds(tmp_openjarvis_home: Path) -> None:
    soul = tmp_openjarvis_home / "SOUL.md"
    soul.write_text("custom user content\n")
    hw = HardwareInfo(platform="linux", cpu_brand="x", cpu_count=1, ram_gb=4.0)
    _bootstrap.write_initial_config(hardware=hw, engine="ollama", model="qwen3.5:2b")
    assert soul.read_text() == "custom user content\n"


def test_overwrites_existing_config_toml(tmp_openjarvis_home: Path) -> None:
    cfg = tmp_openjarvis_home / "config.toml"
    cfg.write_text('[engine]\ndefault = "old"\n')
    hw = HardwareInfo(platform="linux", cpu_brand="x", cpu_count=1, ram_gb=4.0)
    _bootstrap.write_initial_config(hardware=hw, engine="ollama", model="qwen3.5:2b")
    data = tomllib.loads(cfg.read_text())
    assert data["engine"]["default"] == "ollama"
