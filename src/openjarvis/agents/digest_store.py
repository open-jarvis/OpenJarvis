"""DigestStore — SQLite-backed storage for pre-computed digest artifacts."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class DigestArtifact:
    """A pre-computed morning digest ready for delivery."""

    text: str
    audio_path: Path
    sections: Dict[str, str]
    sources_used: List[str]
    generated_at: datetime
    model_used: str
    voice_used: str


class DigestStore:
    """SQLite store for digest artifacts."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "digest.db")
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                audio_path TEXT NOT NULL,
                sections TEXT NOT NULL,
                sources_used TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                model_used TEXT NOT NULL,
                voice_used TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def save(self, artifact: DigestArtifact) -> None:
        """Save a digest artifact."""
        self._conn.execute(
            """
            INSERT INTO digests
                (text, audio_path, sections, sources_used,
                 generated_at, model_used, voice_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.text,
                str(artifact.audio_path),
                json.dumps(artifact.sections),
                json.dumps(artifact.sources_used),
                artifact.generated_at.isoformat(),
                artifact.model_used,
                artifact.voice_used,
            ),
        )
        self._conn.commit()

    def _row_to_artifact(self, row: tuple) -> DigestArtifact:
        return DigestArtifact(
            text=row[0],
            audio_path=Path(row[1]),
            sections=json.loads(row[2]),
            sources_used=json.loads(row[3]),
            generated_at=datetime.fromisoformat(row[4]),
            model_used=row[5],
            voice_used=row[6],
        )

    def get_latest(self) -> Optional[DigestArtifact]:
        """Return the most recent digest, or None."""
        row = self._conn.execute(
            "SELECT text, audio_path, sections, sources_used,"
            " generated_at, model_used, voice_used"
            " FROM digests ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_artifact(row)

    def get_today(self, timezone_name: str = "UTC") -> Optional[DigestArtifact]:
        """Return today's digest if it exists, or None."""
        try:
            from zoneinfo import ZoneInfo

            today = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
        except ImportError:
            today = datetime.now().strftime("%Y-%m-%d")

        row = self._conn.execute(
            "SELECT text, audio_path, sections, sources_used,"
            " generated_at, model_used, voice_used"
            " FROM digests WHERE generated_at LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_artifact(row)

    def history(self, limit: int = 10) -> List[DigestArtifact]:
        """Return the N most recent digests."""
        rows = self._conn.execute(
            "SELECT text, audio_path, sections, sources_used,"
            " generated_at, model_used, voice_used"
            " FROM digests ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
