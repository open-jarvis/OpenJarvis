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
        // Expand leading ~ to the user's home directory
        let db_path = if db_path.starts_with("~") {
            let home = std::env::var("HOME").map_err(|_| {
                OpenJarvisError::Io(std::io::Error::other("HOME environment variable not set"))
            })?;
            PathBuf::from(home).join(db_path.strip_prefix("~").unwrap())
        } else {
            db_path.to_path_buf()
        };
        let db_path = db_path.as_path();

        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e)))?;
        }

        let conn = Connection::open(db_path)
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

        // A longer busy timeout plus best-effort WAL mode (#756): without
        // WAL, a concurrent writer can block readers.  Some SQLite targets
        // (notably in-memory databases and filesystems without WAL support)
        // cannot switch journal mode, so failure to enable WAL must not make
        // an otherwise usable memory backend fail to open.
        conn.busy_timeout(std::time::Duration::from_secs(10))
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        if db_path != Path::new(":memory:") {
            match conn.query_row("PRAGMA journal_mode=WAL", [], |row| row.get::<_, String>(0)) {
                Ok(mode) if mode.eq_ignore_ascii_case("wal") => {}
                Ok(mode) => tracing::warn!(
                    journal_mode = %mode,
                    "SQLite WAL mode is unavailable; using the reported journal mode"
                ),
                Err(error) => tracing::warn!(
                    %error,
                    "Failed to enable SQLite WAL mode; continuing with the existing mode"
                ),
            }
        }

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at REAL DEFAULT (julianday('now'))
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                content, source, tokenize='porter unicode61'
            );",
        )
        .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

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
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        }

        Ok(Self {
            conn: Mutex::new(conn),
            _db_path: db_path.to_path_buf(),
        })
    }

    pub fn in_memory() -> Result<Self, OpenJarvisError> {
        Self::new(Path::new(":memory:"))
    }

    /// Atomically replace every document for *source* with *documents*.
    pub fn replace_source(
        &self,
        source: &str,
        documents: &[(&str, Option<&Value>)],
    ) -> Result<Vec<String>, OpenJarvisError> {
        let mut conn = self.conn.lock();
        let tx = conn
            .transaction()
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

        tx.execute(
            "DELETE FROM documents_fts
             WHERE rowid IN (SELECT rowid FROM documents WHERE source = ?1)",
            rusqlite::params![source],
        )
        .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        tx.execute(
            "DELETE FROM documents WHERE source = ?1",
            rusqlite::params![source],
        )
        .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

        let mut doc_ids = Vec::with_capacity(documents.len());
        for (content, metadata) in documents {
            let doc_id = Uuid::new_v4().to_string();
            let meta_str = metadata
                .map(|m| serde_json::to_string(m).unwrap_or_default())
                .unwrap_or_else(|| "{}".to_string());

            tx.execute(
                "INSERT INTO documents (id, content, source, metadata)
                 VALUES (?1, ?2, ?3, ?4)",
                rusqlite::params![doc_id, content, source, meta_str],
            )
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

            let rowid = tx.last_insert_rowid();
            tx.execute(
                "INSERT INTO documents_fts (rowid, content, source) VALUES (?1, ?2, ?3)",
                rusqlite::params![rowid, content, source],
            )
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
            doc_ids.push(doc_id);
        }

        tx.commit()
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        Ok(doc_ids)
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
        let meta_str = metadata
            .map(|m| serde_json::to_string(m).unwrap_or_default())
            .unwrap_or_else(|| "{}".to_string());

        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO documents (id, content, source, metadata) VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![doc_id, content, source, meta_str],
        )
        .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

        let rowid = conn.last_insert_rowid();
        conn.execute(
            "INSERT INTO documents_fts (rowid, content, source) VALUES (?1, ?2, ?3)",
            rusqlite::params![rowid, content, source],
        )
        .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

        Ok(doc_id)
    }

    fn retrieve(&self, query: &str, top_k: usize) -> Result<Vec<RetrievalResult>, OpenJarvisError> {
        let conn = self.conn.lock();

        // Split on any non-alphanumeric character (not just whitespace) so
        // internal punctuation — apostrophes in particular ("user's") — never
        // reaches the FTS5 MATCH string. FTS5's query grammar treats an
        // unescaped `'` as a string delimiter, so passing a raw token like
        // `user's` through silently fails to parse and yields zero rows with
        // no visible error. Splitting fully avoids needing to escape anything.
        let words: Vec<String> = query
            .split(|c: char| !c.is_alphanumeric())
            .map(|w| w.to_string())
            .filter(|w| !w.is_empty())
            .collect();
        if words.is_empty() {
            return Ok(Vec::new());
        }
        let fts_query = words.join(" OR ");

        let mut stmt = conn
            .prepare(
                "SELECT d.content, d.source, d.metadata,
                        bm25(documents_fts, 1.0, 0.5) * -1 as score
                 FROM documents_fts f
                 JOIN documents d ON d.rowid = f.rowid
                 WHERE documents_fts MATCH ?1
                 ORDER BY bm25(documents_fts, 1.0, 0.5)
                 LIMIT ?2",
            )
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;

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
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?
            .filter_map(|r| r.ok())
            .collect();

        Ok(results)
    }

    fn delete(&self, doc_id: &str) -> Result<bool, OpenJarvisError> {
        let conn = self.conn.lock();
        // Delete from FTS5 using the rowid from the documents table
        conn.execute(
            "DELETE FROM documents_fts WHERE rowid = (SELECT rowid FROM documents WHERE id = ?1)",
            rusqlite::params![doc_id],
        )
        .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        let changes = conn
            .execute(
                "DELETE FROM documents WHERE id = ?1",
                rusqlite::params![doc_id],
            )
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        Ok(changes > 0)
    }

    fn clear(&self) -> Result<(), OpenJarvisError> {
        let conn = self.conn.lock();
        conn.execute_batch("DELETE FROM documents_fts; DELETE FROM documents")
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        Ok(())
    }

    fn count(&self) -> Result<usize, OpenJarvisError> {
        let conn = self.conn.lock();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM documents", [], |row| row.get(0))
            .map_err(|e| OpenJarvisError::Io(std::io::Error::other(e.to_string())))?;
        Ok(count as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sqlite_store_and_retrieve() {
        let mem = SQLiteMemory::in_memory().unwrap();
        let id = mem
            .store("Rust is a systems programming language", "test", None)
            .unwrap();
        assert!(!id.is_empty());

        let results = mem.retrieve("Rust programming", 5).unwrap();
        assert!(!results.is_empty());
        assert!(results[0].content.contains("Rust"));
        assert!(
            results[0].score > 0.0,
            "score should be positive, got {}",
            results[0].score
        );
    }

    #[test]
    fn test_sqlite_porter_stemming() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("Medication list for patient", "health", None)
            .unwrap();

        // Plural form should match via porter stemming
        let results = mem.retrieve("medications", 5).unwrap();
        assert!(
            !results.is_empty(),
            "porter stemming should match 'medications' to 'Medication'"
        );
        assert!(results[0].score > 0.0);
    }

    #[test]
    fn test_sqlite_punctuation_stripping() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("Medication list for patient Micah", "health", None)
            .unwrap();

        // Natural language query with trailing punctuation should not break FTS5
        let results = mem
            .retrieve("What medications does Micah take?", 5)
            .unwrap();
        assert!(
            !results.is_empty(),
            "query with punctuation should still return results"
        );
        assert!(results[0].score > 0.0);
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
    fn test_sqlite_replace_source_is_idempotent() {
        let mem = SQLiteMemory::in_memory().unwrap();

        mem.replace_source("notes.txt", &[("old project notes", None)])
            .unwrap();
        assert_eq!(mem.count().unwrap(), 1);

        mem.replace_source("notes.txt", &[("updated project notes", None)])
            .unwrap();
        assert_eq!(mem.count().unwrap(), 1);

        assert!(mem.retrieve("old", 5).unwrap().is_empty());
        let updated = mem.retrieve("updated", 5).unwrap();
        assert_eq!(updated.len(), 1);
        assert_eq!(updated[0].source, "notes.txt");
    }

    #[test]
    fn test_sqlite_replace_source_preserves_other_sources() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("keep this manual", "manual.txt", None).unwrap();
        mem.replace_source("notes.txt", &[("old project notes", None)])
            .unwrap();

        mem.replace_source("notes.txt", &[("updated project notes", None)])
            .unwrap();

        assert_eq!(mem.count().unwrap(), 2);
        let manual = mem.retrieve("manual", 5).unwrap();
        assert_eq!(manual.len(), 1);
        assert_eq!(manual[0].source, "manual.txt");
    }

    #[test]
    fn test_sqlite_case_insensitive_search() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("Medication dosage guidelines for patients", "medical", None)
            .unwrap();
        mem.store("The medication was prescribed yesterday", "medical", None)
            .unwrap();

        // Lowercase query should match uppercase content
        let lower = mem.retrieve("medication", 10).unwrap();
        assert_eq!(lower.len(), 2, "lowercase query should find both documents");

        // Uppercase query should also match
        let upper = mem.retrieve("MEDICATION", 10).unwrap();
        assert_eq!(upper.len(), 2, "uppercase query should find both documents");

        // Mixed case
        let mixed = mem.retrieve("Medication", 10).unwrap();
        assert_eq!(
            mixed.len(),
            2,
            "mixed-case query should find both documents"
        );
    }

    #[test]
    fn test_sqlite_apostrophe_in_query() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("The user's name is Trev.", "identity", None)
            .unwrap();

        // A query containing an internal apostrophe must not break FTS5's
        // MATCH syntax (an unescaped `'` is a string delimiter in FTS5's
        // query grammar), which previously caused this to silently return
        // zero results instead of matching or erroring.
        let multi_word = mem.retrieve("what is the user's name", 5).unwrap();
        assert!(
            !multi_word.is_empty(),
            "query with an internal apostrophe should not silently return zero results"
        );

        // Bare single-word possessive: exercises the (former) single-word
        // bypass path that skipped the OR-join entirely.
        let bare = mem.retrieve("user's", 5).unwrap();
        assert!(
            !bare.is_empty(),
            "single-word possessive query should still match"
        );
    }

    #[test]
    fn test_sqlite_scores_are_positive() {
        let mem = SQLiteMemory::in_memory().unwrap();
        mem.store("Rust is a systems programming language", "docs", None)
            .unwrap();
        mem.store("Python is a high-level programming language", "docs", None)
            .unwrap();
        mem.store("Cooking recipes for beginners", "other", None)
            .unwrap();

        let results = mem.retrieve("programming", 5).unwrap();
        assert!(!results.is_empty());
        for r in &results {
            assert!(r.score > 0.0, "score should be positive, got {}", r.score);
        }
    }

    #[test]
    fn test_sqlite_uses_wal_journal_mode_and_longer_busy_timeout() {
        // Regression for #756: without WAL mode, memory.db runs in
        // rollback-journal mode where any concurrent writer blocks all
        // readers, and rusqlite's default 5s busy_timeout was too short
        // under realistic contention.
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("memory.db");
        let mem = SQLiteMemory::new(&db_path).unwrap();

        let conn = mem.conn.lock();

        let journal_mode: String = conn
            .query_row("PRAGMA journal_mode", [], |row| row.get(0))
            .unwrap();
        assert_eq!(
            journal_mode.to_lowercase(),
            "wal",
            "expected WAL journal mode for a file-backed database"
        );

        let busy_timeout_ms: i64 = conn
            .query_row("PRAGMA busy_timeout", [], |row| row.get(0))
            .unwrap();
        assert!(
            busy_timeout_ms >= 10_000,
            "expected busy_timeout of at least 10000ms, got {busy_timeout_ms}"
        );
    }

    #[test]
    fn test_sqlite_wal_reader_remains_available_during_write_transaction() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("memory.db");
        let writer = SQLiteMemory::new(&db_path).unwrap();
        writer.store("baseline document", "test", None).unwrap();
        let reader = SQLiteMemory::new(&db_path).unwrap();

        let writer_conn = writer.conn.lock();
        writer_conn.execute_batch("BEGIN EXCLUSIVE").unwrap();

        let outcome = std::thread::scope(|scope| {
            let (tx, rx) = std::sync::mpsc::channel();
            let reader = &reader;
            scope.spawn(move || {
                let result = reader
                    .retrieve("baseline", 5)
                    .map(|results| results.len())
                    .map_err(|error| error.to_string());
                tx.send(result).unwrap();
            });
            let result = rx.recv_timeout(std::time::Duration::from_secs(1));
            writer_conn.execute_batch("ROLLBACK").unwrap();
            result
        });

        let result = outcome.expect("WAL reader blocked behind an active writer");
        assert_eq!(result.unwrap(), 1);
    }

    #[test]
    fn test_sqlite_busy_timeout_serializes_competing_writers() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("memory.db");
        let first = SQLiteMemory::new(&db_path).unwrap();
        let second = SQLiteMemory::new(&db_path).unwrap();

        let first_conn = first.conn.lock();
        first_conn.execute_batch("BEGIN IMMEDIATE").unwrap();

        let outcome = std::thread::scope(|scope| {
            let (tx, rx) = std::sync::mpsc::channel();
            let second_worker = &second;
            scope.spawn(move || {
                let result = second_worker
                    .store("concurrent write", "test", None)
                    .map(|_| ())
                    .map_err(|error| error.to_string());
                tx.send(result).unwrap();
            });

            std::thread::sleep(std::time::Duration::from_millis(100));
            let premature = rx.try_recv();
            first_conn.execute_batch("COMMIT").unwrap();
            assert!(
                matches!(premature, Err(std::sync::mpsc::TryRecvError::Empty)),
                "competing writer did not wait for the active transaction: {premature:?}"
            );
            rx.recv_timeout(std::time::Duration::from_secs(2))
        });

        outcome
            .expect("competing writer did not resume after commit")
            .expect("competing writer failed instead of waiting");
        assert_eq!(second.count().unwrap(), 1);
    }
}
