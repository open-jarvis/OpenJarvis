"""Shared OAuth 2.0 helpers for all connectors.

Provides:
- ``OAuthProvider`` registry with configs for Google, Strava, Spotify
- Generic ``run_connector_oauth()`` that opens browser + catches callback
- URL builder, token persistence, and token cleanup utilities
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from openjarvis.core.config import DEFAULT_CONFIG_DIR

# ---------------------------------------------------------------------------
# Connector credentials directory
# ---------------------------------------------------------------------------

_CONNECTORS_DIR = DEFAULT_CONFIG_DIR / "connectors"

# ---------------------------------------------------------------------------
# OAuth provider registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthProvider:
    """Configuration for an OAuth 2.0 provider."""

    name: str  # "google", "strava", "spotify"
    display_name: str
    auth_endpoint: str
    token_endpoint: str
    scopes: List[str]
    setup_url: str  # URL where user creates OAuth credentials
    setup_hint: str  # One-line instruction for setup
    callback_port: int = 8789
    callback_host: str = "127.0.0.1"
    callback_path: str = "/callback"
    token_auth: str = "body"  # "body" or "basic"
    extra_auth_params: Dict[str, str] = field(default_factory=dict)
    # Which connector IDs this provider covers (one flow → all connected)
    connector_ids: Tuple[str, ...] = ()
    # Filenames in ~/.openjarvis/connectors/ to save tokens to
    credential_files: Tuple[str, ...] = ()


# Combined scopes for all Google connectors so a single OAuth consent
# authorises Drive, Calendar, Contacts, Gmail, and Tasks at once.
GOOGLE_ALL_SCOPES: List[str] = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

OAUTH_PROVIDERS: Dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        name="google",
        display_name="Google",
        auth_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        scopes=GOOGLE_ALL_SCOPES,
        setup_url="https://console.cloud.google.com/apis/credentials",
        setup_hint="Create an OAuth 2.0 Client ID (Desktop app type)",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
        connector_ids=(
            "gdrive",
            "gcalendar",
            "gcontacts",
            "gmail",
            "google_tasks",
        ),
        credential_files=(
            "google.json",
            "gdrive.json",
            "gcalendar.json",
            "gcontacts.json",
            "gmail.json",
            "google_tasks.json",
        ),
    ),
    "strava": OAuthProvider(
        name="strava",
        display_name="Strava",
        auth_endpoint="https://www.strava.com/oauth/authorize",
        token_endpoint="https://www.strava.com/oauth/token",
        scopes=["activity:read_all"],
        setup_url="https://www.strava.com/settings/api",
        setup_hint="Create an API Application (callback domain: localhost)",
        connector_ids=("strava",),
        credential_files=("strava.json",),
    ),
    "spotify": OAuthProvider(
        name="spotify",
        display_name="Spotify",
        auth_endpoint="https://accounts.spotify.com/authorize",
        token_endpoint="https://accounts.spotify.com/api/token",
        scopes=["user-read-recently-played"],
        setup_url="https://developer.spotify.com/dashboard",
        setup_hint=(
            "Create an app, add redirect URI: "
            "http://127.0.0.1:8888/callback"
        ),
        callback_port=8888,
        token_auth="basic",
        connector_ids=("spotify",),
        credential_files=("spotify.json",),
    ),
}


def get_provider_for_connector(connector_id: str) -> Optional[OAuthProvider]:
    """Return the OAuthProvider that covers *connector_id*, or ``None``."""
    for provider in OAUTH_PROVIDERS.values():
        if connector_id in provider.connector_ids:
            return provider
    return None


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------


def get_client_credentials(
    provider: OAuthProvider,
) -> Optional[Tuple[str, str]]:
    """Load stored client_id and client_secret for *provider*.

    Checks credential files in ``~/.openjarvis/connectors/`` and falls
    back to environment variables ``OPENJARVIS_{NAME}_CLIENT_ID`` and
    ``OPENJARVIS_{NAME}_CLIENT_SECRET``.
    """
    # Check credential files
    for filename in provider.credential_files:
        path = _CONNECTORS_DIR / filename
        tokens = load_tokens(str(path))
        if tokens and tokens.get("client_id") and tokens.get("client_secret"):
            return tokens["client_id"], tokens["client_secret"]

    # Check environment variables
    prefix = f"OPENJARVIS_{provider.name.upper()}"
    env_id = os.environ.get(f"{prefix}_CLIENT_ID", "")
    env_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "")
    if env_id and env_secret:
        return env_id, env_secret

    return None


def save_client_credentials(
    provider: OAuthProvider,
    client_id: str,
    client_secret: str,
) -> None:
    """Persist client credentials so the user never has to enter them again."""
    for filename in provider.credential_files:
        path = _CONNECTORS_DIR / filename
        existing = load_tokens(str(path)) or {}
        existing["client_id"] = client_id
        existing["client_secret"] = client_secret
        save_tokens(str(path), existing)


# ---------------------------------------------------------------------------
# Shared credentials file — one OAuth flow covers all Google connectors
# ---------------------------------------------------------------------------

_SHARED_GOOGLE_CREDENTIALS_PATH: str = str(
    _CONNECTORS_DIR / "google.json"
)

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_DEFAULT_REDIRECT_URI = "http://localhost:8789/callback"
_DEFAULT_SCOPES: List[str] = ["openid", "email", "profile"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_google_auth_url(
    client_id: str,
    redirect_uri: str = _DEFAULT_REDIRECT_URI,
    scopes: Optional[List[str]] = None,
) -> str:
    """Build a Google OAuth2 consent URL.

    Parameters
    ----------
    client_id:
        The OAuth 2.0 client ID from the Google Cloud Console.
    redirect_uri:
        Where Google should redirect after consent. Defaults to the local
        callback server at ``http://localhost:8789/callback``.
    scopes:
        List of OAuth scopes to request.  Defaults to
        ``["openid", "email", "profile"]``.

    Returns
    -------
    str
        Full consent URL including query string.
    """
    if scopes is None:
        scopes = _DEFAULT_SCOPES

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def resolve_google_credentials(connector_path: str) -> str:
    """Return the best available Google credentials file path.

    Checks the connector-specific file first, then falls back to the
    shared ``google.json``.  Returns *connector_path* if neither exists
    (so ``is_connected()`` correctly returns ``False``).
    """
    if Path(connector_path).exists():
        return connector_path
    if Path(_SHARED_GOOGLE_CREDENTIALS_PATH).exists():
        return _SHARED_GOOGLE_CREDENTIALS_PATH
    return connector_path


def load_tokens(path: str) -> Optional[Dict[str, Any]]:
    """Load OAuth tokens from a JSON file.

    Returns ``None`` if the file is missing, unreadable, or contains
    invalid JSON.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None


