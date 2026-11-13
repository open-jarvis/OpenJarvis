"""FastAPI router for /v1/mcp/servers — global MCP server management.

GUI-managed servers live in :class:`openjarvis.mcp.store.MCPServerStore`.
Servers declared in ``config.toml`` are listed read-only (and can be
tested) but never written.

Secrets are write-only: responses carry ``has_token`` and ``env_set``
(variable names only) instead of the token and environment values, and
request bodies are parsed by hand so validation errors never echo the
submitted input (FastAPI's default 422 body includes it).

OAuth servers are signed in to from the browser: ``.../oauth/start``
returns the authorization URL and ``/v1/mcp/oauth/callback`` completes
the code exchange (see :mod:`openjarvis.mcp.oauth`).

MCP tools are discovered once at server start-up, so changes made here
take effect after a restart; responses report ``restart_required``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Callable, Dict, List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from openjarvis.mcp.store import KEEP, MCPServerStore, to_runtime_config

logger = logging.getLogger(__name__)

_CONFIG_ID_PREFIX = "config-"
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Headers the transport sets itself; a token must not override them.
_RESERVED_HEADERS = {
    "accept",
    "content-type",
    "content-length",
    "host",
    "mcp-session-id",
}
_OAUTH_RESERVED_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "state",
    "code_challenge",
    "code_challenge_method",
    "resource",
    "scope",
)
_TEST_TIMEOUT_SECONDS = 20.0
_MAX_BODY_BYTES = 64 * 1024


class MCPServerIn(BaseModel):
    """Create/update payload for a GUI-managed MCP server."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    transport: Literal["http", "stdio"]
    url: Optional[str] = Field(default=None, max_length=2048)
    auth_type: Literal["none", "bearer", "header", "oauth"] = "none"
    auth_header: Optional[str] = Field(default=None, max_length=100)
    # Write-only. On update: omitted/null keeps the stored token, "" clears.
    token: Optional[str] = Field(default=None, max_length=8192)
    command: Optional[str] = Field(default=None, max_length=1024)
    args: List[str] = Field(default_factory=list, max_length=100)
    # Names of secret environment variables for stdio servers.
    env_names: List[str] = Field(default_factory=list, max_length=50)
    # Write-only values keyed by name. On update, omitted names keep their
    # stored value and "" clears one.
    env: Optional[Dict[str, str]] = Field(default=None, max_length=50)
    # OAuth: leave the client ID empty to register one dynamically.
    oauth_client_id: Optional[str] = Field(default=None, max_length=512)
    # Write-only. On update: omitted/null keeps the stored secret, "" clears.
    oauth_client_secret: Optional[str] = Field(default=None, max_length=2048)
    oauth_scopes: List[str] = Field(default_factory=list, max_length=50)
    # Extra authorization-request parameters, e.g. to ask for a refresh token.
    oauth_auth_params: Dict[str, str] = Field(default_factory=dict, max_length=10)
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
            if self.auth_type == "oauth":
                self.token = None
                self.oauth_client_id = self.oauth_client_id or None
                self.oauth_scopes = [s for s in self.oauth_scopes if s.strip()]
                reserved = set(_OAUTH_RESERVED_PARAMS)
                if any(k in reserved for k in self.oauth_auth_params):
                    raise ValueError("oauth_auth_params cannot override core params")
            else:
                self._clear_oauth()
            self.command = None
            self.args = []
            self.env_names = []
            self.env = None
        else:
            if not self.command:
                raise ValueError("command is required for stdio servers")
            names = list(dict.fromkeys(n.strip() for n in self.env_names))
            if not all(_ENV_NAME_RE.match(n) for n in names):
                raise ValueError("env_names must be valid environment variable names")
            self.env_names = names
            for key, value in (self.env or {}).items():
                if key not in names:
                    raise ValueError("env keys must be listed in env_names")
                if len(value) > 8192:
                    raise ValueError("env values must be at most 8192 characters")
            self.url = None
            self.auth_type = "none"
            self.auth_header = None
            self._clear_oauth()
        self.include_tools = [t for t in (s.strip() for s in self.include_tools) if t]
        self.exclude_tools = [t for t in (s.strip() for s in self.exclude_tools) if t]
        return self

    def _clear_oauth(self) -> None:
        self.oauth_client_id = None
        self.oauth_client_secret = None
        self.oauth_scopes = []
        self.oauth_auth_params = {}

    def fields(self) -> dict[str, Any]:
        return self.model_dump(exclude={"token", "env", "oauth_client_secret"})


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
        secrets: list[Optional[str]] = [
            data.get("token") if isinstance(data.get("token"), str) else None
        ]
        if isinstance(data.get("oauth_client_secret"), str):
            secrets.append(data["oauth_client_secret"])
        if isinstance(data.get("env"), dict):
            secrets += [v for v in data["env"].values() if isinstance(v, str)]
        errors = [
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": _redact(str(err.get("msg", "invalid value")), secrets),
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
        "env_names": list(record.get("env_names") or []),
        "env_set": store.env_set(record.get("id", "")),
        **_oauth_view(record, store),
        "include_tools": list(record.get("include_tools") or []),
        "exclude_tools": list(record.get("exclude_tools") or []),
        "enabled": bool(record.get("enabled", True)),
        "source": "gui",
        "read_only": False,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _oauth_view(
    record: dict[str, Any], store: Optional[MCPServerStore]
) -> dict[str, Any]:
    status = None
    if record.get("auth_type") == "oauth" and store is not None:
        from openjarvis.mcp.oauth import is_expired

        server_id = record.get("id", "")
        tokens = store.oauth_tokens(server_id)
        if not tokens:
            status = "signed_out"
        elif is_expired(tokens) and not tokens.get("refresh_token"):
            status = "expired"
        else:
            status = "connected"
    return {
        "oauth_client_id": record.get("oauth_client_id"),
        "has_client_secret": bool(
            store and record.get("id") and store.oauth_client_secret(record["id"])
        ),
        "oauth_scopes": list(record.get("oauth_scopes") or []),
        "oauth_auth_params": dict(record.get("oauth_auth_params") or {}),
        "oauth_status": status,
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
        "env_names": [],
        "env_set": [],
        **_oauth_view({}, None),
        "include_tools": list(cfg.get("include_tools") or []),
        "exclude_tools": list(cfg.get("exclude_tools") or []),
        "enabled": True,
        "source": "config",
        "read_only": True,
    }


def _fingerprint(configs: list[dict[str, Any]]) -> str:
    blob = json.dumps(configs, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _server_reason(response: Any) -> str:
    """Short human-readable reason from an error response, if it has one.

    Reads the standard places: a JSON ``error.message`` / ``message`` /
    ``error_description``, or ``error_description`` in ``WWW-Authenticate``.
    """
    reason = ""
    try:
        data = response.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            reason = str(error.get("message") or "")
        reason = reason or str(
            data.get("error_description") or data.get("message") or ""
        )
    if not reason:
        header = response.headers.get("www-authenticate", "")
        match = re.search(r'error_description="([^"]*)"', header)
        reason = match.group(1) if match else ""
    reason = " ".join(reason.split())
    return reason[:300] + ("…" if len(reason) > 300 else "")


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
            reason = _server_reason(err.response)
            if code in (401, 403) and "oauth_connected" in cfg:
                if not cfg.get("oauth_connected"):
                    return "Not signed in. Sign in to this server first."
                if code == 403 and reason:
                    return f"The server refused access (HTTP 403): {reason}"
                return f"The server rejected the sign-in (HTTP {code}). Sign in again."
            if code == 403 and reason:
                return f"The server refused access (HTTP 403): {reason}"
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


def _oauth_secrets(cfg: dict[str, Any]) -> list[Optional[str]]:
    """Stored OAuth tokens/secret for ``cfg``, so errors can be redacted."""
    from pathlib import Path

    if not (cfg.get("oauth_store_root") and cfg.get("id")):
        return []
    store = MCPServerStore(Path(cfg["oauth_store_root"]))
    server_id = cfg["id"]
    try:
        tokens = store.oauth_tokens(server_id) or {}
        values = [store.oauth_client_secret(server_id)]
    except (OSError, ValueError):
        return []
    keys = ("access_token", "refresh_token", "client_secret")
    return values + [tokens.get(k) for k in keys]


def run_server_test(cfg: dict[str, Any]) -> dict[str, Any]:
    """Connect to one server and list its tools; never raises.

    Error messages have the token and the URL's query string removed.
    """
    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.loader import build_transport, filter_server_tools
    from openjarvis.tools.mcp_adapter import MCPToolProvider

    secrets = [cfg.get("token"), cfg.get("url"), *(cfg.get("env") or {}).values()]
    secrets += _oauth_secrets(cfg)
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
        # Read again: a refresh during the test may have stored new tokens.
        secrets += _oauth_secrets(cfg)
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
        return _runtime(record)

    def _runtime(record: dict[str, Any]) -> dict[str, Any]:
        server_id = record.get("id", "")
        return to_runtime_config(
            record,
            mcp_store.token(server_id),
            mcp_store.env(server_id),
            oauth_root=mcp_store.root,
            oauth_connected=mcp_store.oauth_tokens(server_id) is not None,
        )

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
        record = _store_call(
            lambda: mcp_store.create(
                body.fields(),
                token=token,
                env=body.env,
                oauth_client_secret=body.oauth_client_secret,
            )
        )
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
            lambda: mcp_store.update(
                server_id,
                body.fields(),
                token=token,
                env=body.env,
                oauth_client_secret=(
                    KEEP
                    if body.oauth_client_secret is None
                    else body.oauth_client_secret
                ),
            )
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
        env = dict(body.env or {})
        if body.id:
            if token is None:
                token = _store_call(lambda: mcp_store.token(body.id or ""))
            stored = _store_call(lambda: mcp_store.env(body.id or ""))
            env = {**stored, **env}
        record = body.fields()
        record.pop("id", None)
        cfg = to_runtime_config(record, token, env)
        if body.auth_type == "oauth":
            # Reuse a saved sign-in only when the draft still points at it.
            saved = (
                _store_call(lambda: mcp_store.get(body.id or "")) if body.id else None
            )
            same = saved is not None and all(
                saved.get(k) == record.get(k)
                for k in ("url", "auth_type", "oauth_client_id")
            )
            cfg = _runtime({**record, "id": body.id}) if same else cfg
            cfg.setdefault("oauth_connected", False)
        return await _run_test(cfg)

    @router.post("/servers/{server_id}/test")
    async def test_server(server_id: str) -> dict[str, Any]:
        return await _run_test(_resolve_test_config(server_id))

    async def _run_test(cfg: dict[str, Any]) -> dict[str, Any]:
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(tester, cfg)

    # -- OAuth sign-in ------------------------------------------------------

    from openjarvis.mcp import oauth as mcp_oauth

    pending = mcp_oauth.PendingSignIns()

    def _redirect_uri(request: Request) -> str:
        configured = getattr(_config().tools.mcp, "oauth_redirect_uri", "") or ""
        if configured:
            return configured
        base = str(request.base_url).rstrip("/")
        # Behind a local reverse proxy the forwarded scheme can be https
        # while this server only speaks http on loopback; the browser
        # reaches the callback directly, so use the socket address.
        server = request.scope.get("server")
        if urlparse(base).hostname in ("127.0.0.1", "localhost", "::1") and server:
            host, port = server[0], server[1]
            host = f"[{host}]" if ":" in str(host) else host
            base = f"http://{host}:{port}"
        return f"{base}/v1/mcp/oauth/callback"

    @router.get("/oauth/redirect-uri")
    def oauth_redirect_uri(request: Request) -> dict[str, Any]:
        return {"redirect_uri": _redirect_uri(request)}

    @router.post("/servers/{server_id}/oauth/start")
    async def oauth_start(server_id: str, request: Request) -> dict[str, Any]:
        from starlette.concurrency import run_in_threadpool

        record = _store_call(lambda: mcp_store.get(server_id))
        if record is None:
            raise HTTPException(404, "MCP server not found")
        if record.get("auth_type") != "oauth":
            raise HTTPException(400, "This server does not use OAuth sign-in")
        redirect_uri = _redirect_uri(request)
        client_id = record.get("oauth_client_id")
        client_secret = mcp_store.oauth_client_secret(server_id)

        def _prepare() -> str:
            discovery = mcp_oauth.discover(record["url"])
            nonlocal client_id, client_secret
            if not client_id:
                if not discovery.registration_endpoint:
                    raise mcp_oauth.OAuthError(
                        "This server needs an OAuth client you create yourself. "
                        "Enter its client ID and secret, then sign in."
                    )
                registered = mcp_oauth.register_client(
                    discovery.registration_endpoint, redirect_uri
                )
                client_id = registered["client_id"]
                client_secret = registered.get("client_secret")
            sign_in = mcp_oauth.PendingSignIn(
                server_id=server_id,
                verifier="",
                redirect_uri=redirect_uri,
                discovery=discovery,
                client_id=client_id,
                client_secret=client_secret,
            )
            scopes = list(record.get("oauth_scopes") or []) or discovery.scopes
            return mcp_oauth.start_sign_in(
                sign_in, pending, scopes, record.get("oauth_auth_params") or {}
            )

        try:
            url = await run_in_threadpool(_prepare)
        except mcp_oauth.OAuthError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"authorization_url": url, "redirect_uri": redirect_uri}

    @router.get("/oauth/callback", response_class=HTMLResponse)
    async def oauth_callback(request: Request) -> HTMLResponse:
        from starlette.concurrency import run_in_threadpool

        params = request.query_params
        sign_in = pending.pop(params.get("state") or "")
        if sign_in is None:
            return _callback_page(False, "This sign-in link expired. Start again.")
        if params.get("error"):
            return _callback_page(False, "Sign-in was cancelled or refused.")
        code = params.get("code")
        if not code:
            return _callback_page(False, "The authorization server sent no code.")
        try:
            tokens = await run_in_threadpool(mcp_oauth.exchange_code, sign_in, code)
        except mcp_oauth.OAuthError as exc:
            return _callback_page(False, str(exc))
        if _store_call(lambda: mcp_store.get(sign_in.server_id)) is None:
            return _callback_page(False, "The MCP server was deleted.")
        _store_call(lambda: mcp_store.set_oauth_tokens(sign_in.server_id, tokens))
        return _callback_page(True, "Signed in. You can close this window.")

    @router.post("/servers/{server_id}/oauth/sign-out")
    def oauth_sign_out(server_id: str) -> dict[str, Any]:
        if _store_call(lambda: mcp_store.get(server_id)) is None:
            raise HTTPException(404, "MCP server not found")
        _store_call(lambda: mcp_store.set_oauth_tokens(server_id, None))
        return {"signed_out": True, "restart_required": _restart_required()}

    return router


def _callback_page(ok: bool, message: str) -> HTMLResponse:
    """Small page shown in the sign-in window; never includes a token."""
    import html

    status = "ok" if ok else "error"
    body = f"""<!doctype html><html><head><meta charset="utf-8">
<title>OpenJarvis sign-in</title></head>
<body style="font-family:system-ui;padding:2rem">
<p>{html.escape(message)}</p>
<script>
try {{ window.opener && window.opener.postMessage(
  {{ type: "openjarvis-mcp-oauth", status: "{status}" }}, "*"); }} catch (e) {{}}
{"setTimeout(function(){ window.close(); }, 800);" if ok else ""}
</script></body></html>"""
    return HTMLResponse(
        body,
        status_code=200 if ok else 400,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


__all__ = ["MCPServerIn", "create_mcp_router", "run_server_test"]
