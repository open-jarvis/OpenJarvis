"""Tests for ``jarvis init --host`` option."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import generate_default_toml, generate_minimal_toml

_NO_DL = "--no-download"


class TestInitHost:
    def test_init_host_writes_to_config(self, tmp_path: Path) -> None:
        """jarvis init --host writes the host into config.toml."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "init",
                    "--engine",
                    "ollama",
                    "--host",
                    "http://192.168.1.50:11434",
                    _NO_DL,
                ],
            )
        assert result.exit_code == 0
        content = config_path.read_text()
        assert "http://192.168.1.50:11434" in content

    def test_init_host_with_vllm(self, tmp_path: Path) -> None:
        """jarvis init --host applies to the selected engine."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli,
                ["init", "--engine", "vllm", "--host", "http://10.0.0.5:8000", _NO_DL],
            )
        assert result.exit_code == 0
        content = config_path.read_text()
        assert "http://10.0.0.5:8000" in content

    def test_init_host_probes_and_reports(self, tmp_path: Path) -> None:
        """jarvis init --host shows reachability status."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
            mock.patch("openjarvis.cli.init_cmd.httpx") as mock_httpx,
        ):
            mock_httpx.get.side_effect = Exception("Connection refused")
            result = CliRunner().invoke(
                cli,
                ["init", "--engine", "ollama", "--host", "http://bad:11434", _NO_DL],
            )
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "unreachable" in output_lower or "warning" in output_lower

    def test_init_without_host_still_works(self, tmp_path: Path) -> None:
        """jarvis init without --host still produces valid config."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(cli, ["init", "--engine", "ollama", _NO_DL])
        assert result.exit_code == 0
        content = config_path.read_text()
        assert "[engine]" in content


class TestGenerateTomlHost:
    def test_minimal_toml_with_host(self) -> None:
        from openjarvis.core.config import HardwareInfo

        hw = HardwareInfo()
        toml_str = generate_minimal_toml(
            hw, engine="ollama", host="http://remote:11434"
        )
        assert "http://remote:11434" in toml_str
        assert "[engine.ollama]" in toml_str

    def test_minimal_toml_without_host_has_comment(self) -> None:
        from openjarvis.core.config import HardwareInfo

        hw = HardwareInfo()
        toml_str = generate_minimal_toml(hw, engine="ollama")
        assert "# host" in toml_str

    def test_default_toml_with_host(self) -> None:
        from openjarvis.core.config import HardwareInfo

        hw = HardwareInfo()
        toml_str = generate_default_toml(
            hw, engine="ollama", host="http://remote:11434"
        )
        assert "http://remote:11434" in toml_str
