"""Tests for ``jarvis quickstart`` command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli import cli


class TestQuickstartCommand:
    def test_registered(self):
        """quickstart should be a registered CLI command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart", "--help"])
        assert result.exit_code == 0
        assert "quickstart" in result.output.lower() or "--help" in result.output

    def test_happy_path(self, tmp_path):
        """Full quickstart succeeds when hardware detected and engine healthy."""
        config_path = tmp_path / "config.toml"
        hw = MagicMock()
        hw.platform = "linux"
        hw.cpu_brand = "Test CPU"
        hw.cpu_count = 8
        hw.ram_gb = 32
        hw.gpu = MagicMock(name="Test GPU", vram_gb=24, count=1, vendor="nvidia")

        with (
            patch("openjarvis.cli.quickstart_cmd.detect_hardware", return_value=hw),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_PATH", config_path),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch(
                "openjarvis.cli.quickstart_cmd.generate_default_toml",
                return_value="[engine]\n",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd.recommend_engine",
                return_value="ollama",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_engine_health",
                return_value=True,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_model_available",
                return_value=True,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._test_query",
                return_value="Hello!",
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            assert result.exit_code == 0
            assert "1/5" in result.output
            assert "5/5" in result.output

    def test_skips_config_if_exists(self, tmp_path):
        """Config step is skipped when config already exists."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("[engine]\n")
        hw = MagicMock()
        hw.platform = "linux"
        hw.cpu_brand = "Test CPU"
        hw.cpu_count = 8
        hw.ram_gb = 32
        hw.gpu = None

        with (
            patch("openjarvis.cli.quickstart_cmd.detect_hardware", return_value=hw),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_PATH", config_path),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch(
                "openjarvis.cli.quickstart_cmd.generate_default_toml",
                return_value="[engine]\n",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd.recommend_engine",
                return_value="ollama",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_engine_health",
                return_value=True,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_model_available",
                return_value=True,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._test_query",
                return_value="Hello!",
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            assert result.exit_code == 0
            assert (
                "already exists" in result.output.lower()
                or "skip" in result.output.lower()
            )

    def test_force_regenerates_config(self, tmp_path):
        """--force should regenerate config even if it exists."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("[old]\n")
        hw = MagicMock()
        hw.platform = "linux"
        hw.cpu_brand = "Test CPU"
        hw.cpu_count = 8
        hw.ram_gb = 32
        hw.gpu = None

        with (
            patch("openjarvis.cli.quickstart_cmd.detect_hardware", return_value=hw),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_PATH", config_path),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch(
                "openjarvis.cli.quickstart_cmd.generate_default_toml",
                return_value="[engine]\nnew = true\n",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd.recommend_engine",
                return_value="ollama",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_engine_health",
                return_value=True,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_model_available",
                return_value=True,
            ),
            patch("openjarvis.cli.quickstart_cmd._test_query", return_value="Hello!"),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart", "--force"])
            assert result.exit_code == 0
            assert "new = true" in config_path.read_text()

    def test_engine_not_found(self, tmp_path):
        """Helpful message when engine is unreachable."""
        config_path = tmp_path / "config.toml"
        hw = MagicMock()
        hw.platform = "linux"
        hw.cpu_brand = "Test CPU"
        hw.cpu_count = 8
        hw.ram_gb = 32
        hw.gpu = None

        with (
            patch("openjarvis.cli.quickstart_cmd.detect_hardware", return_value=hw),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_PATH", config_path),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch(
                "openjarvis.cli.quickstart_cmd.generate_default_toml",
                return_value="[engine]\n",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd.recommend_engine",
                return_value="ollama",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_engine_health",
                return_value=False,
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            assert result.exit_code == 1
            assert (
                "engine" in result.output.lower()
                or "not reachable" in result.output.lower()
            )

    def test_falls_back_to_any_healthy_engine(self, tmp_path):
        """If the recommended engine is down, use a healthy fallback engine."""
        config_path = tmp_path / "config.toml"
        hw = MagicMock()
        hw.platform = "darwin"
        hw.cpu_brand = "Apple M1"
        hw.cpu_count = 8
        hw.ram_gb = 16
        hw.gpu = MagicMock(name="Apple GPU", vram_gb=16, count=1, vendor="apple")

        with (
            patch("openjarvis.cli.quickstart_cmd.detect_hardware", return_value=hw),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_PATH", config_path),
            patch("openjarvis.cli.quickstart_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch(
                "openjarvis.cli.quickstart_cmd.generate_default_toml",
                return_value='[engine]\ndefault = "mlx"\n',
            ),
            patch(
                "openjarvis.cli.quickstart_cmd.recommend_engine",
                return_value="mlx",
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_engine_health",
                return_value=False,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._discover_healthy_engines",
                return_value=["ollama"],
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._check_model_available",
                return_value=True,
            ),
            patch(
                "openjarvis.cli.quickstart_cmd._test_query",
                return_value="Hello!",
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])

        assert result.exit_code == 0
        assert "falling back" in result.output.lower()
        assert "ollama" in result.output
