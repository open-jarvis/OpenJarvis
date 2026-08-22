"""Tests for the CLI skeleton."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

import openjarvis
from openjarvis.cli import cli, main


class TestMainEntryPoint:
    """Tests for the ``jarvis`` console script entry point."""

    def test_windows_reconfigures_stdout_to_utf8(self) -> None:
        """On Windows, main() must reconfigure stdout/stderr to UTF-8 so that
        CJK characters in CLI output don't trigger UnicodeEncodeError under
        legacy code pages (cp950, cp932, cp949)."""
        stdout_mock = mock.MagicMock(spec=io.TextIOWrapper)
        stderr_mock = mock.MagicMock(spec=io.TextIOWrapper)
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(sys, "stdout", stdout_mock),
            mock.patch.object(sys, "stderr", stderr_mock),
            mock.patch("openjarvis.cli.cli") as cli_mock,
        ):
            main()
        stdout_mock.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        stderr_mock.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )
        cli_mock.assert_called_once()

    def test_non_windows_does_not_reconfigure(self) -> None:
        """On non-Windows platforms, stdout/stderr are left untouched."""
        stdout_mock = mock.MagicMock(spec=io.TextIOWrapper)
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(sys, "stdout", stdout_mock),
            mock.patch("openjarvis.cli.cli") as cli_mock,
        ):
            main()
        stdout_mock.reconfigure.assert_not_called()
        cli_mock.assert_called_once()


class TestCLI:
    def test_help(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "OpenJarvis" in result.output

    def test_version(self) -> None:
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert openjarvis.__version__ in result.output

    def test_ask_requires_query(self) -> None:
        result = CliRunner().invoke(cli, ["ask"])
        assert result.exit_code != 0

    def test_serve_needs_engine(self) -> None:
        """Serve requires a running engine; exits with error when none available."""
        result = CliRunner().invoke(cli, ["serve"])
        # Either exits with error (no engine) or succeeds (deps missing)
        # Both are valid states for testing
        out = result.output.lower()
        assert result.exit_code != 0 or "not installed" in out or "no inference" in out

    def test_model_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["model", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "info" in result.output
        assert "pull" in result.output

    def test_memory_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "index" in result.output
        assert "search" in result.output
        assert "stats" in result.output

    def test_mine_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["mine", "--help"])
        assert result.exit_code == 0
        assert "doctor" in result.output
        assert "start" in result.output
        assert "stop" in result.output

    def test_telemetry_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["telemetry", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.output
        assert "export" in result.output
        assert "clear" in result.output

    def test_bench_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["bench", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_scheduler_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["scheduler", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "pause" in result.output
        assert "resume" in result.output
        assert "cancel" in result.output

    def test_channel_subcommands_exist(self) -> None:
        result = CliRunner().invoke(cli, ["channel", "--help"])
        assert result.exit_code == 0
        assert "send" in result.output
        assert "list" in result.output

    def test_init_creates_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--engine", "ollama", "--no-download"]
            )
        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert "[engine]" in content

    def test_init_preset_uses_utf8_for_config_copy(self, tmp_path: Path) -> None:
        """Preset installation reads and writes shipped TOML as UTF-8."""
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        original_read_text = Path.read_text
        original_write_text = Path.write_text

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path.name == "chat-simple.toml":
                assert kwargs.get("encoding") == "utf-8"
            return original_read_text(path, *args, **kwargs)

        def write_text(path: Path, data: str, *args: object, **kwargs: object) -> int:
            if path == config_path:
                assert kwargs.get("encoding") == "utf-8"
            return original_write_text(path, data, *args, **kwargs)

        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch.object(Path, "read_text", autospec=True, side_effect=read_text),
            mock.patch.object(
                Path, "write_text", autospec=True, side_effect=write_text
            ),
        ):
            result = CliRunner().invoke(cli, ["init", "--preset", "chat-simple"])

        assert result.exit_code == 0
        assert "lightweight conversational AI" in config_path.read_text(
            encoding="utf-8"
        )

    def test_preset_switch_requires_explicit_force(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".openjarvis"
        config_dir.mkdir()
        config_path = config_dir / "config.toml"
        original = '# customized\n[engine]\ndefault = "ollama"\n'
        config_path.write_text(original, encoding="utf-8")

        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
        ):
            rejected = CliRunner().invoke(
                cli,
                ["init", "--preset", "chat-simple"],
            )
            assert config_path.read_text(encoding="utf-8") == original
            confirmed = CliRunner().invoke(
                cli,
                ["init", "--preset", "chat-simple", "--force"],
            )

        assert rejected.exit_code != 0
        assert "jarvis init --preset chat-simple --force" in " ".join(
            rejected.output.split()
        )
        assert confirmed.exit_code == 0
        assert config_path.read_text(encoding="utf-8") != original
        assert "lightweight conversational AI" in config_path.read_text(
            encoding="utf-8"
        )


class TestStartupResilience:
    """Importing the CLI must not force heavy/native deps (#404, #309).

    A broken or slow numpy on Windows otherwise raises at import time and takes
    down every `jarvis` command — including `jarvis serve` — because the CLI
    eagerly pulls the deep-research command chain (-> embeddings -> numpy).
    """

    def test_importing_cli_does_not_import_numpy(self) -> None:
        # Run in a fresh subprocess: the pytest session itself almost certainly
        # has numpy loaded from other tests, so an in-process check is useless.
        code = (
            "import openjarvis.cli, sys; "
            "leaked=[m for m in sys.modules if m=='numpy' or m.startswith('numpy.')]; "
            "assert not leaked, leaked; "
            "print('numpy-free')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, (
            "importing openjarvis.cli pulled in numpy (a broken numpy would then "
            f"crash `jarvis serve`):\nstdout={result.stdout}\nstderr={result.stderr}"
        )
