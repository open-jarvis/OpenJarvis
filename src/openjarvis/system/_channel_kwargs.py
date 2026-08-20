"""Per-channel config→kwargs mappers for ChannelRegistry.create()."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def _telegram(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.bot_token:
        kw["bot_token"] = c.bot_token
    if c.parse_mode:
        kw["parse_mode"] = c.parse_mode
    return kw


def _discord(c: Any) -> Dict[str, Any]:
    return {"bot_token": c.bot_token} if c.bot_token else {}


def _slack(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.bot_token:
        kw["bot_token"] = c.bot_token
    if c.app_token:
        kw["app_token"] = c.app_token
    return kw


def _webhook(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.url:
        kw["url"] = c.url
    if c.secret:
        kw["secret"] = c.secret
    if c.method:
        kw["method"] = c.method
    return kw


def _email(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {
        "smtp_port": c.smtp_port,
        "imap_port": c.imap_port,
        "use_tls": c.use_tls,
    }
    if c.smtp_host:
        kw["smtp_host"] = c.smtp_host
    if c.imap_host:
        kw["imap_host"] = c.imap_host
    if c.username:
        kw["username"] = c.username
    if c.password:
        kw["password"] = c.password
    return kw


def _whatsapp(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.access_token:
        kw["access_token"] = c.access_token
    if c.phone_number_id:
        kw["phone_number_id"] = c.phone_number_id
    return kw


def _signal(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.api_url:
        kw["api_url"] = c.api_url
    if c.phone_number:
        kw["phone_number"] = c.phone_number
    return kw


def _google_chat(c: Any) -> Dict[str, Any]:
    return {"webhook_url": c.webhook_url} if c.webhook_url else {}


def _irc(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"port": c.port, "use_tls": c.use_tls}
    if c.server:
        kw["server"] = c.server
    if c.nick:
        kw["nick"] = c.nick
    if c.password:
        kw["password"] = c.password
    return kw


def _webchat(c: Any) -> Dict[str, Any]:
    return {}


def _teams(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.app_id:
        kw["app_id"] = c.app_id
    if c.app_password:
        kw["app_password"] = c.app_password
    if c.service_url:
        kw["service_url"] = c.service_url
    return kw


def _matrix(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.homeserver:
        kw["homeserver"] = c.homeserver
    if c.access_token:
        kw["access_token"] = c.access_token
    return kw


def _mattermost(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.url:
        kw["url"] = c.url
    if c.token:
        kw["token"] = c.token
    return kw


def _feishu(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.app_id:
        kw["app_id"] = c.app_id
    if c.app_secret:
        kw["app_secret"] = c.app_secret
    return kw


def _bluebubbles(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {}
    if c.url:
        kw["url"] = c.url
    if c.password:
        kw["password"] = c.password
    return kw


def _whatsapp_baileys(c: Any) -> Dict[str, Any]:
    kw: Dict[str, Any] = {"assistant_has_own_number": c.assistant_has_own_number}
    if c.auth_dir:
        kw["auth_dir"] = c.auth_dir
    if c.assistant_name:
        kw["assistant_name"] = c.assistant_name
    return kw


def _sendblue(c: Any) -> Dict[str, Any]:
    if c is None:
        return {}
    kw: Dict[str, Any] = {}
    if getattr(c, "api_key_id", ""):
        kw["api_key_id"] = c.api_key_id
    if getattr(c, "api_secret_key", ""):
        kw["api_secret_key"] = c.api_secret_key
    if getattr(c, "from_number", ""):
        kw["from_number"] = c.from_number
    return kw


# Maps channel key → (config.channel.<attr>, mapper).
# Omit a channel here to have it fall through with only {"bus": bus}.
_CHANNEL_MAPPERS: Dict[str, tuple] = {
    "telegram": ("telegram", _telegram),
    "discord": ("discord", _discord),
    "slack": ("slack", _slack),
    "webhook": ("webhook", _webhook),
    "email": ("email", _email),
    "whatsapp": ("whatsapp", _whatsapp),
    "signal": ("signal", _signal),
    "google_chat": ("google_chat", _google_chat),
    "irc": ("irc", _irc),
    "webchat": ("webchat", _webchat),
    "teams": ("teams", _teams),
    "matrix": ("matrix", _matrix),
    "mattermost": ("mattermost", _mattermost),
    "feishu": ("feishu", _feishu),
    "bluebubbles": ("bluebubbles", _bluebubbles),
    "whatsapp_baileys": ("whatsapp_baileys", _whatsapp_baileys),
    "sendblue": ("sendblue", _sendblue),
}


def build_channel_kwargs(channel_config: Any, key: str) -> Dict[str, Any]:
    """Return channel-specific kwargs for ChannelRegistry.create(key, ...).

    Does not include ``bus`` — the caller adds that.
    """
    entry: Optional[tuple] = _CHANNEL_MAPPERS.get(key)
    if entry is None:
        return {}
    attr, mapper = entry
    sub_cfg: Callable[[Any], Dict[str, Any]] = getattr(channel_config, attr, None)
    if sub_cfg is None:
        return {}
    return mapper(sub_cfg)