def save_tokens(path: str, tokens: Dict[str, Any]) -> None:
    """Persist *tokens* to *path* as JSON with owner-only (0o600) permissions.

    Creates parent directories as needed.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)


def delete_tokens(path: str) -> None:
    """Delete the credentials file at *path* if it exists."""
    p = Path(path)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Token exchange & full OAuth flow
# ---------------------------------------------------------------------------


def exchange_google_token(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str = _DEFAULT_REDIRECT_URI,
) -> Dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Parameters
    ----------
    code:
        The authorization code received from Google's consent redirect.
    client_id:
        OAuth 2.0 client ID.
    client_secret:
        OAuth 2.0 client secret.
    redirect_uri:
        Must match the redirect URI used when obtaining the auth code.

    Returns
    -------
    dict
        Token response containing ``access_token``, ``refresh_token``,
        ``token_type``, and ``expires_in``.
    """
    import httpx

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_oauth_flow(
    client_id: str,
    client_secret: str,
    scopes: List[str],
    credentials_path: str,
    redirect_uri: str = _DEFAULT_REDIRECT_URI,
) -> Dict[str, Any]:
    """Run the full OAuth flow: browser consent, callback, token exchange.

    Steps:

    1. Build consent URL
    2. Start localhost callback server
    3. Open browser to consent URL
    4. Wait for Google to redirect with ``?code=...``
    5. Exchange code for ``access_token`` + ``refresh_token``
    6. Save tokens to *credentials_path*
    7. Return the tokens dict

    Parameters
    ----------
    client_id:
        OAuth 2.0 client ID.
    client_secret:
        OAuth 2.0 client secret.
    scopes:
        List of OAuth scopes to request.
    credentials_path:
        Where to persist the resulting tokens.
    redirect_uri:
        Local callback URI.  Defaults to ``http://localhost:8789/callback``.

    Returns
    -------
    dict
        Token response from Google (``access_token``, ``refresh_token``, etc.).

    Raises
    ------
    RuntimeError
        If the user denies authorization or the callback times out.
    """
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    auth_url = build_google_auth_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
    )

    # Mutable containers used by the callback handler closure.
    auth_code: List[str] = []
    error: List[str] = []

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — required override name
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            if "code" in params:
                auth_code.append(params["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization successful!</h2>"
                    b"<p>You can close this tab and return to OpenJarvis.</p>"
                    b"</body></html>"
                )
            elif "error" in params:
                error.append(params["error"][0])
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization failed</h2>"
                    b"<p>Please try again.</p></body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # Suppress HTTP request logs

    # Parse port from redirect_uri
    port = int(urlparse(redirect_uri).port or 8789)

    # Kill any stale listener on the port before starting
    import socket

    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        test_sock.bind(("127.0.0.1", port))
        test_sock.close()
    except OSError:
        # Port in use — try to free it
        test_sock.close()
        import subprocess

        subprocess.run(
            ["lsof", "-t", "-i", f":{port}"],
            capture_output=True,
        )
        # Wait briefly and retry
        import time

        time.sleep(1)

    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 120  # 2 minute timeout

    # Open the consent page in the user's default browser
    webbrowser.open(auth_url)

    # Wait for the callback (blocking, with per-request timeout)
    while not auth_code and not error:
        server.handle_request()

    server.server_close()

    if error:
        raise RuntimeError(f"OAuth authorization failed: {error[0]}")
    if not auth_code:
        raise RuntimeError("OAuth authorization timed out")

    # Exchange the authorization code for tokens
    tokens = exchange_google_token(
        code=auth_code[0],
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )

    # Persist tokens together with client credentials (needed for refresh)
    token_payload = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in", 3600),
        "client_id": client_id,
        "client_secret": client_secret,
    }
    save_tokens(credentials_path, token_payload)

    # Also save to the shared Google credentials file so that all Google
    # connectors can use this token without a separate OAuth flow.
    if credentials_path != _SHARED_GOOGLE_CREDENTIALS_PATH:
        save_tokens(_SHARED_GOOGLE_CREDENTIALS_PATH, token_payload)

    return tokens


