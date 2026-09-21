"""Tests for ``jarvis init --digest`` config writing."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import cli

_NO_DL = "--no-download"
_READ_TEXT = Path.read_text
_WRITE_TEXT = Path.write_text


def _cp1252_read_text(
    path: Path,
    encoding: str | None = None,
    errors: str | None = None,
) -> str:
    return _READ_TEXT(path, encoding=encoding or "cp1252", errors=errors)


def _cp1252_write_text(
    path: Path,
    data: str,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
) -> int:
    return _WRITE_TEXT(
        path,
        data,
        encoding=encoding or "cp1252",
        errors=errors,
        newline=newline,
    )


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
            # Emulate Windows' non-UTF default locale on every platform. Any
            # init-path read/write that omits encoding now uses cp1252 and the
            # box-drawing rule raises exactly the original Unicode error.
            mock.patch.object(Path, "read_text", _cp1252_read_text),
            mock.patch.object(Path, "write_text", _cp1252_write_text),
        ):
            result = CliRunner().invoke(
                cli,
                ["init", "--engine", "ollama", "--digest", _NO_DL],
            )
        assert result.exit_code == 0, result.output
        content = config_path.read_text(encoding="utf-8")
        assert "[digest]" in content
        assert "─" in content
