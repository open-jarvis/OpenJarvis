"""SQLite store for the construction domain.

Tables:
* ``cost_items``  — unit-cost catalog (labor, materials, equipment).
* ``projects``    — project records with status tracking.
* ``documents``   — generated quotes/contracts linked to a project.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_STATUSES = ("lead", "quoted", "active", "completed", "cancelled")


@dataclass
class CostItem:
    name: str
    category: str
    unit: str
    unit_cost: float
    updated_at: str = ""


@dataclass
class Project:
    id: str
    name: str
    client: str
    status: str
    notes: str = ""
    created_at: str = ""


@dataclass
class DocumentRecord:
    id: str
    project_id: str
    doc_type: str  # quote | contract
    title: str
    path: str
    total: float
    created_at: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConstructionStore:
    """Persistent store for cost catalog, projects, and generated documents."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "construction.db")
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cost_items (
                name TEXT PRIMARY KEY,
                category TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'each',
                unit_cost REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                client TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'lead',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                doc_type TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT NOT NULL,
                total REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}'
            );
            """
        )

    # -- Cost catalog ----------------------------------------------------------

    def add_cost_item(
        self, name: str, unit_cost: float, *, category: str = "", unit: str = "each"
    ) -> CostItem:
        """Insert or update a catalog item (keyed by lower-cased name)."""
        key = name.strip().lower()
        self._conn.execute(
            """
            INSERT INTO cost_items (name, category, unit, unit_cost, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                category = excluded.category,
                unit = excluded.unit,
                unit_cost = excluded.unit_cost,
                updated_at = excluded.updated_at
            """,
            (key, category, unit, float(unit_cost), _now()),
        )
        self._conn.commit()
        return CostItem(key, category, unit, float(unit_cost), _now())

    def get_cost_item(self, name: str) -> Optional[CostItem]:
        row = self._conn.execute(
            "SELECT name, category, unit, unit_cost, updated_at FROM cost_items"
            " WHERE name = ?",
            (name.strip().lower(),),
        ).fetchone()
        return CostItem(*row) if row else None

    def search_cost_items(self, query: str = "") -> List[CostItem]:
        if query:
            cur = self._conn.execute(
                "SELECT name, category, unit, unit_cost, updated_at FROM cost_items"
                " WHERE name LIKE ? OR category LIKE ? ORDER BY name",
                (f"%{query.lower()}%", f"%{query.lower()}%"),
            )
        else:
            cur = self._conn.execute(
                "SELECT name, category, unit, unit_cost, updated_at FROM cost_items"
                " ORDER BY name"
            )
        return [CostItem(*r) for r in cur.fetchall()]

    def delete_cost_item(self, name: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM cost_items WHERE name = ?", (name.strip().lower(),)
        )
        self._conn.commit()
        return cur.rowcount

    # -- Projects --------------------------------------------------------------

    def create_project(
        self, name: str, *, client: str = "", status: str = "lead", notes: str = ""
    ) -> Project:
        if status not in PROJECT_STATUSES:
            status = "lead"
        proj = Project(
            id=uuid.uuid4().hex[:12],
            name=name,
            client=client,
            status=status,
            notes=notes,
            created_at=_now(),
        )
        self._conn.execute(
            "INSERT INTO projects (id, name, client, status, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (proj.id, proj.name, proj.client, proj.status, proj.notes, proj.created_at),
        )
        self._conn.commit()
        return proj

    def get_project(self, project_id: str) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT id, name, client, status, notes, created_at FROM projects"
            " WHERE id = ?",
            (project_id,),
        ).fetchone()
        return Project(*row) if row else None

    def find_project_by_name(self, name: str) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT id, name, client, status, notes, created_at FROM projects"
            " WHERE lower(name) = ? ORDER BY created_at DESC LIMIT 1",
            (name.strip().lower(),),
        ).fetchone()
        return Project(*row) if row else None

    def list_projects(self, status: Optional[str] = None) -> List[Project]:
        if status:
            cur = self._conn.execute(
                "SELECT id, name, client, status, notes, created_at FROM projects"
                " WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, name, client, status, notes, created_at FROM projects"
                " ORDER BY created_at DESC"
            )
        return [Project(*r) for r in cur.fetchall()]

    def update_project_status(self, project_id: str, status: str) -> bool:
        if status not in PROJECT_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Use one of {PROJECT_STATUSES}."
            )
        cur = self._conn.execute(
            "UPDATE projects SET status = ? WHERE id = ?", (status, project_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # -- Documents -------------------------------------------------------------

    def record_document(
        self,
        *,
        doc_type: str,
        title: str,
        path: str,
        total: float = 0.0,
        project_id: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> DocumentRecord:
        rec = DocumentRecord(
            id=uuid.uuid4().hex[:12],
            project_id=project_id,
            doc_type=doc_type,
            title=title,
            path=path,
            total=float(total),
            created_at=_now(),
            data=data or {},
        )
        self._conn.execute(
            "INSERT INTO documents (id, project_id, doc_type, title, path, total,"
            " created_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rec.id,
                rec.project_id,
                rec.doc_type,
                rec.title,
                rec.path,
                rec.total,
                rec.created_at,
                json.dumps(rec.data),
            ),
        )
        self._conn.commit()
        return rec

    def list_documents(self, project_id: str = "") -> List[DocumentRecord]:
        if project_id:
            cur = self._conn.execute(
                "SELECT id, project_id, doc_type, title, path, total, created_at, data"
                " FROM documents WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, project_id, doc_type, title, path, total, created_at, data"
                " FROM documents ORDER BY created_at DESC"
            )
        out: List[DocumentRecord] = []
        for r in cur.fetchall():
            out.append(
                DocumentRecord(
                    id=r[0],
                    project_id=r[1],
                    doc_type=r[2],
                    title=r[3],
                    path=r[4],
                    total=r[5],
                    created_at=r[6],
                    data=json.loads(r[7]) if r[7] else {},
                )
            )
        return out

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "ConstructionStore",
    "CostItem",
    "Project",
    "DocumentRecord",
    "PROJECT_STATUSES",
]
