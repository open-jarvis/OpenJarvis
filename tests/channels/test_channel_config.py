"""Tests for channel configuration — nested sub-configs and TOML loading."""

from __future__ import annotations

import tempfile
from pathlib import Path

from openjarvis.core.config import (
    ChannelConfig,
    DiscordChannelConfig,
    EmailChannelConfig,
    SlackChannelConfig,
    TelegramChannelConfig,
    WebhookChannelConfig,
    load_config,
)


class TestChannelConfig:
    def test_defaults(self):
        cfg = ChannelConfig()
        assert cfg.enabled is False
        assert cfg.default_channel == ""
        assert cfg.default_agent == "simple"

    def test_nested_defaults(self):
        cfg = ChannelConfig()
        assert isinstance(cfg.telegram, TelegramChannelConfig)
        assert isinstance(cfg.discord, DiscordChannelConfig)
        assert isinstance(cfg.slack, SlackChannelConfig)
        assert isinstance(cfg.webhook, WebhookChannelConfig)
        assert isinstance(cfg.email, EmailChannelConfig)

    def test_telegram_defaults(self):
        cfg = TelegramChannelConfig()
        assert cfg.bot_token == ""
        assert cfg.allowed_chat_ids == ""
        assert cfg.parse_mode == "Markdown"

    def test_discord_defaults(self):
        cfg = DiscordChannelConfig()
        assert cfg.bot_token == ""

    def test_slack_defaults(self):
        cfg = SlackChannelConfig()
        assert cfg.bot_token == ""
        assert cfg.app_token == ""

    def test_webhook_defaults(self):
        cfg = WebhookChannelConfig()
        assert cfg.url == ""
        assert cfg.secret == ""
        assert cfg.method == "POST"

    def test_email_defaults(self):
        cfg = EmailChannelConfig()
        assert cfg.smtp_host == ""
        assert cfg.smtp_port == 587
        assert cfg.imap_host == ""
        assert cfg.imap_port == 993
        assert cfg.username == ""
        assert cfg.password == ""
        assert cfg.use_tls is True


class TestTomlLoading:
    def _write_toml(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".toml",
            delete=False,
        )
        f.write(content)
        f.flush()
        f.close()
        return Path(f.name)

    def test_load_channel_top_level(self):
        path = self._write_toml("""
[channel]
enabled = true
default_channel = "telegram"
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.enabled is True
            assert cfg.channel.default_channel == "telegram"
        finally:
            path.unlink()

    def test_load_channel_telegram(self):
        path = self._write_toml("""
[channel]
enabled = true
default_channel = "telegram"

[channel.telegram]
bot_token = "123:ABC"
parse_mode = "HTML"
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.telegram.bot_token == "123:ABC"
            assert cfg.channel.telegram.parse_mode == "HTML"
        finally:
            path.unlink()

    def test_load_channel_discord(self):
        path = self._write_toml("""
[channel.discord]
bot_token = "discord-token"
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.discord.bot_token == "discord-token"
        finally:
            path.unlink()

    def test_load_channel_slack(self):
        path = self._write_toml("""
[channel.slack]
bot_token = "xoxb-slack"
app_token = "xapp-slack"
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.slack.bot_token == "xoxb-slack"
            assert cfg.channel.slack.app_token == "xapp-slack"
        finally:
            path.unlink()

    def test_load_channel_webhook(self):
        path = self._write_toml("""
[channel.webhook]
url = "https://example.com/hook"
secret = "s3cr3t"
method = "PUT"
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.webhook.url == "https://example.com/hook"
            assert cfg.channel.webhook.secret == "s3cr3t"
            assert cfg.channel.webhook.method == "PUT"
        finally:
            path.unlink()

    def test_load_channel_email(self):
        path = self._write_toml("""
[channel.email]
smtp_host = "smtp.example.com"
smtp_port = 465
username = "user@example.com"
password = "pass"
use_tls = false
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.email.smtp_host == "smtp.example.com"
            assert cfg.channel.email.smtp_port == 465
            assert cfg.channel.email.username == "user@example.com"
            assert cfg.channel.email.password == "pass"
            assert cfg.channel.email.use_tls is False
        finally:
            path.unlink()

    def test_backward_compat_no_default_channel(self):
        """Old config without default_channel still works."""
        path = self._write_toml("""
[channel]
enabled = false
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.enabled is False
            assert cfg.channel.default_channel == ""
        finally:
            path.unlink()

    def test_multiple_channel_configs(self):
        path = self._write_toml("""
[channel]
enabled = true
default_channel = "slack"

[channel.telegram]
bot_token = "tg-token"

[channel.slack]
bot_token = "slack-token"
""")
        try:
            cfg = load_config(path)
            assert cfg.channel.default_channel == "slack"
            assert cfg.channel.telegram.bot_token == "tg-token"
            assert cfg.channel.slack.bot_token == "slack-token"
        finally:
            path.unlink()