# ---------------------------------------------------------------------------
# Generic OAuth flow — works with any OAuthProvider
# ---------------------------------------------------------------------------


def _wait_for_callback_code(
    host: str = "127.0.0.1",
    port: int = 8789,
    path: str = "/callback",
    timeout: int = 120,
) -> str:
    """Start a localhost HTTP server and wait for ``?code=`` on *path*.

    Returns the authorization code received from the OAuth redirect.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    auth_code: List[str] = []
    error: List[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            params = parse_qs(urlparse(self.path).query)
            if "code" in params:
                auth_code.append(params["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:system-ui;text-align:center;"
                    b"padding:60px'>"
                    b"<h2 style='color:#22c55e'>Connected!</h2>"
                    b"<p>You can close this tab and return to OpenJarvis.</p>"
                    b"</body></html>"
                )
            elif "error" in params:
                error.append(params.get("error", ["unknown"])[0])
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:system-ui;text-align:center;"
                    b"padding:60px'>"
                    b"<h2 style='color:#ef4444'>Authorization Failed</h2>"
                    b"<p>Please close this tab and try again.</p>"
                    b"</body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *_args: Any) -> None:
            pass

    # Ensure port is free
    import socket

    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        test_sock.bind((host, port))
    except OSError:
        pass
    finally:
        test_sock.close()

    import time

    time.sleep(0.3)

    server = HTTPServer((host, port), _Handler)
    server.timeout = timeout

    while not auth_code and not error:
        server.handle_request()
    server.server_close()

    if error:
        raise RuntimeError(f"OAuth authorization denied: {error[0]}")
    if not auth_code:
        raise RuntimeError("OAuth callback timed out")
    return auth_code[0]


def _exchange_token(
    provider: OAuthProvider,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    """Exchange an authorization *code* for tokens using *provider* config."""
    import httpx

    data: Dict[str, str] = {
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    headers: Dict[str, str] = {}

    if provider.token_auth == "basic":
        creds = base64.b64encode(
            f"{client_id}:{client_secret}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {creds}"
    else:
        data["client_id"] = client_id
        data["client_secret"] = client_secret

    resp = httpx.post(
        provider.token_endpoint, data=data, headers=headers, timeout=30.0
    )
    resp.raise_for_status()
    return resp.json()


def run_connector_oauth(
    connector_id: str,
    client_id: str = "",
    client_secret: str = "",
) -> Dict[str, Any]:
    """Run a complete OAuth flow for *connector_id*.

    1. Look up the ``OAuthProvider``
    2. Resolve client credentials (arg → stored → env)
    3. Build auth URL and open the user's browser
    4. Start localhost callback server and wait for the code
    5. Exchange the code for tokens
    6. Save tokens to all relevant credential files

    Returns the raw token response dict.
    """
    import webbrowser

    provider = get_provider_for_connector(connector_id)
    if provider is None:
        raise ValueError(f"No OAuth provider configured for '{connector_id}'")

    # Resolve credentials
    if not (client_id and client_secret):
        creds = get_client_credentials(provider)
        if creds:
            client_id, client_secret = creds
    if not (client_id and client_secret):
        raise RuntimeError(
            f"No client credentials for {provider.display_name}. "
            f"Set them up at: {provider.setup_url}"
        )

    redirect_uri = (
        f"http://{provider.callback_host}:{provider.callback_port}"
        f"{provider.callback_path}"
    )

    # Build auth URL
    params: Dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(provider.scopes),
        **provider.extra_auth_params,
    }
    auth_url = f"{provider.auth_endpoint}?{urlencode(params)}"

    # Open browser and wait for callback
    webbrowser.open(auth_url)
    code = _wait_for_callback_code(
        host=provider.callback_host,
        port=provider.callback_port,
        path=provider.callback_path,
    )

    # Exchange code for tokens
    tokens = _exchange_token(
        provider, code, client_id, client_secret, redirect_uri
    )

    # Build payload with client credentials included (needed for refresh)
    payload = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in", 3600),
        "client_id": client_id,
        "client_secret": client_secret,
    }

    # Save to all credential files for this provider
    for filename in provider.credential_files:
        save_tokens(str(_CONNECTORS_DIR / filename), payload)

    return tokens
