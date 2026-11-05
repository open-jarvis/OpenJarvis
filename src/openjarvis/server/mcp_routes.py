"""FastAPI router for /v1/mcp/servers — global MCP server management.

GUI-managed servers live in :class:`openjarvis.mcp.store.MCPServerStore`.
Servers declared in ``config.toml`` are listed read-only (and can be
tested) but never written.

Secrets are write-only: responses carry ``has_token`` instead of the
token, and request bodies are parsed by hand so validation errors never
echo the submitted input (FastAPI's default 422 body includes it).

MCP tools are discovered once at server start-up, so changes made here
take effect after a restart; responses report ``restart_required``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Callable, List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from openjarvis.mcp.store import KEEP, MCPServerStore, to_runtime_config

logger = logging.getLogger(__name__)

_CONFIG_ID_PREFIX = "config-"
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
# Headers the transport sets itself; a token must not override them.
_RESERVED_HEADERS = {
    "accept",
    "content-type",
    "content-length",
    "host",
    "mcp-session-id",
}
_TEST_TIMEOUT_SECONDS = 20.0
_MAX_BODY_BYTES = 64 * 1024


class MCPServerIn(BaseModel):
    """Create/update payload for a GUI-managed MCP server."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    transport: Literal["http", "stdio"]
    url: Optional[str] = Field(default=None, max_length=2048)
    auth_type: Literal["none", "bearer", "header"] = "none"
    auth_header: Optional[str] = Field(default=None, max_length=100)
    # Write-only. On update: omitted/null keeps the stored token, "" clears.
    token: Optional[str] = Field(default=None, max_length=8192)
    command: Optional[str] = Field(default=None, max_length=1024)
    args: List[str] = Field(default_factory=list, max_length=100)
    include_tools: List[str] = Field(default_factory=list, max_length=500)
    exclude_tools: List[str] = Field(default_factory=list, max_length=500)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_transport(self) -> "MCPServerIn":
        if self.transport == "http":
            if not self.url:
                raise ValueError("url is required for http servers")
            parsed = urlparse(self.url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("url must be an http:// or https:// URL")
            if parsed.username or parsed.password:
                raise ValueError(
                    "url must not contain credentials; use the token field"
                )
            if self.auth_type == "header":
                header = self.auth_header or ""
                if not _HEADER_NAME_RE.match(header):
                    raise ValueError("auth_header must be a valid HTTP header name")
                if header.lower() in _RESERVED_HEADERS:
                    raise ValueError("auth_header cannot be a reserved header")
            else:
                self.auth_header = None
            self.command = None
            self.args = []
        else:
            if not self.command:
                raise ValueError("command is required for stdio servers")
            self.url = None
            self.auth_type = "none"
            self.auth_header = None
        self.include_tools = [t for t in (s.strip() for s in self.include_tools) if t]
        self.exclude_tools = [t for t in (s.strip() for s in self.exclude_tools) if t]
        return self

    def fields(self) -> dict[str, Any]:
        return self.model_dump(exclude={"token"})


class MCPServerTestIn(MCPServerIn):
    """Test an unsaved draft; ``id`` reuses that server's stored token."""

    id: Optional[str] = Field(default=None, max_length=64)


def _redact(text: str, secrets: list[Optional[str]]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _safe_url(url: Optional[str]) -> Optional[str]:
    """Drop query, fragment and credentials, which may carry secrets."""
    if not url:
        return url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path}"


async def _parse_body(request: Request, model: type[BaseModel]) -> Any:
    """Parse a JSON body without ever echoing it back in an error."""
    content_type = request.headers.get("content-type", "")
    if not content_type.split(";")[0].strip().lower() == "application/json":
        # Also blocks "simple" cross-site form/text POSTs (no CORS preflight).
        raise HTTPException(415, "Content-Type must be application/json")
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    try:
        data = json.loads(raw or b"null")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Request body is not valid JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(422, "Request body must be a JSON object")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        token = data.get("token") if isinstance(data.get("token"), str) else None
        errors = [
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": _redact(str(err.get("msg", "invalid value")), [token]),
            }
            for err in exc.errors(include_input=False, include_url=False)
        ]
        raise HTTPException(422, errors) from None


