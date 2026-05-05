"""Tests for openjarvis.evals.comparison.third_party."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.evals.comparison.third_party import (
    ThirdPartyConfig,
    ThirdPartyEntry,
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

    def test_loads_default_path_with_no_args(self) -> None:
        """Calling load_third_party_config() with no args reads the in-repo default."""
        cfg = load_third_party_config()
        assert "hermes" in cfg.entries
        assert "openclaw" in cfg.entries
        assert cfg.entries["hermes"].pinned_commit == "5d3be898a"
        assert (
            cfg.entries["openclaw"].pinned_commit
            == "123ae82fca3009df7144fa8d41e1185cd63e61e1"
        )


class TestVerifyCommitPin:
    def test_matching_commit_passes(self, tmp_path: Path) -> None:
        """No exception when HEAD matches pinned commit."""
        from openjarvis.evals.comparison.third_party import verify_commit_pin

        entry = ThirdPartyEntry(
            name="hermes",
            path=tmp_path,
            pinned_commit="abc123",
            runner_script="x",
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "abc123\n"
            mock_run.return_value.returncode = 0
            verify_commit_pin(entry)  # should not raise

    def test_mismatched_commit_raises(self, tmp_path: Path) -> None:
        from openjarvis.evals.comparison.third_party import (
            CommitDriftError,
            verify_commit_pin,
        )

        entry = ThirdPartyEntry(
            name="hermes",
            path=tmp_path,
            pinned_commit="abc123",
            runner_script="x",
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "deadbeef\n"
            mock_run.return_value.returncode = 0
            with pytest.raises(CommitDriftError, match="abc123.*deadbeef"):
                verify_commit_pin(entry)

    def test_drift_override_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openjarvis.evals.comparison.third_party import verify_commit_pin

        entry = ThirdPartyEntry(
            name="hermes",
            path=tmp_path,
            pinned_commit="abc123",
            runner_script="x",
        )
        monkeypatch.setenv("JARVIS_ALLOW_COMMIT_DRIFT", "1")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "deadbeef\n"
            mock_run.return_value.returncode = 0
            # Should not raise; should log a warning instead
            verify_commit_pin(entry)


class TestVerifyCommitPinPathHandling:
    def test_empty_path_raises_with_env_var_hint(self) -> None:
        from openjarvis.evals.comparison.third_party import (
            ThirdPartyNotFoundError,
            verify_commit_pin,
        )

        entry = ThirdPartyEntry(
            name="hermes",
            path=Path(""),
            pinned_commit="abc",
            runner_script="x",
        )
        with pytest.raises(ThirdPartyNotFoundError, match="HERMES_AGENT_PATH"):
            verify_commit_pin(entry)
