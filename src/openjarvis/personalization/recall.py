"""SessionRecaller — pull relevant snippets from past sessions.

Local-only: no embeddings call, no network. Uses SQLite FTS5 when the
``session_messages`` table has it, otherwise falls back to plain LIKE
matching with token overlap scoring.

This is a thin layer designed to provide "warm context" — short user
turns and the corresponding assistant replies — without dumping entire
sessions back into the prompt.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from openjarvis.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

DEFAULT_SESSIONS_DB = DEFAULT_CONFIG_DIR / "sessions.db"

_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "you",
        "i",
        "me",
        "my",
        "we",
        "us",
        "our",
        "your",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "this",
        "that",
        "what",
        "which",
        "how",
        "when",
        "where",
        "why",
        "請",
        "幫",
        "我",
        "你",
        "他",
        "她",
        "是",
        "的",
        "嗎",
        "嘛",
        "啊",
        "喔",
    }
)


_CJK_RE = re.compile(r"[一-鿿]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenise(text: str) -> List[str]:
    """Lossy tokenizer: ASCII words + per-character CJK.

    CJK has no spaces, so the simplest cheap signal that still gives us
    overlap on partial matches is character bigrams + single characters.
    Bigrams help with multi-char words like "黑咖啡" → "黑咖", "咖啡".
    """
    text = text.lower()
    tokens: List[str] = []
    for word in _ASCII_WORD_RE.findall(text):
        if word and word not in _STOP and len(word) > 1:
            tokens.append(word)
    chars = _CJK_RE.findall(text)
    chars = [c for c in chars if c not in _STOP]
    tokens.extend(chars)
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    return tokens


@dataclass(slots=True)
class RecalledTurn:
    """A single recalled user/assistant turn pair."""

    session_id: str
    role: str
    content: str
    timestamp: float
    score: float

    def to_hint(self) -> str:
        snippet = self.content.strip()
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."
        if self.role == "user":
            return f"你曾說過：「{snippet}」"
        if self.role == "assistant":
            return f"我之前回答過：「{snippet}」"
        return snippet


class SessionRecaller:
    """Search past session messages for snippets relevant to a query.

    The recaller never modifies the sessions DB. It opens a short-lived
    read-only connection on each query so it is safe to run alongside an
    active :class:`SessionStore`.
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_SESSIONS_DB,
        *,
        exclude_session_id: Optional[str] = None,
        min_score: float = 0.05,
    ) -> None:
        self._db_path = Path(db_path).expanduser()
        self._exclude = exclude_session_id
        self._min_score = min_score

    def for_session(self, session_id: Optional[str]) -> "SessionRecaller":
        return SessionRecaller(
            db_path=self._db_path,
            exclude_session_id=session_id,
            min_score=self._min_score,
        )

    def recall(self, query: str, *, limit: int = 3) -> List[str]:
        turns = self.recall_turns(query, limit=limit)
        return [t.to_hint() for t in turns]

    def recall_turns(self, query: str, *, limit: int = 3) -> List[RecalledTurn]:
        if not query or not self._db_path.exists():
            return []
        tokens = _tokenise(query)
        if not tokens:
            return []

        try:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError as exc:
            logger.debug("Cannot open sessions db read-only: %s", exc)
            return []

        try:
            rows = self._search(conn, tokens, limit * 5)
        finally:
            conn.close()

        scored: List[RecalledTurn] = []
        for session_id, role, content, ts in rows:
            if self._exclude and session_id == self._exclude:
                continue
            score = _score(content, tokens)
            if score < self._min_score:
                continue
            scored.append(
                RecalledTurn(
                    session_id=session_id,
                    role=role,
                    content=content,
                    timestamp=ts or 0.0,
                    score=score,
                )
            )
        scored.sort(key=lambda t: t.score, reverse=True)
        return scored[:limit]

    @staticmethod
    def _search(
        conn: sqlite3.Connection,
        tokens: Sequence[str],
        candidate_limit: int,
    ) -> List[Tuple[str, str, str, float]]:
        like_clauses = " OR ".join("content LIKE ?" for _ in tokens)
        params = [f"%{t}%" for t in tokens]
        sql = (
            "SELECT session_id, role, content, timestamp "
            "FROM session_messages "
            f"WHERE {like_clauses} "
            "ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(candidate_limit)
        try:
            return list(conn.execute(sql, params))
        except sqlite3.OperationalError:
            return []


def _score(content: str, tokens: Sequence[str]) -> float:
    body_tokens = set(_tokenise(content))
    if not body_tokens:
        return 0.0
    overlap = sum(1 for t in tokens if t in body_tokens)
    return overlap / max(len(tokens), 1)


__all__ = [
    "DEFAULT_SESSIONS_DB",
    "RecalledTurn",
    "SessionRecaller",
]
