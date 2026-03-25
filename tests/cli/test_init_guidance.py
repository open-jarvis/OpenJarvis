"""Tests for ``jarvis init`` next-steps guidance."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.cli.init_cmd import _next_steps_text

_NO_DL = "--no-download"


class TestInitShowsNextSteps:
    def test_init_shows_next_steps(self, tmp_path: Path) -> None:
        """Init command prints next-steps panel after writing config."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "llamacpp", _NO_DL]
            )
        assert result.exit_code == 0
        assert "Getting Started" in result.output
        assert "jarvis ask" in result.output
        assert "jarvis doctor" in result.output

    def test_init_output_shows_toml_sections_literally(self, tmp_path: Path) -> None:
        """Init output should render TOML section headers like [engine] literally."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "llamacpp", _NO_DL]
            )
        assert result.exit_code == 0
        assert "[engine]" in result.output
        assert "[intelligence]" in result.output


class TestNextStepsOllama:
    def test_next_steps_ollama(self) -> None:
        text = _next_steps_text("ollama")
        assert "ollama serve" in text
        assert "ollama pull" in text
        assert "jarvis ask" in text
        assert "jarvis doctor" in text

    def test_next_steps_ollama_with_model(self) -> None:
        text = _next_steps_text("ollama", "qwen3.5:14b")
        assert "ollama pull qwen3.5:14b" in text

    def test_next_steps_ollama_default_model(self) -> None:
        text = _next_steps_text("ollama")
        assert "ollama pull qwen3.5:3b" in text


class TestNextStepsVllm:
    def test_next_steps_vllm(self) -> None:
        text = _next_steps_text("vllm")
        assert "pip install vllm" in text
        assert "vllm serve" in text
        assert "jarvis ask" in text
        assert "jarvis doctor" in text


class TestNextStepsLlamacpp:
    def test_next_steps_llamacpp(self) -> None:
        text = _next_steps_text("llamacpp")
        assert "brew install llama.cpp" in text
        assert "llama-server" in text
        assert "jarvis ask" in text
        assert "jarvis doctor" in text


class TestNextStepsMlx:
    def test_next_steps_mlx(self) -> None:
        text = _next_steps_text("mlx")
        assert "pip install mlx-lm" in text
        assert "mlx_lm.server" in text
        assert "jarvis ask" in text
        assert "jarvis doctor" in text


class TestMinimalConfig:
    def test_init_generates_minimal_by_default(self, tmp_path: Path) -> None:
        """Default jarvis init produces a short config."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama", _NO_DL]
            )
        assert result.exit_code == 0
        content = config_path.read_text()
        # Minimal config should be short
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert len(lines) <= 30
        # Should have the reference hint
        assert "jarvis init --full" in content

    def test_init_full_generates_verbose_config(self, tmp_path: Path) -> None:
        """jarvis init --full produces the full reference config."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli,
                ["init", "--full", "--engine", "ollama", _NO_DL],
            )
        assert result.exit_code == 0
        content = config_path.read_text()
        # Full config should have many sections
        assert "[engine.ollama]" in content
        assert "[server]" in content
        assert "[security]" in content


class TestInitDownloadPrompt:
    def test_init_shows_download_prompt(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama"], input="n\n"
            )
        assert result.exit_code == 0
        assert "Download" in result.output
        assert "now?" in result.output

    def test_init_no_download_flag_skips_prompt(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama", _NO_DL]
            )
        assert result.exit_code == 0
        assert "Download" not in result.output


class TestInitEmptyModelFallback:
    def test_init_no_model_shows_warning(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.recommend_model", return_value=""),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "llamacpp"]
            )
        assert result.exit_code == 0
        assert (
            "Not enough memory" in result.output
            or "not enough memory" in result.output
        )


class TestNextStepsExoNexa:
    def test_next_steps_exo(self) -> None:
        text = _next_steps_text("exo")
        assert "exo" in text.lower()
        assert "jarvis ask" in text
        assert "ollama" not in text.lower()

    def test_next_steps_nexa(self) -> None:
        text = _next_steps_text("nexa")
        assert "nexa" in text.lower()
        assert "jarvis ask" in text
        assert "ollama" not in text.lower()


class TestInitDownloadDispatch:
    def test_init_ollama_download_calls_ollama_pull(
        self, tmp_path: Path
    ) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch(
                "openjarvis.cli.init_cmd.ollama_pull",
                return_value=True,
            ) as mock_pull,
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama"], input="y\n"
            )
        assert result.exit_code == 0
        mock_pull.assert_called_once()

    def test_init_vllm_shows_auto_download_message(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "vllm"], input="y\n"
            )
        assert result.exit_code == 0
        assert "automatically" in result.output


class TestInitPrivacyHook:
    def test_init_shows_privacy_summary(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner") as MockScanner,
        ):
            from openjarvis.cli.scan_cmd import ScanResult
            instance = MockScanner.return_value
            instance.run_quick.return_value = [
                ScanResult("FileVault", "ok", "FileVault enabled", "darwin"),
            ]
            result = CliRunner().invoke(
                cli, ["init", "--engine", "llamacpp", _NO_DL]
            )
        assert result.exit_code == 0
        assert "jarvis scan" in result.output
