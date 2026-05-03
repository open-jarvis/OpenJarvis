"""Tests for openjarvis.evals.comparison.third_party."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.evals.comparison.third_party import (
    ThirdPartyConfig,
    ThirdPartyNotFoundError,
    load_third_party_config,
)


class TestLoadThirdPartyConfig:
    def test_loads_default_toml(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "_third_party.toml"
        toml_path.write_text(
            "[hermes]\n"
            'path = "/some/hermes/path"\n'
            'pinned_commit = "abc123"\n'
            'runner_script = "_runners/hermes_runner.py"\n'
            'python_executable = ""\n'
            "\n"
            "[openclaw]\n"
            'path = "/some/openclaw/path"\n'
            'pinned_commit = "def456"\n'
            'runner_script = "_runners/openclaw_runner.mjs"\n'
            'node_executable = ""\n'
        )
        cfg = load_third_party_config(toml_path)
        assert isinstance(cfg, ThirdPartyConfig)
        assert cfg.entries["hermes"].path == Path("/some/hermes/path")
        assert cfg.entries["hermes"].pinned_commit == "abc123"
        assert cfg.entries["openclaw"].pinned_commit == "def456"

    def test_env_var_overrides_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        toml_path = tmp_path / "_third_party.toml"
        toml_path.write_text(
            "[hermes]\n"
            'path = "/default/hermes"\n'
            'pinned_commit = "abc"\n'
            'runner_script = "x"\n'
            'python_executable = ""\n'
        )
        monkeypatch.setenv("HERMES_AGENT_PATH", "/override/hermes")
        cfg = load_third_party_config(toml_path)
        assert cfg.entries["hermes"].path == Path("/override/hermes")

    def test_missing_toml_raises(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "does_not_exist.toml"
        with pytest.raises(ThirdPartyNotFoundError, match="_third_party.toml"):
            load_third_party_config(toml_path)
