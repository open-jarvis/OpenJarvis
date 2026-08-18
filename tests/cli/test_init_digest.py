"""Tests for ``jarvis init --digest`` config writing."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli

_NO_DL = "--no-download"


class TestInitDigestEncoding:
    def test_init_digest_round_trips_utf8(self, tmp_path: Path) -> None:
        """The digest section's U+2500 rule must survive on any locale (#769).

        Without explicit ``encoding=`` the write uses the locale codec, which
        is cp1252 on a default Windows install and cannot encode U+2500, so
        ``jarvis init --digest`` crashed with UnicodeEncodeError there.
        """
        config_dir = tmp_path / ".openjarvis"
        config_path = config_dir / "config.toml"
        with (
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
            mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_path),
            mock.patch("openjarvis.cli.init_cmd.PrivacyScanner"),
        ):
            result = CliRunner().invoke(
                cli,
                ["init", "--engine", "ollama", "--digest", _NO_DL],
            )
        assert result.exit_code == 0, result.output
        content = config_path.read_text(encoding="utf-8")
        assert "[digest]" in content
        assert "─" in content
