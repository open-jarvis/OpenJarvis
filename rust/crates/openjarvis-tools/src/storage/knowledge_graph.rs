//! Knowledge graph memory — SQLite entity-relation store.

use crate::storage::traits::MemoryBackend;
use openjarvis_core::{OpenJarvisError, RetrievalResult};
use parking_lot::Mutex;
use rusqlite::Connection;
use serde_json::Value;
use std::path::Path;
use uuid::Uuid;

pub struct KnowledgeGraphMemory {
    conn: Mutex<Connection>,
}

impl KnowledgeGraphMemory {
    pub fn new(db_path: &Path) -> Result<Self, OpenJarvisError> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(e))
            })?;
        }

        let conn = Connection::open(db_path).map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT DEFAULT '',
                properties TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT DEFAULT '{}',
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            );
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);",
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub fn in_memory() -> Result<Self, OpenJarvisError> {
        Self::new(Path::new(":memory:"))
    }

    pub fn add_entity(
        &self,
        name: &str,
        entity_type: &str,
        properties: Option<&Value>,
    ) -> Result<String, OpenJarvisError> {
        let id = Uuid::new_v4().to_string();
        let props = properties
            .map(|p| serde_json::to_string(p).unwrap_or_default())
            .unwrap_or_else(|| "{}".to_string());

        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO entities (id, name, entity_type, properties) VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![id, name, entity_type, props],
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(id)
    }

    pub fn add_relation(
        &self,
        source_id: &str,
        target_id: &str,
        relation_type: &str,
        properties: Option<&Value>,
    ) -> Result<String, OpenJarvisError> {
        let id = Uuid::new_v4().to_string();
        let props = properties
            .map(|p| serde_json::to_string(p).unwrap_or_default())
            .unwrap_or_else(|| "{}".to_string());

        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO relations (id, source_id, target_id, relation_type, properties)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            rusqlite::params![id, source_id, target_id, relation_type, props],
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(id)
    }

    pub fn neighbors(&self, entity_id: &str) -> Result<Vec<(String, String, String)>, OpenJarvisError> {
        let conn = self.conn.lock();
        let mut stmt = conn
            .prepare(
                "SELECT e.name, r.relation_type, 'outgoing'
                 FROM relations r JOIN entities e ON e.id = r.target_id
                 WHERE r.source_id = ?1
                 UNION ALL
                 SELECT e.name, r.relation_type, 'incoming'
                 FROM relations r JOIN entities e ON e.id = r.source_id
                 WHERE r.target_id = ?1",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let results = stmt
            .query_map(rusqlite::params![entity_id], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();

        Ok(results)
    }
}

impl MemoryBackend for KnowledgeGraphMemory {
    fn backend_id(&self) -> &str {
        "knowledge_graph"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, OpenJarvisError> {
        self.add_entity(content, source, metadata)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, OpenJarvisError> {
        let conn = self.conn.lock();
        let pattern = format!("%{query}%");
        let mut stmt = conn
            .prepare(
                "SELECT name, entity_type, properties
                 FROM entities WHERE name LIKE ?1 LIMIT ?2",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let results = stmt
            .query_map(rusqlite::params![pattern, top_k as i64], |row| {
                Ok(RetrievalResult {
                    content: row.get::<_, String>(0)?,
                    source: row.get::<_, String>(1).unwrap_or_default(),
                    score: 1.0,
                    metadata: row
                        .get::<_, String>(2)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_default(),
                })
            })
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();

        Ok(results)
    }

    fn delete(&self, doc_id: &str) -> Result<bool, OpenJarvisError> {
        let conn = self.conn.lock();
        let changes = conn
            .execute(
                "DELETE FROM entities WHERE id = ?1",
                rusqlite::params![doc_id],
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(changes > 0)
    }

    fn clear(&self) -> Result<(), OpenJarvisError> {
        let conn = self.conn.lock();
        conn.execute_batch("DELETE FROM relations; DELETE FROM entities;")
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(())
    }

    fn count(&self) -> Result<usize, OpenJarvisError> {
        let conn = self.conn.lock();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM entities", [], |row| row.get(0))
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(count as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_kg_entities_and_relations() {
        let kg = KnowledgeGraphMemory::in_memory().unwrap();
        let e1 = kg.add_entity("Rust", "language", None).unwrap();
        let e2 = kg.add_entity("Systems Programming", "concept", None).unwrap();
        kg.add_relation(&e1, &e2, "used_for", None).unwrap();

        let neighbors = kg.neighbors(&e1).unwrap();
        assert_eq!(neighbors.len(), 1);
        assert_eq!(neighbors[0].0, "Systems Programming");
    }
}
