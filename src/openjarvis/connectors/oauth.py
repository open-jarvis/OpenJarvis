"""Shared OAuth 2.0 helpers for Google connectors.

Provides URL builder, token persistence, and token cleanup utilities
that are reused by gmail, drive, calendar, and contacts connectors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Google OAuth endpoints / defaults
# ---------------------------------------------------------------------------

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
    save_tokens(
        credentials_path,
        {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "token_type": tokens.get("token_type", "Bearer"),
            "expires_in": tokens.get("expires_in", 3600),
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )

    return tokens
