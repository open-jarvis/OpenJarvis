"""OAuth sign-in for remote MCP servers (MCP authorization spec).

Implements the client side of the MCP authorization flow, with nothing
specific to any provider:

1. Discover the server's protected-resource metadata (RFC 9728) from the
   ``WWW-Authenticate`` header of a 401, or from its well-known URL.
2. Fetch the authorization server's metadata (RFC 8414, or OpenID
   Connect discovery).
3. Register a client dynamically (RFC 7591) when the authorization
   server supports it; otherwise use a client ID/secret the user created.
4. Authorization code flow with PKCE (S256) and a single-use ``state``,
   sending the ``resource`` indicator (RFC 8707).
5. Refresh the access token when it expires.

Tokens and client secrets are stored in the owner-only ``secrets.json``
of :class:`openjarvis.mcp.store.MCPServerStore` and never returned.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

_HTTP_TIMEOUT = 15.0
_STATE_TTL_SECONDS = 600
# Refresh this many seconds before the access token expires.
_EXPIRY_MARGIN_SECONDS = 60


class OAuthError(Exception):
    """A sign-in step failed. The message is safe to show to the user."""


def _http() -> Any:
    import httpx

    return httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=False)


def _get_json(client: Any, url: str) -> Optional[dict[str, Any]]:
    try:
        res = client.get(url, headers={"Accept": "application/json"})
    except Exception:
        return None
    if res.status_code != 200:
        return None
    try:
        data = res.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _well_known(base: str, suffix: str) -> list[str]:
    """Path-inserted well-known URL first, then the root one."""
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    urls = [f"{origin}/.well-known/{suffix}{path}"] if path else []
    urls.append(f"{origin}/.well-known/{suffix}")
    return urls


_RESOURCE_METADATA_RE = re.compile(r'resource_metadata="([^"]+)"')
_SCOPE_RE = re.compile(r'scope="([^"]*)"')


def _check_https(url: str, label: str) -> None:
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise OAuthError(f"The {label} must use https.")


@dataclass
class Discovery:
    resource: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str]
    scopes: list[str] = field(default_factory=list)


def discover(server_url: str, client: Any = None) -> Discovery:
    """Find the authorization server for an MCP server URL."""
    owns = client is None
    client = client or _http()
    try:
        return _discover(server_url, client)
    finally:
        if owns:
            client.close()


def _discover(server_url: str, client: Any) -> Discovery:
    metadata_urls: list[str] = []
    challenge_scope: Optional[str] = None
    try:
        res = client.post(
            server_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "openjarvis", "version": "1"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        header = res.headers.get("www-authenticate", "") if res.status_code else ""
        match = _RESOURCE_METADATA_RE.search(header)
        if match:
            metadata_urls.append(match.group(1))
        scope_match = _SCOPE_RE.search(header)
        if scope_match:
            challenge_scope = scope_match.group(1)
    except Exception:
        raise OAuthError(
            "Could not reach the server. Check the URL and that the server is running."
        ) from None
    metadata_urls += _well_known(server_url, "oauth-protected-resource")

    resource_meta = None
    for url in metadata_urls:
        resource_meta = _get_json(client, url)
        if resource_meta and resource_meta.get("authorization_servers"):
            break
    if not resource_meta or not resource_meta.get("authorization_servers"):
        raise OAuthError(
            "This server does not publish OAuth metadata, so it cannot be "
            "signed in to here. Use a token instead if the server supports one."
        )
    issuer = str(resource_meta["authorization_servers"][0])
    _check_https(issuer, "authorization server")

    as_meta = None
    for url in _well_known(issuer, "oauth-authorization-server") + _well_known(
        issuer, "openid-configuration"
    ):
        as_meta = _get_json(client, url)
        if as_meta and as_meta.get("authorization_endpoint"):
            break
    if not as_meta or not as_meta.get("token_endpoint"):
        raise OAuthError("Could not read the authorization server's metadata.")
    methods = as_meta.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise OAuthError("The authorization server does not support PKCE (S256).")
    for key in ("authorization_endpoint", "token_endpoint"):
        _check_https(str(as_meta[key]), key.replace("_", " "))

    scopes = (
        challenge_scope.split()
        if challenge_scope
        else [str(s) for s in resource_meta.get("scopes_supported") or []]
    )
    return Discovery(
        resource=str(resource_meta.get("resource") or server_url),
        issuer=issuer,
        authorization_endpoint=str(as_meta["authorization_endpoint"]),
        token_endpoint=str(as_meta["token_endpoint"]),
        registration_endpoint=as_meta.get("registration_endpoint"),
        scopes=scopes,
    )


def register_client(
    registration_endpoint: str, redirect_uri: str, client: Any = None
) -> dict[str, Any]:
    """Dynamic client registration (RFC 7591)."""
    _check_https(registration_endpoint, "registration endpoint")
    owns = client is None
    client = client or _http()
    try:
        res = client.post(
            registration_endpoint,
            json={
                "client_name": "OpenJarvis",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
    except Exception:
        raise OAuthError("Could not register with the authorization server.") from None
    finally:
        if owns:
            client.close()
    data = res.json() if res.status_code in (200, 201) else {}
    if not isinstance(data, dict) or not data.get("client_id"):
        raise OAuthError(
            "The authorization server refused client registration. "
            "Create an OAuth client yourself and enter its client ID."
        )
    return {"client_id": data["client_id"], "client_secret": data.get("client_secret")}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class PendingSignIn:
    server_id: str
    verifier: str
    redirect_uri: str
    discovery: Discovery
    client_id: str
    client_secret: Optional[str]
    created: float = field(default_factory=time.time)


class PendingSignIns:
    """Single-use ``state`` values for sign-ins in progress (in memory)."""

    def __init__(self) -> None:
        self._items: dict[str, PendingSignIn] = {}
        self._lock = threading.Lock()

    def add(self, pending: PendingSignIn) -> str:
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._prune()
            self._items[state] = pending
        return state

    def pop(self, state: str) -> Optional[PendingSignIn]:
        with self._lock:
            self._prune()
            return self._items.pop(state, None)

    def _prune(self) -> None:
        now = time.time()
        for key in [
            k for k, v in self._items.items() if now - v.created > _STATE_TTL_SECONDS
        ]:
            del self._items[key]


def authorization_url(
    pending: PendingSignIn,
    state: str,
    challenge: str,
    scopes: list[str],
    extra_params: Optional[dict[str, str]] = None,
) -> str:
    params = {
        **(extra_params or {}),
        "response_type": "code",
        "client_id": pending.client_id,
        "redirect_uri": pending.redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": pending.discovery.resource,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    endpoint = pending.discovery.authorization_endpoint
    sep = "&" if urlparse(endpoint).query else "?"
    return f"{endpoint}{sep}{urlencode(params)}"


def start_sign_in(
    pending: PendingSignIn,
    pending_store: PendingSignIns,
    scopes: list[str],
    extra_params: Optional[dict[str, str]] = None,
) -> str:
    """Register ``pending`` and return the URL to send the user to."""
    verifier, challenge = _pkce()
    pending.verifier = verifier
    state = pending_store.add(pending)
    return authorization_url(pending, state, challenge, scopes, extra_params)


def _token_request(
    token_endpoint: str,
    data: dict[str, str],
    client_id: str,
    client_secret: Optional[str],
    client: Any = None,
) -> dict[str, Any]:
    owns = client is None
    client = client or _http()
    body = {**data, "client_id": client_id}
    if client_secret:
        body["client_secret"] = client_secret
    try:
        res = client.post(
            token_endpoint, data=body, headers={"Accept": "application/json"}
        )
    except Exception:
        raise OAuthError("Could not reach the authorization server.") from None
    finally:
        if owns:
            client.close()
    try:
        payload = res.json()
    except ValueError:
        payload = {}
    if res.status_code != 200 or not payload.get("access_token"):
        code = payload.get("error") if isinstance(payload, dict) else None
        if code == "invalid_client":
            raise OAuthError("The client ID or secret was rejected.")
        if code == "invalid_grant":
            raise OAuthError("The sign-in expired or was revoked. Sign in again.")
        raise OAuthError("The authorization server did not return a token.")
    return payload


def token_record(payload: dict[str, Any], previous: Optional[dict] = None) -> dict:
    """Store-ready token fields from a token response."""
    record = dict(previous or {})
    record["access_token"] = payload["access_token"]
    if payload.get("refresh_token"):
        record["refresh_token"] = payload["refresh_token"]
    expires_in = payload.get("expires_in")
    record["expires_at"] = (
        time.time() + float(expires_in)
        if isinstance(expires_in, (int, float))
        else None
    )
    return record


def exchange_code(pending: PendingSignIn, code: str, client: Any = None) -> dict:
    payload = _token_request(
        pending.discovery.token_endpoint,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "code_verifier": pending.verifier,
            "resource": pending.discovery.resource,
        },
        pending.client_id,
        pending.client_secret,
        client,
    )
    record = token_record(payload)
    record.update(
        token_endpoint=pending.discovery.token_endpoint,
        client_id=pending.client_id,
        resource=pending.discovery.resource,
    )
    if pending.client_secret:
        record["client_secret"] = pending.client_secret
    return record


def refresh(record: dict[str, Any], client: Any = None) -> dict[str, Any]:
    if not record.get("refresh_token"):
        raise OAuthError("The sign-in expired. Sign in again.")
    payload = _token_request(
        record["token_endpoint"],
        {
            "grant_type": "refresh_token",
            "refresh_token": record["refresh_token"],
            "resource": record.get("resource") or "",
        },
        record["client_id"],
        record.get("client_secret"),
        client,
    )
    return token_record(payload, record)


def is_expired(record: dict[str, Any]) -> bool:
    expires_at = record.get("expires_at")
    return (
        bool(expires_at) and time.time() >= float(expires_at) - _EXPIRY_MARGIN_SECONDS
    )


class OAuthTokenProvider:
    """Return a valid access token for one stored server, refreshing it."""

    def __init__(self, store: Any, server_id: str) -> None:
        self._store = store
        self._server_id = server_id
        self._lock = threading.Lock()

    def __call__(self, force_refresh: bool = False) -> Optional[str]:
        with self._lock:
            record = self._store.oauth_tokens(self._server_id)
            if not record:
                return None
            if force_refresh or is_expired(record):
                try:
                    record = refresh(record)
                except OAuthError:
                    return None if is_expired(record) else record.get("access_token")
                self._store.set_oauth_tokens(self._server_id, record)
            return record.get("access_token")


__all__ = [
    "Discovery",
    "OAuthError",
    "OAuthTokenProvider",
    "PendingSignIn",
    "PendingSignIns",
    "discover",
    "exchange_code",
    "is_expired",
    "refresh",
    "register_client",
    "start_sign_in",
]
