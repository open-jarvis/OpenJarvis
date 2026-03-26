"""Tests for Phase 21 messaging channels."""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.line_channel import LineChannel
from openjarvis.channels.mastodon_channel import MastodonChannel
from openjarvis.channels.messenger_channel import MessengerChannel
from openjarvis.channels.nostr_channel import NostrChannel
from openjarvis.channels.reddit_channel import RedditChannel
from openjarvis.channels.rocketchat_channel import RocketChatChannel
from openjarvis.channels.twitch_channel import TwitchChannel
from openjarvis.channels.viber_channel import ViberChannel
from openjarvis.channels.xmpp_channel import XMPPChannel
from openjarvis.channels.zulip_channel import ZulipChannel
from openjarvis.core.registry import ChannelRegistry

# (class, registry key, library module name, pip package name)
CHANNELS = [
    (LineChannel, "line", "linebot", "line-bot-sdk"),
    (ViberChannel, "viber", "viberbot", "viberbot"),
    (MessengerChannel, "messenger", "pymessenger", "pymessenger"),
    (RedditChannel, "reddit", "praw", "praw"),
    (MastodonChannel, "mastodon", "mastodon", "Mastodon.py"),
    (XMPPChannel, "xmpp", "slixmpp", "slixmpp"),
    (RocketChatChannel, "rocketchat", "rocketchat_API", "rocketchat_API"),
    (ZulipChannel, "zulip", "zulip", "zulip"),
    (TwitchChannel, "twitch", "twitchio", "twitchio"),
    (NostrChannel, "nostr", "pynostr", "pynostr"),
]


@pytest.fixture(autouse=True)
def _ensure_registered():
    """Re-register channels after any registry clear."""
    for cls, key, _, _ in CHANNELS:
        if not ChannelRegistry.contains(key):
            ChannelRegistry.register_value(key, cls)


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls,key,lib_mod,pip_pkg", CHANNELS)
class TestChannelSpec:
    """Verify registration, channel_id, and default status."""

    def test_registry_key(self, cls, key, lib_mod, pip_pkg):
        assert ChannelRegistry.contains(key)

    def test_channel_id(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        assert ch.channel_id == key

    def test_status_disconnected(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_list_channels(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        result = ch.list_channels()
        assert key in result

    def test_on_message_registers_handler(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


@pytest.mark.parametrize("cls,key,lib_mod,pip_pkg", CHANNELS)
class TestChannelNotConnected:
    """Verify send returns False when credentials are missing."""

    def test_send_no_credentials(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        result = ch.send("test-channel", "hello")
        assert result is False

    def test_connect_no_credentials_sets_error(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        # connect() without credentials should set ERROR status
        # (unless the import check fires first — but with no creds it
        # should short-circuit before the import)
        try:
            ch.connect()
        except ImportError:
            pass
        # With no credentials, status should be ERROR
        assert ch.status() == ChannelStatus.ERROR

    def test_disconnect(self, cls, key, lib_mod, pip_pkg):
        ch = cls()
        ch._status = ChannelStatus.CONNECTED
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED


@pytest.mark.parametrize("cls,key,lib_mod,pip_pkg", CHANNELS)
class TestChannelImportError:
    """Verify connect raises ImportError with helpful message when lib missing."""

    def _make_configured(self, cls, key):
        """Create a channel instance with enough config to pass cred checks."""
        if key == "line":
            return cls(channel_access_token="tok", channel_secret="sec")
        elif key == "viber":
            return cls(auth_token="tok")
        elif key == "messenger":
            return cls(access_token="tok")
        elif key == "reddit":
            return cls(client_id="cid", client_secret="csec")
        elif key == "mastodon":
            return cls(api_base_url="https://m.social", access_token="tok")
        elif key == "xmpp":
            return cls(jid="bot@example.com", password="pass")
        elif key == "rocketchat":
            return cls(url="https://rc.example.com", user="bot", password="pass")
        elif key == "zulip":
            return cls(email="bot@zulip.com", api_key="key", site="https://z.com")
        elif key == "twitch":
            return cls(access_token="tok")
        elif key == "nostr":
            return cls(private_key="aa" * 32)
        return cls()

    def test_connect_import_error(self, cls, key, lib_mod, pip_pkg):
        ch = self._make_configured(cls, key)

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == lib_mod or name.startswith(lib_mod + "."):
                raise ImportError(f"No module named '{lib_mod}'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match=pip_pkg):
                ch.connect()


# ---------------------------------------------------------------------------
# Individual channel-specific tests
# ---------------------------------------------------------------------------


class TestLineChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "LINE_CHANNEL_ACCESS_TOKEN": "env-tok",
                "LINE_CHANNEL_SECRET": "env-sec",
            },
        ):
            ch = LineChannel()
            assert ch._channel_access_token == "env-tok"
            assert ch._channel_secret == "env-sec"


class TestViberChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "VIBER_AUTH_TOKEN": "env-tok",
                "VIBER_BOT_NAME": "TestBot",
            },
        ):
            ch = ViberChannel()
            assert ch._auth_token == "env-tok"
            assert ch._name == "TestBot"


class TestMessengerChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "MESSENGER_ACCESS_TOKEN": "env-tok",
            },
        ):
            ch = MessengerChannel()
            assert ch._access_token == "env-tok"


class TestRedditChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "REDDIT_CLIENT_ID": "cid",
                "REDDIT_CLIENT_SECRET": "csec",
                "REDDIT_USERNAME": "user",
                "REDDIT_PASSWORD": "pass",
            },
        ):
            ch = RedditChannel()
            assert ch._client_id == "cid"
            assert ch._client_secret == "csec"
            assert ch._username == "user"
            assert ch._password == "pass"


class TestMastodonChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "MASTODON_API_BASE_URL": "https://m.social",
                "MASTODON_ACCESS_TOKEN": "env-tok",
            },
        ):
            ch = MastodonChannel()
            assert ch._api_base_url == "https://m.social"
            assert ch._access_token == "env-tok"


class TestXMPPChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "XMPP_JID": "bot@example.com",
                "XMPP_PASSWORD": "pass",
                "XMPP_SERVER": "xmpp.example.com",
                "XMPP_PORT": "5223",
            },
        ):
            ch = XMPPChannel()
            assert ch._jid == "bot@example.com"
            assert ch._password == "pass"
            assert ch._server == "xmpp.example.com"
            assert ch._port == 5223


class TestRocketChatChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "ROCKETCHAT_URL": "https://rc.example.com",
                "ROCKETCHAT_USER": "bot",
                "ROCKETCHAT_PASSWORD": "pass",
            },
        ):
            ch = RocketChatChannel()
            assert ch._url == "https://rc.example.com"
            assert ch._user == "bot"
            assert ch._password == "pass"

    def test_token_auth_env(self):
        with patch.dict(
            "os.environ",
            {
                "ROCKETCHAT_URL": "https://rc.example.com",
                "ROCKETCHAT_AUTH_TOKEN": "tok",
                "ROCKETCHAT_USER_ID": "uid",
            },
        ):
            ch = RocketChatChannel()
            assert ch._auth_token == "tok"
            assert ch._user_id == "uid"


class TestZulipChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "ZULIP_EMAIL": "bot@zulip.com",
                "ZULIP_API_KEY": "key",
                "ZULIP_SITE": "https://z.com",
            },
        ):
            ch = ZulipChannel()
            assert ch._email == "bot@zulip.com"
            assert ch._api_key == "key"
            assert ch._site == "https://z.com"

    def test_zuliprc_env(self):
        with patch.dict(
            "os.environ",
            {
                "ZULIP_RC": "/path/to/zuliprc",
            },
        ):
            ch = ZulipChannel()
            assert ch._zuliprc == "/path/to/zuliprc"


class TestTwitchChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "TWITCH_ACCESS_TOKEN": "env-tok",
                "TWITCH_CLIENT_ID": "env-cid",
                "TWITCH_NICK": "env-nick",
                "TWITCH_CHANNELS": "chan1,chan2",
            },
        ):
            ch = TwitchChannel()
            assert ch._access_token == "env-tok"
            assert ch._client_id == "env-cid"
            assert ch._nick == "env-nick"
            assert ch._initial_channels == "chan1,chan2"


class TestNostrChannel:
    def test_env_fallback(self):
        with patch.dict(
            "os.environ",
            {
                "NOSTR_PRIVATE_KEY": "aa" * 32,
                "NOSTR_RELAYS": "wss://r1.example.com,wss://r2.example.com",
            },
        ):
            ch = NostrChannel()
            assert ch._private_key == "aa" * 32
            assert len(ch._relays) == 2
            assert ch._relays[0] == "wss://r1.example.com"

    def test_default_relay(self):
        ch = NostrChannel()
        assert "wss://relay.damus.io" in ch._relays
