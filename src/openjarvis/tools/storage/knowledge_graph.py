"""Knowledge graph storage backend — entity-relation store with pattern queries."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import MemoryRegistry


@dataclass(slots=True)
class Entity:
    """A node in the knowledge graph."""

    entity_id: str
    entity_type: str  # "agent", "tool", "model", "user", "concept", etc.
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass(slots=True)
class Relation:
    """An edge between two entities."""

    source_id: str
    target_id: str
    relation_type: str  # "used", "produced", "depends_on", "similar_to", etc.
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


@dataclass(slots=True)
class GraphQueryResult:
    """Result from a graph pattern query."""

    entities: List[Entity] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)


@MemoryRegistry.register("knowledge_graph")
class KnowledgeGraphMemory:
    """SQLite-backed knowledge graph implementing MemoryBackend ABC.

    Provides standard store/retrieve/delete/clear operations plus
    graph-specific operations: add_entity(), add_relation(),
    query_pattern(), neighbors().
    """

    def __init__(
        self,
        db_path: Union[str, Path] = DEFAULT_CONFIG_DIR / "knowledge_graph.db",
        **kwargs: Any,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                entity_id   TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                name        TEXT NOT NULL,
                properties  TEXT DEFAULT '{}',
                created_at  REAL
            );
            CREATE TABLE IF NOT EXISTS relations (
                id            INTEGER PRIMARY KEY,
                source_id     TEXT NOT NULL,
                target_id     TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                weight        REAL DEFAULT 1.0,
                properties    TEXT DEFAULT '{}',
                created_at    REAL,
                FOREIGN KEY (source_id) REFERENCES entities(entity_id),
                FOREIGN KEY (target_id) REFERENCES entities(entity_id)
            );
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
            CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(relation_type);
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
        """)
        self._conn.commit()

    # -- MemoryBackend ABC --

    def store(
        self,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store content as an entity (MemoryBackend interface)."""
        meta = metadata or {}
        self.add_entity(
            Entity(
                entity_id=key,
                entity_type=meta.get("entity_type", "document"),
                name=meta.get("name", key),
                properties={"content": content, **(meta.get("properties", {}))},
            )
        )

    def retrieve(self, key: str) -> Optional[str]:
        """Retrieve content by entity_id (MemoryBackend interface)."""
        entity = self.get_entity(key)
        if entity:
            return entity.properties.get("content", json.dumps(entity.properties))
        return None

    def search(self, query: str, top_k: int = 5, **kwargs: Any) -> List[Dict[str, Any]]:
        """Search entities by name/type/content (MemoryBackend interface)."""
        rows = self._conn.execute(
            "SELECT entity_id, entity_type, name, properties, created_at "
            "FROM entities "
            "WHERE name LIKE ? OR entity_type LIKE ? OR properties LIKE ? "
            "LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", top_k),
        ).fetchall()
        results = []
        for row in rows:
            eid, etype, name, props_json, ts = row
            props = json.loads(props_json) if props_json else {}
            results.append(
                {
                    "key": eid,
                    "content": props.get("content", ""),
                    "score": 1.0,
                    "metadata": {"entity_type": etype, "name": name},
                }
            )
        return results

    def delete(self, key: str) -> bool:
        """Delete an entity and its relations."""
        self._conn.execute(
            "DELETE FROM relations WHERE source_id = ? OR target_id = ?",
            (key, key),
        )
        cur = self._conn.execute("DELETE FROM entities WHERE entity_id = ?", (key,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> None:
        """Remove all entities and relations."""
        self._conn.execute("DELETE FROM relations")
        self._conn.execute("DELETE FROM entities")
        self._conn.commit()

    # -- Graph-specific operations --

    def add_entity(self, entity: Entity) -> None:
        """Add or update an entity."""
        ts = entity.created_at or time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO entities"
            " (entity_id, entity_type, name,"
            " properties, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                entity.entity_id,
                entity.entity_type,
                entity.name,
                json.dumps(entity.properties),
                ts,
            ),
        )
        self._conn.commit()

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        row = self._conn.execute(
            "SELECT entity_id, entity_type, name, properties, created_at "
            "FROM entities WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            return None
        return Entity(
            entity_id=row[0],
            entity_type=row[1],
            name=row[2],
            properties=json.loads(row[3]) if row[3] else {},
            created_at=row[4] or 0.0,
        )

    def add_relation(self, relation: Relation) -> None:
        """Add a relation between two entities."""
        ts = relation.created_at or time.time()
        self._conn.execute(
            "INSERT INTO relations"
            " (source_id, target_id, relation_type,"
            " weight, properties, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                relation.source_id,
                relation.target_id,
                relation.relation_type,
                relation.weight,
                json.dumps(relation.properties),
                ts,
            ),
        )
        self._conn.commit()

    def neighbors(
        self,
        entity_id: str,
        *,
        relation_type: Optional[str] = None,
        direction: str = "both",
        limit: int = 50,
    ) -> List[Entity]:
        """Get neighboring entities connected by relations."""
        results: List[Entity] = []

        if direction in ("out", "both"):
            sql = "SELECT target_id FROM relations WHERE source_id = ?"
            params: list = [entity_id]
            if relation_type:
                sql += " AND relation_type = ?"
                params.append(relation_type)
            sql += " LIMIT ?"
            params.append(limit)
            for row in self._conn.execute(sql, params).fetchall():
                entity = self.get_entity(row[0])
                if entity:
                    results.append(entity)

        if direction in ("in", "both"):
            sql = "SELECT source_id FROM relations WHERE target_id = ?"
            params = [entity_id]
            if relation_type:
                sql += " AND relation_type = ?"
                params.append(relation_type)
            sql += " LIMIT ?"
            params.append(limit)
            for row in self._conn.execute(sql, params).fetchall():
                entity = self.get_entity(row[0])
                if entity and entity.entity_id != entity_id:
                    results.append(entity)

        return results[:limit]

    def query_pattern(
        self,
        *,
        entity_type: Optional[str] = None,
        relation_type: Optional[str] = None,
        limit: int = 50,
    ) -> GraphQueryResult:
        """Query entities and relations matching a pattern."""
        entities: List[Entity] = []
        relations: List[Relation] = []

        if entity_type:
            rows = self._conn.execute(
                "SELECT entity_id, entity_type, name, properties, created_at "
                "FROM entities WHERE entity_type = ? LIMIT ?",
                (entity_type, limit),
            ).fetchall()
            for row in rows:
                entities.append(
                    Entity(
                        entity_id=row[0],
                        entity_type=row[1],
                        name=row[2],
                        properties=json.loads(row[3]) if row[3] else {},
                        created_at=row[4] or 0.0,
                    )
                )

        if relation_type:
            rows = self._conn.execute(
                "SELECT source_id, target_id,"
                " relation_type, weight,"
                " properties, created_at "
                "FROM relations"
                " WHERE relation_type = ? LIMIT ?",
                (relation_type, limit),
            ).fetchall()
            for row in rows:
                relations.append(
                    Relation(
                        source_id=row[0],
                        target_id=row[1],
                        relation_type=row[2],
                        weight=row[3],
                        properties=json.loads(row[4]) if row[4] else {},
                        created_at=row[5] or 0.0,
                    )
                )

        return GraphQueryResult(entities=entities, relations=relations)

    def entity_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()
        return row[0] if row else 0

    def relation_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM relations").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()


__all__ = ["Entity", "GraphQueryResult", "KnowledgeGraphMemory", "Relation"]