def _gui_view(record: dict[str, Any], store: MCPServerStore) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "transport": record.get("transport"),
        "url": record.get("url"),
        "auth_type": record.get("auth_type") or "none",
        "auth_header": record.get("auth_header"),
        "has_token": store.has_token(record.get("id", "")),
        "command": record.get("command"),
        "args": list(record.get("args") or []),
        "include_tools": list(record.get("include_tools") or []),
        "exclude_tools": list(record.get("exclude_tools") or []),
        "enabled": bool(record.get("enabled", True)),
        "source": "gui",
        "read_only": False,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _config_view(index: int, cfg: dict[str, Any]) -> dict[str, Any]:
    # Args are omitted: config.toml users sometimes pass keys on the
    # command line, and this listing must never expose secrets.
    return {
        "id": f"{_CONFIG_ID_PREFIX}{index}",
        "name": cfg.get("name") or "<unnamed>",
        "transport": "http" if cfg.get("url") else "stdio",
        "url": _safe_url(cfg.get("url")),
        "auth_type": "bearer" if cfg.get("token") else "none",
        "auth_header": None,
        "has_token": bool(cfg.get("token")),
        "command": cfg.get("command") or None,
        "args": [],
        "include_tools": list(cfg.get("include_tools") or []),
        "exclude_tools": list(cfg.get("exclude_tools") or []),
        "enabled": True,
        "source": "config",
        "read_only": True,
    }


