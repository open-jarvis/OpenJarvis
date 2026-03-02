"""Channel abstraction for multi-platform messaging."""

import importlib

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)

# Trigger registration of built-in channels.
# Each module uses @ChannelRegistry.register() — importing is sufficient.
_CHANNEL_MODULES = [
    "telegram",
    "discord_channel",
    "slack",
    "webhook",
    "email_channel",
    "whatsapp",
    "signal_channel",
    "google_chat",
    "irc_channel",
    "webchat",
    "teams",
    "matrix_channel",
    "mattermost",
    "feishu",
    "bluebubbles",
    "whatsapp_baileys",
    "line_channel",
    "viber_channel",
    "messenger_channel",
    "reddit_channel",
    "mastodon_channel",
    "xmpp_channel",
    "rocketchat_channel",
    "zulip_channel",
    "twitch_channel",
    "nostr_channel",
]

for _mod in _CHANNEL_MODULES:
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

__all__ = [
    "BaseChannel",
    "ChannelHandler",
    "ChannelMessage",
    "ChannelStatus",
]
