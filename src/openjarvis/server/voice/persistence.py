"""Where a finished Voice conversation goes to outlive the process."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("openjarvis.server.voice")

_UNSET = object()


def build_session_store(config: Any) -> Any | None:
    """Open the SQLite session store, or return None when it is switched off.

    ``cli/serve.py:363`` only builds one when the loaded agent's constructor
    happens to accept it, and then keeps no handle — so the server itself has
    nothing to write through. This builds it from config alone.

    ``config.sessions.enabled`` defaults to False, so an installation that
    never opted in keeps behaving exactly as before.
    """
    sessions = getattr(config, "sessions", None)
    if sessions is None or not getattr(sessions, "enabled", False):
        return None
    try:
        from openjarvis.sessions.session import SessionStore

        return SessionStore(
            db_path=Path(sessions.db_path).expanduser(),
            max_age_hours=sessions.max_age_hours,
            consolidation_threshold=sessions.consolidation_threshold,
        )
    except Exception:
        # An unopenable database must not cost the user their Voice session.
        logger.warning(
            "session store unavailable; voice will not persist", exc_info=True
        )
        return None


def session_store_for(app_state: Any) -> Any | None:
    """Return the app's session store, opening it on first use.

    Cached on ``app_state`` because every Voice session asks for it and opening
    SQLite per session would be waste. ``None`` is cached too — a disabled
    store must not be retried on every connection.
    """
    cached = getattr(app_state, "session_store", _UNSET)
    if cached is not _UNSET:
        return cached
    store = build_session_store(getattr(app_state, "config", None))
    app_state.session_store = store
    return store
