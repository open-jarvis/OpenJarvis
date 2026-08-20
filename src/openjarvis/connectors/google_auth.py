"""Shared Google OAuth helpers: access token read + one-shot 401 refresh.

All Google connectors (Gmail, Calendar, Contacts, Drive, Tasks) authenticate
with the same OAuth flow and store identical token payloads at
``~/.openjarvis/connectors/*.json`` — typically a shared ``google.json`` file
plus per-product copies. They all need the same refresh-on-401 behavior, so
the wrapper lives here instead of being duplicated per connector.

Use ``call_with_refresh(api_fn, credentials_path, *args, **kwargs)`` around
any token-taking API helper. On a 401 the wrapper exchanges the stored
``refresh_token`` for a new ``access_token``, updates the credentials file,
and retries the call once. All other status codes propagate.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

import httpx

from openjarvis.connectors.oauth import load_tokens, save_tokens

logger = logging.getLogger(__name__)


_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleAuthError(RuntimeError):
    """Raised when Google credentials are missing or refresh-token grant fails."""


def current_access_token(credentials_path: str) -> str:
    """Return the current access token from the credentials file (empty if absent)."""
    tokens = load_tokens(credentials_path) or {}
    return tokens.get("access_token", tokens.get("token", ""))


def refresh_access_token(credentials_path: str) -> str:
    """Exchange the stored refresh_token for a fresh access_token and persist it.

    Returns the new access_token. Raises :class:`GoogleAuthError` when the
    credentials file is missing, lacks a refresh_token / client credentials,
    or when Google rejects the refresh grant (e.g. the refresh_token has been
    revoked and the user needs to re-authenticate).
    """
    tokens = load_tokens(credentials_path)
    if not tokens:
        raise GoogleAuthError(
            f"No credentials at {credentials_path}; re-run the connector OAuth flow."
        )
    refresh_token = tokens.get("refresh_token", "")
    client_id = tokens.get("client_id", "")
    client_secret = tokens.get("client_secret", "")
    if not (refresh_token and client_id and client_secret):
        raise GoogleAuthError(
            "Stored Google credentials are missing refresh_token / client_id / "
            "client_secret; re-run the connector OAuth flow to mint a full token."
        )

    resp = httpx.post(
        _GOOGLE_TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise GoogleAuthError(
            f"Google token refresh failed ({resp.status_code}): {resp.text[:200]}"
        )
    payload = resp.json()
    new_token = payload.get("access_token", "")
    if not new_token:
        raise GoogleAuthError(
            "Google token refresh returned 200 but no access_token in payload."
        )

    tokens["access_token"] = new_token
    # Keep the legacy "token" key in sync for older code paths that read it.
    tokens["token"] = new_token
    if "expires_in" in payload:
        tokens["expires_in"] = payload["expires_in"]
    save_tokens(credentials_path, tokens)
    logger.info(
        "Refreshed Google access token (expires_in=%s)", payload.get("expires_in")
    )
    return new_token


def call_with_refresh(
    api_fn: Callable[..., Dict[str, Any]],
    credentials_path: str,
    *args: Any,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Invoke ``api_fn(token, *args, **kwargs)`` with one-shot 401 auto-refresh.

    Loads the current access token from disk, calls the helper, and if Google
    returns 401 (the access token has expired or been revoked) uses the stored
    refresh_token to mint a new access_token, updates the credentials file,
    and retries the call exactly once.

    Any other ``HTTPStatusError`` is re-raised unchanged — auth-related retries
    end here; transient 5xx / timeout retries belong further up the stack.
    """
    token = current_access_token(credentials_path)
    try:
        return api_fn(token, *args, **kwargs)
    except httpx.HTTPStatusError as exc:
        if exc.response is None or exc.response.status_code != 401:
            raise
        logger.info(
            "Google returned 401 on %s — refreshing access token and retrying.",
            getattr(api_fn, "__name__", "<api_fn>"),
        )
        new_token = refresh_access_token(credentials_path)
        return api_fn(new_token, *args, **kwargs)


__all__ = [
    "GoogleAuthError",
    "current_access_token",
    "refresh_access_token",
    "call_with_refresh",
]
