"""CLI commands that edit ``config.toml`` must read and write it as UTF-8.

``Path.read_text()`` / ``write_text()`` without ``encoding=`` use the locale
codec, which is cp1252 on a default Windows install. ``core.config`` loads the
file as UTF-8, so a non-UTF-8 default either crashes the command on read or
leaves a file the loader cannot parse after a write.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli

_READ_TEXT = Path.read_text
_WRITE_TEXT = Path.write_text

# U+2764 encodes to E2 9D A4 in UTF-8; 0x9D is undefined in cp1252.
_NON_CP1252_COMMENT = "# my assistant ❤\n"


def _read_utf8(path: Path) -> str:
    """Decode as strict UTF-8, ignoring platform newline translation."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.fixture(autouse=True)
def _cp1252_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``Path.read_text`` / ``write_text`` default to cp1252."""

    def read_text(path, encoding=None, errors=None, newline=None):
        return _READ_TEXT(path, encoding=encoding or "cp1252", errors=errors)

    def write_text(path, data, encoding=None, errors=None, newline=None):
        return _WRITE_TEXT(
            path, data, encoding=encoding or "cp1252", errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "write_text", write_text)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_bytes(
        (_NON_CP1252_COMMENT + '[server.auth]\napi_key = "old"\n').encode("utf-8")
    )
    return path


def test_auth_create_key_preserves_utf8_config(config_path: Path) -> None:
    with (
        patch("openjarvis.cli.auth_cmd.DEFAULT_CONFIG_PATH", config_path),
        patch("openjarvis.cli.auth_cmd.DEFAULT_CONFIG_DIR", config_path.parent),
    ):
        result = CliRunner().invoke(cli, ["auth", "create-key"])

    assert result.exit_code == 0, result.output
    text = _read_utf8(config_path)
    assert text.startswith(_NON_CP1252_COMMENT)
    assert 'api_key = "old"' not in text


def test_auth_revoke_key_preserves_utf8_config(config_path: Path) -> None:
    with patch("openjarvis.cli.auth_cmd.DEFAULT_CONFIG_PATH", config_path):
        result = CliRunner().invoke(cli, ["auth", "revoke-key"])

    assert result.exit_code == 0, result.output
    text = _read_utf8(config_path)
    assert text.startswith(_NON_CP1252_COMMENT)
    assert 'api_key = ""' in text


def test_tunnel_status_reads_utf8_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(
        (_NON_CP1252_COMMENT + 'public_url = "https://example.test"\n').encode("utf-8")
    )

    with patch("openjarvis.cli.tunnel_cmd.DEFAULT_CONFIG_PATH", config_path):
        result = CliRunner().invoke(cli, ["tunnel", "status"])

    assert result.exit_code == 0, result.output
    assert "https://example.test" in result.output


def test_mine_init_appends_to_utf8_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(_NON_CP1252_COMMENT.encode("utf-8"))

    result = CliRunner().invoke(
        cli,
        [
            "mine",
            "init",
            "--provider",
            "cpu-pearl",
            "--wallet-address",
            "prl1qtestingaddr",
            "--pearld-rpc-url",
            "http://127.0.0.1:44107",
            "--pearld-rpc-user",
            "rpcuser",
            "--pearld-rpc-password-env",
            "TEST_PEARLD_PASSWORD",
        ],
        env={"OPENJARVIS_CONFIG": str(config_path)},
    )

    assert result.exit_code == 0, result.output
    text = _read_utf8(config_path)
    assert text.startswith(_NON_CP1252_COMMENT)
    assert "[mining]" in text


def test_quickstart_writes_utf8_config(tmp_path: Path) -> None:
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
            return_value=_NON_CP1252_COMMENT + "[engine]\n",
        ),
        patch("openjarvis.cli.quickstart_cmd.recommend_engine", return_value="ollama"),
        patch("openjarvis.cli.quickstart_cmd._check_engine_health", return_value=True),
        patch(
            "openjarvis.cli.quickstart_cmd._check_model_available", return_value=True
        ),
        patch("openjarvis.cli.quickstart_cmd._test_query", return_value="Hello!"),
    ):
        result = CliRunner().invoke(cli, ["quickstart"])

    assert result.exit_code == 0, result.output
    assert _read_utf8(config_path).startswith(_NON_CP1252_COMMENT)
