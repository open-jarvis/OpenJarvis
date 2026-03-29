"""Credential persistence for tools and channels.

Stores credentials in ~/.openjarvis/credentials.toml with 0o600 permissions.
Thread-safe writes via lock. Sets os.environ on save for immediate effect.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_LOCK = threading.Lock()
_DEFAULT_PATH = Path.home() / ".openjarvis" / "credentials.toml"

TOOL_CREDENTIALS: dict[str, list[str]] = {
    "web_search": ["TAVILY_API_KEY"],
    "image_generate": ["OPENAI_API_KEY"],
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "discord": ["DISCORD_BOT_TOKEN"],
    "email": ["EMAIL_USERNAME", "EMAIL_PASSWORD"],
    "whatsapp": ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"],
    "signal": ["SIGNAL_CLI_PATH"],
    "google_chat": ["GOOGLE_CHAT_WEBHOOK_URL"],
    "teams": ["TEAMS_WEBHOOK_URL"],
    "bluebubbles": ["BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_PASSWORD"],
    "line": ["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET"],
    "viber": ["VIBER_AUTH_TOKEN"],
    "messenger": ["MESSENGER_PAGE_ACCESS_TOKEN", "MESSENGER_VERIFY_TOKEN"],
    "reddit": [
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USERNAME",
        "REDDIT_PASSWORD",
    ],
    "mastodon": ["MASTODON_ACCESS_TOKEN", "MASTODON_API_BASE_URL"],
    "twitch": ["TWITCH_TOKEN", "TWITCH_CHANNEL"],
    "matrix": ["MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN"],
    "mattermost": ["MATTERMOST_URL", "MATTERMOST_TOKEN"],
    "zulip": ["ZULIP_EMAIL", "ZULIP_API_KEY", "ZULIP_SITE"],
    "rocketchat": ["ROCKETCHAT_URL", "ROCKETCHAT_USER_ID", "ROCKETCHAT_AUTH_TOKEN"],
    "xmpp": ["XMPP_JID", "XMPP_PASSWORD"],
    "feishu": ["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
    "nostr": ["NOSTR_PRIVATE_KEY"],
}


def load_credentials(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load credentials from TOML file."""
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def save_credential(
    tool_name: str,
    key: str,
    value: str,
    *,
    path: Path | None = None,
) -> None:
    """Save a single credential key, validate, write file, and set os.environ."""
    allowed = TOOL_CREDENTIALS.get(tool_name, [])
    if key not in allowed:
        raise ValueError(f"Unknown credential key '{key}' for tool '{tool_name}'")
    stripped = value.strip()
    if not stripped:
        raise ValueError("Credential value must not be empty")

    p = Path(path) if path else _DEFAULT_PATH
    with _LOCK:
        creds = load_credentials(path=p)
        if tool_name not in creds:
            creds[tool_name] = {}
        creds[tool_name][key] = stripped

        p.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for section, kvs in creds.items():
            lines.append(f"[{section}]")
            for k, v in kvs.items():
                lines.append(f'{k} = "{v}"')
            lines.append("")
        p.write_text("\n".join(lines))
        os.chmod(p, 0o600)

    os.environ[key] = stripped


def get_credential_status(tool_name: str) -> dict[str, bool]:
    """Return {KEY: bool} for each required key indicating if set in env."""
    keys = TOOL_CREDENTIALS.get(tool_name, [])
    return {k: bool(os.environ.get(k)) for k in keys}


def inject_credentials(path: Path | None = None) -> None:
    """Load credentials.toml and inject into os.environ. Call at server startup."""
    creds = load_credentials(path=path)
    for _tool, kvs in creds.items():
        for k, v in kvs.items():
            if k not in os.environ:
                os.environ[k] = v


def get_tool_credential(
    tool_name: str,
    key: str,
    *,
    path: Path | None = None,
) -> str | None:
    """Read a single credential without polluting ``os.environ``.

    Falls back to ``os.environ`` if the key is not in credentials.toml,
    for backward compatibility with Docker env var workflows.
    """
    creds = load_credentials(path=path)
    tool_creds = creds.get(tool_name, {})
    value = tool_creds.get(key)
    if value is not None:
        return value
    return os.environ.get(key) or None
