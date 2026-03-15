//! SQLite + FTS5 memory backend.

use crate::storage::traits::MemoryBackend;
use openjarvis_core::{OpenJarvisError, RetrievalResult};
use parking_lot::Mutex;
use rusqlite::Connection;
use serde_json::Value;
use std::path::{Path, PathBuf};
use uuid::Uuid;

pub struct SQLiteMemory {
    conn: Mutex<Connection>,
    _db_path: PathBuf,
}

impl SQLiteMemory {
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
            "CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at REAL DEFAULT (julianday('now'))
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                id, content, source, tokenize='unicode61'
            );",
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        // Migrate existing FTS5 tables that lack the unicode61 tokenizer
        // (ensures case-insensitive search on databases created before this fix).
        let needs_migration: bool = conn
            .query_row(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents_fts'",
                [],
                |row| row.get::<_, String>(0),
            )
            .map(|sql| !sql.contains("unicode61"))
            .unwrap_or(false);

        if needs_migration {
            conn.execute_batch(
                "DROP TABLE IF EXISTS documents_fts;
                 CREATE VIRTUAL TABLE documents_fts USING fts5(
                     id, content, source, tokenize='unicode61'
                 );
                 INSERT INTO documents_fts (id, content, source)
                     SELECT id, content, source FROM documents;",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        }

        Ok(Self {
            conn: Mutex::new(conn),
            _db_path: db_path.to_path_buf(),
        })
    }

    pub fn in_memory() -> Result<Self, OpenJarvisError> {
        Self::new(Path::new(":memory:"))
    }
}

impl MemoryBackend for SQLiteMemory {
    fn backend_id(&self) -> &str {
        "sqlite"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, OpenJarvisError> {
        let doc_id = Uuid::new_v4().to_string();
        let meta_str =
            metadata.map(|m| serde_json::to_string(m).unwrap_or_default())
                .unwrap_or_else(|| "{}".to_string());

        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO documents (id, content, source, metadata) VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![doc_id, content, source, meta_str],
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        conn.execute(
            "INSERT INTO documents_fts (id, content, source) VALUES (?1, ?2, ?3)",
            rusqlite::params![doc_id, content, source],
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(doc_id)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, OpenJarvisError> {
        let conn = self.conn.lock();

        let words: Vec<&str> = query.split_whitespace().collect();
        let fts_query = if words.len() == 1 {
            words[0].to_string()
        } else {
            words.join(" OR ")
        };

        let mut stmt = conn
            .prepare(
                "SELECT d.content, d.source, d.metadata,
                        bm25(documents_fts, 0.0, 1.0, 0.5) * -1 as score
                 FROM documents_fts f
                 JOIN documents d ON d.id = f.id
                 WHERE documents_fts MATCH ?1
                 ORDER BY bm25(documents_fts, 0.0, 1.0, 0.5)
                 LIMIT ?2",
            )
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let results = stmt
            .query_map(rusqlite::params![fts_query, top_k as i64], |row| {
                Ok(RetrievalResult {
                    content: row.get(0)?,
                    source: row.get::<_, String>(1).unwrap_or_default(),
                    metadata: row
                        .get::<_, String>(2)
                        .ok()
                        .and_then(|s| serde_json::from_str(&s).ok())
                        .unwrap_or_default(),
                    score: row.get::<_, f64>(3).unwrap_or(0.0),
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
        conn.execute(
            "DELETE FROM documents_fts WHERE id = ?1",
            rusqlite::params![doc_id],
        )
        .map_err(|e| {
            OpenJarvisError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;
        let changes = conn
            .execute(
                "DELETE FROM documents WHERE id = ?1",
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
        conn.execute_batch("DELETE FROM documents_fts; DELETE FROM documents")
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
            .query_row("SELECT COUNT(*) FROM documents", [], |row| row.get(0))
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
    fn test_sqlite_store_and_retrieve() {
        let mem = SQLiteMemory::in_memory().unwrap();
        let id = mem.store("Rust is a systems programming language", "test", None).unwrap();
        assert!(!id.is_empty());

        let results = mem.retrieve("Rust programming", 5).unwrap();
        assert!(!results.is_empty());
        assert!(results[0].content.contains("Rust"));
    }

    #[test]
    fn test_sqlite_delete() {
        let mem = SQLiteMemory::in_memory().unwrap();
        let id = mem.store("test content", "test", None).unwrap();
        assert_eq!(mem.count().unwrap(), 1);
        assert!(mem.delete(&id).unwrap());
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_sqlite_clear() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("doc 1", "s1", None).unwrap();
        mem.store("doc 2", "s2", None).unwrap();
        assert_eq!(mem.count().unwrap(), 2);
        mem.clear().unwrap();
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_sqlite_case_insensitive_search() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("Medication dosage guidelines for patients", "medical", None).unwrap();
        mem.store("The medication was prescribed yesterday", "medical", None).unwrap();

        // Lowercase query should match uppercase content
        let lower = mem.retrieve("medication", 10).unwrap();
        assert_eq!(lower.len(), 2, "lowercase query should find both documents");

        // Uppercase query should also match
        let upper = mem.retrieve("MEDICATION", 10).unwrap();
        assert_eq!(upper.len(), 2, "uppercase query should find both documents");

        // Mixed case
        let mixed = mem.retrieve("Medication", 10).unwrap();
        assert_eq!(mixed.len(), 2, "mixed-case query should find both documents");
    }

    #[test]
    fn test_sqlite_scores_are_positive() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("Rust is a systems programming language", "docs", None).unwrap();
        mem.store("Python is a high-level programming language", "docs", None).unwrap();
        mem.store("Cooking recipes for beginners", "other", None).unwrap();

        let results = mem.retrieve("programming", 5).unwrap();
        assert!(!results.is_empty());
        for r in &results {
            assert!(r.score > 0.0, "score should be positive, got {}", r.score);
        }
    }
}
