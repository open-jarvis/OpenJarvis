"""ScienceProjectStore — SQLite-backed storage for saved science projects.

Copies ``agents/digest_store.py``'s shape: plain ``sqlite3``, a
``_migrate()`` method for forward-compatible schema evolution, JSON-
serialized complex fields, ISO-format timestamps.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from openjarvis.core.paths import get_config_dir
from openjarvis.science_lab.models import (
    ComparisonRow,
    ConfidenceScore,
    Hypothesis,
    ScienceProject,
    SimulationResult,
    TargetProperty,
)


class ScienceProjectStore:
    """SQLite store for named science projects."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(get_config_dir() / "science_lab.db")
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS science_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                objective TEXT NOT NULL,
                target_properties TEXT NOT NULL,
                hypotheses TEXT NOT NULL,
                simulations TEXT NOT NULL,
                comparison TEXT NOT NULL,
                confidence_value REAL NOT NULL DEFAULT 0.0,
                confidence_basis TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the initial schema (none yet)."""
        existing = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(science_projects)"
            ).fetchall()
        }
        # No post-v1 columns yet; kept for forward compatibility, e.g.:
        # if "tags" not in existing:
        #     self._conn.execute(
        #         "ALTER TABLE science_projects ADD COLUMN tags TEXT DEFAULT ''"
        #     )
        del existing  # placeholder until a real migration is needed

    def save(self, project: ScienceProject) -> None:
        """Save (upsert on unique ``name``) a science project."""
        project.updated_at = datetime.now(timezone.utc)
        self._conn.execute(
            """
            INSERT INTO science_projects
                (name, objective, target_properties, hypotheses, simulations,
                 comparison, confidence_value, confidence_basis, notes,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                objective=excluded.objective,
                target_properties=excluded.target_properties,
                hypotheses=excluded.hypotheses,
                simulations=excluded.simulations,
                comparison=excluded.comparison,
                confidence_value=excluded.confidence_value,
                confidence_basis=excluded.confidence_basis,
                notes=excluded.notes,
                updated_at=excluded.updated_at
            """,
            (
                project.name,
                project.objective,
                json.dumps([p.to_dict() for p in project.target_properties]),
                json.dumps([h.to_dict() for h in project.hypotheses]),
                json.dumps([s.to_dict() for s in project.simulations]),
                json.dumps([c.to_dict() for c in project.comparison]),
                project.confidence.value,
                project.confidence.basis,
                project.notes,
                project.created_at.isoformat(),
                project.updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def _row_to_project(self, row: tuple) -> ScienceProject:
        return ScienceProject(
            name=row[0],
            objective=row[1],
            target_properties=[TargetProperty.from_dict(p) for p in json.loads(row[2])],
            hypotheses=[Hypothesis.from_dict(h) for h in json.loads(row[3])],
            simulations=[SimulationResult.from_dict(s) for s in json.loads(row[4])],
            comparison=[ComparisonRow.from_dict(c) for c in json.loads(row[5])],
            confidence=ConfidenceScore(value=row[6], basis=row[7]),
            notes=row[8],
            created_at=datetime.fromisoformat(row[9]),
            updated_at=datetime.fromisoformat(row[10]),
        )

    _SELECT_COLUMNS = (
        "name, objective, target_properties, hypotheses, simulations,"
        " comparison, confidence_value, confidence_basis, notes,"
        " created_at, updated_at"
    )

    def get(self, name: str) -> Optional[ScienceProject]:
        """Return the project named *name*, or ``None``."""
        row = self._conn.execute(
            f"SELECT {self._SELECT_COLUMNS} FROM science_projects WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def list_projects(self, limit: int = 50) -> List[ScienceProject]:
        """Return the most recently updated projects, newest first."""
        rows = self._conn.execute(
            f"SELECT {self._SELECT_COLUMNS} FROM science_projects"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def delete(self, name: str) -> bool:
        """Delete the project named *name*. Returns whether a row was removed."""
        cur = self._conn.execute("DELETE FROM science_projects WHERE name = ?", (name,))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()


__all__ = ["ScienceProjectStore"]
