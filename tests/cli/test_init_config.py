"""Tests for ``jarvis init --config`` option (regression for #768).

The ``--config`` option is declared with ``click.Path`` and the command body
uses the value as a :class:`pathlib.Path` (``config.read_text()`` /
``config.write_text()``). Without ``path_type=Path`` Click hands the callback a
plain ``str``, so every invocation of ``--config`` crashed with
``AttributeError: 'str' object has no attribute 'read_text'``.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli

_NO_DL = "--no-download"


class TestInitConfig:
    def test_init_config_installs_provided_file(self, tmp_path: Path) -> None:
        """jarvis init --config <file> activates it at the canonical path.

        Regression for #768: the callback receives a Path and can call
        ``read_text()`` / ``write_text()`` on it.
        """
        provided = tmp_path / "some-config.toml"
        supplied_content = '[engine]\nname = "ollama"\n'
        provided.write_text(supplied_content, encoding="utf-8")

        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"  # absent -> passes the exists() guard
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli, ["init", "--config", str(provided), _NO_DL]
            )

        assert result.exception is None, result.output
        assert result.exit_code == 0
        assert config_path.read_text(encoding="utf-8") == supplied_content
        # Treat the supplied file as input: init must not rewrite it.
        assert provided.read_text(encoding="utf-8") == supplied_content

    def test_init_config_digest_updates_installed_copy(self, tmp_path: Path) -> None:
        """Post-processing applies to the active copy, not the input file."""
        provided = tmp_path / "some-config.toml"
        supplied_content = '[engine]\nname = "ollama"\n'
        provided.write_text(supplied_content, encoding="utf-8")
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
                    "--config",
                    str(provided),
                    "--digest",
                    _NO_DL,
                ],
            )

        assert result.exception is None, result.output
        assert result.exit_code == 0
        assert "[digest]" in config_path.read_text(encoding="utf-8")
        assert provided.read_text(encoding="utf-8") == supplied_content

    def test_init_config_rejects_directory(self, tmp_path: Path) -> None:
        """A directory is rejected by Click (dir_okay=False), not by a later crash."""
        a_dir = tmp_path / "not-a-file"
        a_dir.mkdir()

        result = CliRunner().invoke(cli, ["init", "--config", str(a_dir), _NO_DL])

        # Click usage error (exit 2), and specifically NOT the AttributeError crash.
        assert result.exit_code == 2
        assert not isinstance(result.exception, AttributeError)
