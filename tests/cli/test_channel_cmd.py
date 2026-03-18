"""Tests for the ``jarvis channel`` CLI commands."""

from __future__ import annotations

from unittest import mock

from click.testing import CliRunner

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.cli import cli


def _patch_channel(
    list_channels=None,
    send_return=True,
    status_return=ChannelStatus.DISCONNECTED,
):
    """Return patches for load_config and _get_channel."""
    cfg = mock.MagicMock()
    cfg.channel.default_channel = ""

    bridge_instance = mock.MagicMock()
    bridge_instance.list_channels.return_value = list_channels or []
    bridge_instance.send.return_value = send_return
    bridge_instance.status.return_value = status_return

    config_patch = mock.patch(
        "openjarvis.core.config.load_config",
        return_value=cfg,
    )
    get_channel_patch = mock.patch(
        "openjarvis.cli.channel_cmd._get_channel",
        return_value=bridge_instance,
    )
    return config_patch, get_channel_patch, bridge_instance


class TestChannelHelp:
    def test_subcommands_in_help(self) -> None:
        result = CliRunner().invoke(cli, ["channel", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "send" in result.output
        assert "status" in result.output


class TestChannelList:
    def test_list_with_channels(self) -> None:
        config_p, getch_p, _ = _patch_channel(
            list_channels=["slack", "discord"],
        )
        with config_p, getch_p:
            result = CliRunner().invoke(cli, ["channel", "list"])
        assert result.exit_code == 0
        assert "slack" in result.output
        assert "discord" in result.output

    def test_list_no_channels(self) -> None:
        config_p, getch_p, _ = _patch_channel(list_channels=[])
        with config_p, getch_p:
            result = CliRunner().invoke(cli, ["channel", "list"])
        assert result.exit_code == 0
        assert "No channels available" in result.output

    def test_list_connection_error(self) -> None:
        config_p, getch_p, inst = _patch_channel()
        inst.list_channels.side_effect = ConnectionError("refused")
        with config_p, getch_p:
            result = CliRunner().invoke(cli, ["channel", "list"])
        assert result.exit_code == 0
        assert "Failed" in result.output or "refused" in result.output


class TestChannelSend:
    def test_send_success(self) -> None:
        config_p, getch_p, _ = _patch_channel(send_return=True)
        with config_p, getch_p:
            result = CliRunner().invoke(
                cli,
                ["channel", "send", "slack", "Hello!"],
            )
        assert result.exit_code == 0
        assert "Message sent" in result.output

    def test_send_failure(self) -> None:
        config_p, getch_p, _ = _patch_channel(send_return=False)
        with config_p, getch_p:
            result = CliRunner().invoke(
                cli,
                ["channel", "send", "slack", "Hello!"],
            )
        assert result.exit_code == 0
        assert "Failed to send" in result.output


class TestChannelStatus:
    def test_status_shows_info(self) -> None:
        config_p, getch_p, _ = _patch_channel(
            status_return=ChannelStatus.DISCONNECTED,
        )
        with config_p, getch_p:
            result = CliRunner().invoke(cli, ["channel", "status"])
        assert result.exit_code == 0
        assert "disconnected" in result.output
