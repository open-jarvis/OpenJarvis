#!/usr/bin/env python3
"""Run OAuth flows for Google, Strava, and Spotify in sequence.

Usage:
    uv run python scripts/oauth_all.py [--google] [--strava] [--spotify]
    uv run python scripts/oauth_all.py   # runs all three
"""

from __future__ import annotations

import argparse
import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CONFIG_DIR = Path.home() / ".openjarvis" / "connectors"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CALLBACK_PORT = 8789
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

# ── Credentials (read from stored files, then env vars) ──────────────────────


def _load_creds(filename: str) -> Dict[str, str]:
    """Load client_id/client_secret from a stored credential file."""
    path = CONFIG_DIR / filename
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "client_id": data.get("client_id", ""),
                "client_secret": data.get("client_secret", ""),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {"client_id": "", "client_secret": ""}


_google = _load_creds("google.json")
GOOGLE_CLIENT_ID = os.environ.get("OPENJARVIS_GOOGLE_CLIENT_ID", "") or _google["client_id"]
GOOGLE_CLIENT_SECRET = os.environ.get("OPENJARVIS_GOOGLE_CLIENT_SECRET", "") or _google["client_secret"]

_strava = _load_creds("strava.json")
STRAVA_CLIENT_ID = os.environ.get("OPENJARVIS_STRAVA_CLIENT_ID", "") or _strava["client_id"]
STRAVA_CLIENT_SECRET = os.environ.get("OPENJARVIS_STRAVA_CLIENT_SECRET", "") or _strava["client_secret"]

_spotify = _load_creds("spotify.json")
SPOTIFY_CLIENT_ID = os.environ.get("OPENJARVIS_SPOTIFY_CLIENT_ID", "") or _spotify["client_id"]
SPOTIFY_CLIENT_SECRET = os.environ.get("OPENJARVIS_SPOTIFY_CLIENT_SECRET", "") or _spotify["client_secret"]

# ── Generic OAuth helpers ────────────────────────────────────────────────────


def _wait_for_code(port: int = CALLBACK_PORT, timeout: int = 120) -> str:
    """Start a localhost server and wait for the OAuth callback with ?code=."""
    auth_code: List[str] = []
    error: List[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params = parse_qs(urlparse(self.path).query)
            if "code" in params:
                auth_code.append(params["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Success!</h2>"
                    b"<p>You can close this tab.</p></body></html>"
                )
            else:
                error.append(params.get("error", ["unknown"])[0])
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Failed</h2></body></html>")

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = timeout
    while not auth_code and not error:
        server.handle_request()
    server.server_close()

    if error:
        raise RuntimeError(f"OAuth error: {error[0]}")
    if not auth_code:
        raise RuntimeError("OAuth timed out")
    return auth_code[0]


def _save(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    path.chmod(0o600)
    print(f"  Saved tokens to {path}")


# ── Google ───────────────────────────────────────────────────────────────────


def do_google() -> None:
    print("\n=== Google OAuth (Drive, Calendar, Contacts, Gmail, Tasks) ===")
    scopes = [
        "openid", "email", "profile",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/tasks.readonly",
    ]
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urlencode({
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
        })
    )
    print(f"  Opening browser...")
    webbrowser.open(url)
    code = _wait_for_code()

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    tokens = resp.json()

    payload = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in", 3600),
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
    }

    # Save to shared + all connector-specific files
    for name in ["google", "gdrive", "gcalendar", "gcontacts", "gmail", "google_tasks"]:
        _save(CONFIG_DIR / f"{name}.json", payload)

    print("  Google OAuth complete!")


# ── Strava ───────────────────────────────────────────────────────────────────


def do_strava() -> None:
    print("\n=== Strava OAuth ===")
    url = (
        "https://www.strava.com/oauth/authorize?"
        + urlencode({
            "client_id": STRAVA_CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "activity:read_all",
        })
    )
    print(f"  Opening browser...")
    webbrowser.open(url)
    code = _wait_for_code()

    resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    tokens = resp.json()

    payload = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
    }
    _save(CONFIG_DIR / "strava.json", payload)
    print("  Strava OAuth complete!")


# ── Spotify ──────────────────────────────────────────────────────────────────


def _make_self_signed_cert() -> tuple[str, str]:
    """Generate a temporary self-signed cert for localhost HTTPS."""
    import ssl
    import subprocess
    import tempfile

    cert_dir = Path(tempfile.mkdtemp())
    key_path = str(cert_dir / "key.pem")
    cert_path = str(cert_dir / "cert.pem")
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_path, "-out", cert_path,
            "-days", "1", "-nodes",
            "-subj", "/CN=localhost",
        ],
        capture_output=True, check=True,
    )
    return cert_path, key_path


def _wait_for_code_https(port: int = 8888, timeout: int = 120) -> str:
    """Like _wait_for_code but serves over HTTPS with a self-signed cert."""
    import ssl

    cert_path, key_path = _make_self_signed_cert()

    auth_code: List[str] = []
    error: List[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            params = parse_qs(urlparse(self.path).query)
            if "code" in params:
                auth_code.append(params["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Success!</h2>"
                    b"<p>You can close this tab.</p></body></html>"
                )
            else:
                error.append(params.get("error", ["unknown"])[0])
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Failed</h2></body></html>")

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.timeout = timeout

    while not auth_code and not error:
        server.handle_request()
    server.server_close()

    if error:
        raise RuntimeError(f"OAuth error: {error[0]}")
    if not auth_code:
        raise RuntimeError("OAuth timed out")
    return auth_code[0]


def do_spotify() -> None:
    print("\n=== Spotify OAuth ===")
    spotify_port = 8888
    spotify_redirect = f"http://127.0.0.1:{spotify_port}/callback"
    url = (
        "https://accounts.spotify.com/authorize?"
        + urlencode({
            "client_id": SPOTIFY_CLIENT_ID,
            "redirect_uri": spotify_redirect,
            "response_type": "code",
            "scope": "user-read-recently-played",
        })
    )
    print(f"  Opening browser...")
    webbrowser.open(url)
    code = _wait_for_code(port=spotify_port)

    import base64
    auth_header = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()

    resp = httpx.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth_header}"},
        data={
            "code": code,
            "redirect_uri": spotify_redirect,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    tokens = resp.json()

    payload = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }
    _save(CONFIG_DIR / "spotify.json", payload)
    print("  Spotify OAuth complete!")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run OAuth flows for OpenJarvis connectors")
    parser.add_argument("--google", action="store_true", help="Only Google")
    parser.add_argument("--strava", action="store_true", help="Only Strava")
    parser.add_argument("--spotify", action="store_true", help="Only Spotify")
    args = parser.parse_args()

    run_all = not (args.google or args.strava or args.spotify)

    if run_all or args.google:
        do_google()
    if run_all or args.strava:
        do_strava()
    if run_all or args.spotify:
        do_spotify()

    print("\nDone! All OAuth flows complete.")
