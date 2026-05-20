"""ProfileConsolidator — fold memory backend rows into a UserProfile.

The ``memory_learn`` tool (and other learning paths) stores facts in the
memory backend with a structured ``metadata`` payload that looks like::

    {"key": "pref.coffee", "source": "explicit"}

The consolidator scans the backend for rows with such metadata, groups
them by key-prefix into Identity / Preferences / Facts / Relations
sections, and writes the result to ``~/.openjarvis/USER.md``.

Notes:

* "Latest write wins": when the same ``key`` appears multiple times we
  keep the most recently stored row (by ``created_at`` if available,
  otherwise the last one seen in the result list).
* The consolidator is content-only — it never writes back to the memory
  backend. Editing USER.md by hand is safe.
* Rows whose metadata has no ``key`` field are skipped (they're treated
  as RAG corpus, not profile facts).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from openjarvis.personalization.profile import (
    DEFAULT_PROFILE_PATH,
    UserProfile,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConsolidationStats:
    """Summary returned by :meth:`ProfileConsolidator.consolidate`."""

    scanned: int = 0
    accepted: int = 0
    skipped_no_key: int = 0
    skipped_duplicate: int = 0
    profile_path: Optional[Path] = None


def _coerce_metadata(meta: Any) -> Dict[str, Any]:
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str):
        try:
            import json

            return json.loads(meta)
        except Exception:
            return {}
    return {}


def _ts_of(meta: Dict[str, Any]) -> float:
    for key in ("created_at", "ts", "timestamp"):
        try:
            return float(meta.get(key, 0.0))
        except Exception:
            continue
    return 0.0


class ProfileConsolidator:
    """Fold a memory backend's contents into a :class:`UserProfile`.

    Parameters
    ----------
    backend:
        Any object exposing ``retrieve(query, top_k=...)`` returning a
        list of :class:`~openjarvis.tools.storage._stubs.RetrievalResult`.
        We also try ``all_documents()`` / ``list_documents()`` / ``scan()``
        for full enumeration; if none are available we fall back to a
        broad retrieve over the prefix tokens.
    """

    _PREFIX_QUERIES: Tuple[str, ...] = (
        "user",
        "pref",
        "fact",
        "relation",
        "note",
    )

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consolidate(
        self,
        *,
        output_path: Path | str = DEFAULT_PROFILE_PATH,
        top_k_per_prefix: int = 200,
    ) -> Tuple[UserProfile, ConsolidationStats]:
        """Scan the backend and return ``(profile, stats)``.

        The profile is also written to ``output_path``.
        """
        stats = ConsolidationStats()
        latest: Dict[str, Tuple[float, str]] = {}

        for row in self._iter_rows(top_k_per_prefix):
            stats.scanned += 1
            meta = _coerce_metadata(row.get("metadata"))
            key = (meta.get("key") or "").strip()
            if not key:
                stats.skipped_no_key += 1
                continue
            value = (row.get("content") or "").strip()
            if not value:
                stats.skipped_no_key += 1
                continue
            ts = _ts_of(meta)
            existing = latest.get(key)
            if existing is None:
                latest[key] = (ts, value)
            elif ts >= existing[0]:
                # New row supersedes the previous one for this key.
                latest[key] = (ts, value)
                stats.skipped_duplicate += 1
            else:
                stats.skipped_duplicate += 1

        # ``accepted`` reflects the final profile size, not raw write count.
        stats.accepted = len(latest)

        profile = UserProfile()
        for key, (_ts, value) in sorted(latest.items()):
            profile.add(key, value)

        path = profile.save(output_path)
        stats.profile_path = path
        return profile, stats

    # ------------------------------------------------------------------
    # Row enumeration
    # ------------------------------------------------------------------

    def _iter_rows(self, top_k_per_prefix: int) -> Iterable[Dict[str, Any]]:
        """Yield ``{content, metadata}`` dicts from the backend.

        Tries the cheap full-enumeration paths first, then falls back to
        prefix-token retrieves. Deduplicates by ``doc_id`` when available.
        """
        seen_ids: set[str] = set()

        for method_name in ("all_documents", "list_documents", "scan"):
            method = getattr(self._backend, method_name, None)
            if callable(method):
                try:
                    for row in method():
                        rid = self._row_id(row)
                        if rid and rid in seen_ids:
                            continue
                        if rid:
                            seen_ids.add(rid)
                        yield self._normalise_row(row)
                    return
                except Exception as exc:
                    logger.debug(
                        "%s() failed on backend %r: %s",
                        method_name,
                        type(self._backend).__name__,
                        exc,
                    )

        # Fallback: do a broad retrieve per prefix.
        for prefix in self._PREFIX_QUERIES:
            try:
                results = self._backend.retrieve(prefix, top_k=top_k_per_prefix)
            except Exception as exc:
                logger.debug("retrieve(%r) failed: %s", prefix, exc)
                continue
            for r in results:
                rid = self._row_id(r)
                if rid and rid in seen_ids:
                    continue
                if rid:
                    seen_ids.add(rid)
                yield self._normalise_row(r)

    @staticmethod
    def _row_id(row: Any) -> Optional[str]:
        meta = getattr(row, "metadata", None) or (
            row.get("metadata") if isinstance(row, dict) else None
        )
        meta = _coerce_metadata(meta)
        for k in ("id", "doc_id"):
            if k in meta:
                return str(meta[k])
        return None

    @staticmethod
    def _normalise_row(row: Any) -> Dict[str, Any]:
        if isinstance(row, dict):
            return {
                "content": row.get("content", ""),
                "metadata": _coerce_metadata(row.get("metadata")),
            }
        return {
            "content": getattr(row, "content", "") or "",
            "metadata": _coerce_metadata(getattr(row, "metadata", None)),
        }


def consolidate_from_config(
    config: Any,
    *,
    output_path: Path | str = DEFAULT_PROFILE_PATH,
) -> Tuple[UserProfile, ConsolidationStats]:
    """Helper: build a SQLite backend from config and consolidate it.

    Also probes ``config.memory.db_path`` directly for a ``user_facts``
    table populated by older setup scripts / external tools. That table
    uses ``(key, value, ts, source)`` columns and is the easiest place
    to seed an initial profile.
    """
    import openjarvis.tools.storage  # noqa: F401  ensure registration
    from openjarvis.core.registry import MemoryRegistry

    rows: list[Dict[str, Any]] = list(_iter_user_facts(config.memory.db_path))

    backend_rows: Iterable[Dict[str, Any]] = []
    key = config.memory.default_backend
    backend = None
    if MemoryRegistry.contains(key):
        backend = MemoryRegistry.create(key, db_path=config.memory.db_path)
        try:
            backend_rows = list(ProfileConsolidator(backend)._iter_rows(200))
        finally:
            close = getattr(backend, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    class _Combined:
        def __init__(self, rows):
            self._rows = rows

        def all_documents(self):
            return self._rows

    combined = list(rows) + list(backend_rows)
    return ProfileConsolidator(_Combined(combined)).consolidate(
        output_path=output_path
    )


def _iter_user_facts(db_path: str) -> Iterable[Dict[str, Any]]:
    """Yield ``user_facts`` rows in ``{content, metadata}`` form."""
    from pathlib import Path as _Path

    path = _Path(db_path).expanduser()
    if not path.exists():
        return
    import sqlite3

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name='user_facts'"
            )
            if not cur.fetchone():
                return
            for row in conn.execute(
                "SELECT id, ts, key, value FROM user_facts"
            ):
                row_id, ts, k, v = row
                try:
                    from datetime import datetime as _dt

                    created_at = _dt.fromisoformat(ts).timestamp() if ts else 0.0
                except Exception:
                    created_at = 0.0
                yield {
                    "content": v or "",
                    "metadata": {
                        "id": f"user_facts:{row_id}",
                        "key": k or "",
                        "created_at": created_at,
                        "source": "user_facts",
                    },
                }
    except sqlite3.OperationalError as exc:
        logger.debug("user_facts probe failed: %s", exc)


__all__ = [
    "ConsolidationStats",
    "ProfileConsolidator",
    "consolidate_from_config",
]
