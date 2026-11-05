"""File-backed store for MCP servers managed from the GUI.

Server records and their secrets live in two separate owner-only files
under one root directory:

* ``servers.json`` — self-contained server records (no secrets);
* ``secrets.json`` — tokens, secret environment variables, OAuth client
  secrets and OAuth tokens, keyed by server id.

The global store's root is ``<config dir>/mcp``. The store takes the root
as a parameter so another scope (for example a per-team layer) can reuse
the same format under its own directory.

Servers declared in ``[tools.mcp].servers`` in ``config.toml`` are not
stored here; they keep working as before and are merged in by
:func:`openjarvis.mcp.loader.resolve_effective_mcp_servers`.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openjarvis.security.file_utils import secure_write_json

_FORMAT_VERSION = 1

# Fields copied verbatim from an API payload into a stored record.
RECORD_FIELDS = (
    "name",
    "transport",
    "url",
    "auth_type",
    "auth_header",
    "command",
    "args",
    "env_names",
    "oauth_client_id",
    "oauth_scopes",
    "oauth_auth_params",
    "include_tools",
    "exclude_tools",
    "enabled",
)

# Sentinel for ``update(token=KEEP)``: leave the stored secret unchanged.
KEEP = object()

Secrets = dict[str, dict[str, Any]]


def default_store_root(config_dir: Optional[Path] = None) -> Path:
    """Return the global store directory (``<config dir>/mcp``)."""
    if config_dir is None:
        from openjarvis.core.config import get_config_dir

        config_dir = get_config_dir()
    return Path(config_dir) / "mcp"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MCPServerStore:
    """Read and write GUI-managed MCP server records and their secrets."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else default_store_root()
        self._servers_path = self.root / "servers.json"
        self._secrets_path = self.root / "secrets.json"
        self._lock = threading.Lock()

    # -- file I/O ---------------------------------------------------------

    def _read(self, path: Path, key: str, default: Any) -> Any:
        if not path.exists():
            return default
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        value = data.get(key, default)
        if not isinstance(value, type(default)):
            raise ValueError(f"{path.name}: '{key}' has the wrong type")
        return value

    def _servers(self) -> list[dict[str, Any]]:
        return self._read(self._servers_path, "servers", [])

    def _secrets(self) -> Secrets:
        return self._read(self._secrets_path, "secrets", {})

    def _write_servers(self, servers: list[dict[str, Any]]) -> None:
        secure_write_json(
            self._servers_path, {"version": _FORMAT_VERSION, "servers": servers}
        )

    def _write_secrets(self, secrets: Secrets) -> None:
        secure_write_json(
            self._secrets_path, {"version": _FORMAT_VERSION, "secrets": secrets}
        )

    # -- public API -------------------------------------------------------

    def list_servers(self) -> list[dict[str, Any]]:
        """Return all records (without secrets)."""
        with self._lock:
            return [dict(s) for s in self._servers()]

    def get(self, server_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            for server in self._servers():
                if server.get("id") == server_id:
                    return dict(server)
        return None

    def has_token(self, server_id: str) -> bool:
        return bool(self.token(server_id))

    def token(self, server_id: str) -> Optional[str]:
        with self._lock:
            return self._secrets().get(server_id, {}).get("token") or None

    def env(self, server_id: str) -> dict[str, str]:
        """Return the stored secret environment variables for a server."""
        with self._lock:
            return _entry_env(self._secrets().get(server_id, {}))

    def env_set(self, server_id: str) -> list[str]:
        """Names of the environment variables that have a stored value."""
        return sorted(self.env(server_id))

    def oauth_tokens(self, server_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            tokens = self._secrets().get(server_id, {}).get("oauth")
        return dict(tokens) if isinstance(tokens, dict) else None

    def set_oauth_tokens(self, server_id: str, tokens: Optional[dict]) -> None:
        """Store (or with ``None`` remove) a server's OAuth tokens."""
        with self._lock:
            secrets = self._secrets()
            entry = dict(secrets.get(server_id, {}))
            if tokens:
                entry["oauth"] = dict(tokens)
            else:
                entry.pop("oauth", None)
            if entry:
                secrets[server_id] = entry
            else:
                secrets.pop(server_id, None)
            self._write_secrets(secrets)

    def oauth_client_secret(self, server_id: str) -> Optional[str]:
        with self._lock:
            return self._secrets().get(server_id, {}).get("oauth_client_secret")

    def create(
        self,
        fields: dict[str, Any],
        *,
        token: Optional[str],
        env: Optional[dict[str, str]] = None,
        oauth_client_secret: Optional[str] = None,
    ) -> dict:
        record = {k: fields.get(k) for k in RECORD_FIELDS}
        record["id"] = uuid.uuid4().hex[:12]
        record["created_at"] = record["updated_at"] = _now()
        with self._lock:
            servers = self._servers()
            servers.append(record)
            entry = _secret_entry({}, record, token, env, oauth_client_secret)
            if entry:
                secrets = self._secrets()
                secrets[record["id"]] = entry
                self._write_secrets(secrets)
            self._write_servers(servers)
        return dict(record)

    def update(
        self,
        server_id: str,
        fields: dict[str, Any],
        *,
        token: Any = KEEP,
        env: Optional[dict[str, str]] = None,
        oauth_client_secret: Any = KEEP,
    ) -> Optional[dict]:
        """Replace a record's fields.

        ``token`` and ``oauth_client_secret``: ``KEEP``, or ``None`` to
        clear. ``env`` sets the given variables ("" clears one); others
        keep their stored value, and names no longer in ``env_names`` are
        dropped. OAuth tokens are dropped when the URL, client or auth
        type changes.
        """
        with self._lock:
            servers = self._servers()
            for index, server in enumerate(servers):
                if server.get("id") == server_id:
                    break
            else:
                return None
            record = {**server, **{k: fields.get(k) for k in RECORD_FIELDS}}
            record["updated_at"] = _now()
            servers[index] = record
            secrets = self._secrets()
            old = secrets.get(server_id, {})
            entry = _secret_entry(old, record, token, env, oauth_client_secret)
            if "oauth" in entry and any(
                server.get(k) != record.get(k)
                for k in ("url", "auth_type", "oauth_client_id")
            ):
                del entry["oauth"]
            if entry != old:
                if entry:
                    secrets[server_id] = entry
                else:
                    secrets.pop(server_id, None)
                self._write_secrets(secrets)
            self._write_servers(servers)
        return dict(record)

    def delete(self, server_id: str) -> bool:
        with self._lock:
            servers = self._servers()
            remaining = [s for s in servers if s.get("id") != server_id]
            if len(remaining) == len(servers):
                return False
            self._write_servers(remaining)
            secrets = self._secrets()
            if secrets.pop(server_id, None) is not None:
                self._write_secrets(secrets)
        return True

    def runtime_configs(self, *, only_enabled: bool = True) -> list[dict[str, Any]]:
        """Return loader-ready server dicts with secrets merged in."""
        with self._lock:
            servers = self._servers()
            secrets = self._secrets()
        configs = []
        for server in servers:
            if not (server.get("enabled", True) or not only_enabled):
                continue
            entry = secrets.get(server.get("id", ""), {})
            configs.append(
                to_runtime_config(
                    server,
                    entry.get("token"),
                    _entry_env(entry),
                    oauth_root=self.root,
                    oauth_connected="oauth" in entry,
                )
            )
        return configs


def _entry_env(entry: dict[str, Any]) -> dict[str, str]:
    env = entry.get("env")
    return dict(env) if isinstance(env, dict) else {}


def _secret_entry(
    old: dict[str, Any],
    record: dict[str, Any],
    token: Any,
    env: Optional[dict[str, str]],
    oauth_client_secret: Any = KEEP,
) -> dict[str, Any]:
    """Return the secrets entry for ``record`` after applying the changes."""
    entry: dict[str, Any] = {}
    stored_token = old.get("token") if token is KEEP else token
    if stored_token:
        entry["token"] = stored_token
    if record.get("auth_type") == "oauth":
        secret = (
            old.get("oauth_client_secret")
            if oauth_client_secret is KEEP
            else oauth_client_secret
        )
        if secret:
            entry["oauth_client_secret"] = secret
        if old.get("oauth"):
            entry["oauth"] = old["oauth"]
    names = list(record.get("env_names") or [])
    values = {**_entry_env(old), **(env or {})}
    kept = {k: values[k] for k in names if values.get(k)}
    if kept:
        entry["env"] = kept
    return entry


def to_runtime_config(
    record: dict[str, Any],
    token: Optional[str],
    env: Optional[dict[str, str]] = None,
    *,
    oauth_root: Optional[Path] = None,
    oauth_connected: bool = False,
) -> dict:
    """Convert a stored record to the dict shape the MCP loaders accept.

    OAuth servers carry no token: the transport reads (and refreshes) it
    from the store at ``oauth_root`` on each request.
    """
    cfg: dict[str, Any] = {
        "id": record.get("id"),
        "name": record.get("name") or "<unnamed>",
        "include_tools": list(record.get("include_tools") or []),
        "exclude_tools": list(record.get("exclude_tools") or []),
    }
    if record.get("transport") == "stdio":
        cfg["command"] = record.get("command") or ""
        cfg["args"] = list(record.get("args") or [])
        names = record.get("env_names") or []
        values = {k: env[k] for k in names if env and env.get(k)}
        if values:
            cfg["env"] = values
    else:
        cfg["url"] = record.get("url")
        auth_type = record.get("auth_type") or "none"
        if auth_type == "oauth":
            if oauth_root is not None:
                cfg["oauth_store_root"] = str(oauth_root)
            cfg["oauth_connected"] = oauth_connected
        elif auth_type != "none" and token:
            cfg["token"] = token
            if auth_type == "header":
                cfg["auth_header"] = record.get("auth_header")
    return cfg


__all__ = [
    "KEEP",
    "MCPServerStore",
    "RECORD_FIELDS",
    "default_store_root",
    "to_runtime_config",
]