def _fingerprint(configs: list[dict[str, Any]]) -> str:
    blob = json.dumps(configs, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _friendly_test_error(exc: BaseException, cfg: dict[str, Any]) -> str:
    """Turn a connection failure into a short message the user can act on."""
    import httpx

    seen: list[BaseException] = []
    current: Optional[BaseException] = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    for err in seen:
        if isinstance(err, httpx.HTTPStatusError):
            code = err.response.status_code
            if code in (401, 403):
                return (
                    "The server rejected the credentials (HTTP "
                    f"{code}). Check the token and the authentication method."
                )
            if code == 404:
                return "No MCP endpoint at this URL (HTTP 404). Check the URL."
            return f"The server returned an error (HTTP {code}). Try again later."
        if isinstance(err, httpx.TimeoutException):
            return "The server did not respond in time. Check that it is running."
        if isinstance(err, httpx.ConnectError):
            return (
                "Could not reach the server. Check the URL and that the server "
                "is running."
            )
        if isinstance(err, FileNotFoundError):
            command = cfg.get("command") or "the command"
            return f"Could not start {command}: command not found."
    if cfg.get("command"):
        return (
            "The command started but did not respond as an MCP server. "
            "Check the command and its arguments."
        )
    return "Connected, but the server did not respond as an MCP server."


def run_server_test(cfg: dict[str, Any]) -> dict[str, Any]:
    """Connect to one server and list its tools; never raises.

    Error messages have the token and the URL's query string removed.
    """
    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.loader import build_transport, filter_server_tools
    from openjarvis.tools.mcp_adapter import MCPToolProvider

    secrets = [cfg.get("token"), cfg.get("url")]
    client = None
    try:
        transport = build_transport(cfg, request_timeout=_TEST_TIMEOUT_SECONDS)
        if transport is None:
            return {"ok": False, "error": "Server has neither a URL nor a command"}
        client = MCPClient(transport)
        client.initialize()
        discovered = MCPToolProvider(client).discover()
        active = {t.spec.name for t in filter_server_tools(discovered, cfg)}
        return {
            "ok": True,
            "tools": [
                {
                    "name": t.spec.name,
                    "description": t.spec.description,
                    "active": t.spec.name in active,
                }
                for t in discovered
            ],
        }
    except Exception as exc:
        logger.info(
            "MCP server test failed: %s",
            _redact(f"{type(exc).__name__}: {exc}", secrets)[:500],
        )
        return {"ok": False, "error": _redact(_friendly_test_error(exc, cfg), secrets)}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.debug("Failed to close MCP test client", exc_info=True)


def create_mcp_router(
    *,
    config: Any = None,
    store: Optional[MCPServerStore] = None,
    tester: Callable[[dict[str, Any]], dict[str, Any]] = run_server_test,
) -> APIRouter:
    """Create the /v1/mcp router.

    ``config`` is the loaded JarvisConfig (``load_config()`` when omitted);
    ``store`` defaults to the global store next to that config.
    """
    from pathlib import Path

    from openjarvis.core.config import get_config_dir, load_config
    from openjarvis.mcp.store import default_store_root

    def _config() -> Any:
        return config if config is not None else load_config()

    if store is None:
        raw_dir = getattr(_config(), "_config_dir", None)
        config_dir = Path(raw_dir) if isinstance(raw_dir, (str, Path)) else None
        store = MCPServerStore(default_store_root(config_dir or get_config_dir()))
    mcp_store = store

    def _startup_state() -> str:
        try:
            return _fingerprint(mcp_store.runtime_configs())
        except (OSError, ValueError):
            return ""

    loaded_fingerprint = _startup_state()

    def _restart_required() -> bool:
        return _startup_state() != loaded_fingerprint

    def _config_servers() -> tuple[list[dict[str, Any]], Optional[str]]:
        from openjarvis.core.config import resolve_mcp_servers

        cfg = _config()
        raw = cfg.tools.mcp.servers
        if not raw:
            return [], None
        raw_dir = getattr(cfg, "_config_dir", None)
        config_dir = Path(raw_dir) if isinstance(raw_dir, (str, Path)) else None
        try:
            return resolve_mcp_servers(raw, config_dir or get_config_dir()), None
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            # The message may quote config content; keep it generic.
            logger.warning("Failed to parse [tools.mcp].servers: %s", exc)
            return [], "Could not parse [tools.mcp].servers in config.toml"

    def _store_call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except (OSError, ValueError) as exc:
            logger.warning("MCP server store error: %s", exc)
            raise HTTPException(500, "Could not read or write MCP server store")

    def _resolve_test_config(server_id: str) -> dict[str, Any]:
        if server_id.startswith(_CONFIG_ID_PREFIX):
            servers, _ = _config_servers()
            try:
                index = int(server_id[len(_CONFIG_ID_PREFIX) :])
                return servers[index]
            except (ValueError, IndexError):
                raise HTTPException(404, "MCP server not found") from None
        record = _store_call(lambda: mcp_store.get(server_id))
        if record is None:
            raise HTTPException(404, "MCP server not found")
        return to_runtime_config(record, mcp_store.token(server_id))

    router = APIRouter(prefix="/v1/mcp", tags=["mcp"])

    @router.get("/servers")
    def list_servers() -> dict[str, Any]:
        records = _store_call(mcp_store.list_servers)
        config_servers, config_error = _config_servers()
        return {
            "enabled": bool(_config().tools.mcp.enabled),
            "servers": [_gui_view(r, mcp_store) for r in records],
            "config_servers": [
                _config_view(i, s) for i, s in enumerate(config_servers)
            ],
            "config_error": config_error,
            "restart_required": _restart_required(),
        }

    @router.post("/servers", status_code=201)
    async def create_server(request: Request) -> dict[str, Any]:
        body: MCPServerIn = await _parse_body(request, MCPServerIn)
        token = body.token if body.auth_type != "none" else None
        record = _store_call(lambda: mcp_store.create(body.fields(), token=token))
        return {
            "server": _gui_view(record, mcp_store),
            "restart_required": _restart_required(),
        }

    @router.put("/servers/{server_id}")
    async def update_server(server_id: str, request: Request) -> dict[str, Any]:
        body: MCPServerIn = await _parse_body(request, MCPServerIn)
        token: Any = KEEP if body.token is None else body.token
        if body.auth_type == "none":
            token = None
        record = _store_call(
            lambda: mcp_store.update(server_id, body.fields(), token=token)
        )
        if record is None:
            raise HTTPException(404, "MCP server not found")
        return {
            "server": _gui_view(record, mcp_store),
            "restart_required": _restart_required(),
        }

    @router.delete("/servers/{server_id}")
    def delete_server(server_id: str) -> dict[str, Any]:
        if not _store_call(lambda: mcp_store.delete(server_id)):
            raise HTTPException(404, "MCP server not found")
        return {"deleted": True, "restart_required": _restart_required()}

    @router.post("/servers/test")
    async def test_draft(request: Request) -> dict[str, Any]:
        body: MCPServerTestIn = await _parse_body(request, MCPServerTestIn)
        token = body.token
        if token is None and body.id:
            token = _store_call(lambda: mcp_store.token(body.id or ""))
        record = body.fields()
        record.pop("id", None)
        return await _run_test(to_runtime_config(record, token))

    @router.post("/servers/{server_id}/test")
    async def test_server(server_id: str) -> dict[str, Any]:
        return await _run_test(_resolve_test_config(server_id))

    async def _run_test(cfg: dict[str, Any]) -> dict[str, Any]:
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(tester, cfg)

    return router


__all__ = ["MCPServerIn", "create_mcp_router", "run_server_test"]
