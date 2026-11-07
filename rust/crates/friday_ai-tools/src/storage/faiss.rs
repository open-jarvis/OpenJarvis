//! FAISS-style vector similarity memory backend — pure Rust brute-force cosine similarity.

use crate::storage::traits::MemoryBackend;
use friday_ai_core::{FridayAIError, RetrievalResult};
use parking_lot::Mutex;
use rusqlite::Connection;
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use uuid::Uuid;

/// Default embedding dimension used by the dummy `embed()` stub.
const DEFAULT_DIM: usize = 128;

/// FAISS-style memory backend using brute-force cosine similarity over stored embeddings.
///
/// Documents and their embeddings are persisted in SQLite.  The `retrieve()` method
/// computes cosine similarity between a query embedding and every stored embedding,
/// returning the top-k closest results.
///
/// Because real embedding requires an external model (Python / LLM), the `embed()`
/// method provided here is a deterministic **stub** that hashes the input text into a
/// fixed-dimension vector.  Callers that have real embeddings should use
/// `store_with_embedding()` and `retrieve_by_embedding()` directly.
pub struct FAISSMemory {
    conn: Mutex<Connection>,
    _db_path: PathBuf,
    dim: usize,
}

impl FAISSMemory {
    pub fn new(db_path: &Path, dim: usize) -> Result<Self, FridayAIError> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                FridayAIError::Io(std::io::Error::other(e))
            })?;
        }

        let conn = Connection::open(db_path).map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS faiss_documents (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                embedding BLOB NOT NULL,
                created_at REAL DEFAULT (julianday('now'))
            );",
        )
        .map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(Self {
            conn: Mutex::new(conn),
            _db_path: db_path.to_path_buf(),
            dim,
        })
    }

    pub fn in_memory() -> Result<Self, FridayAIError> {
        Self::new(Path::new(":memory:"), DEFAULT_DIM)
    }

    pub fn with_dim(dim: usize) -> Result<Self, FridayAIError> {
        Self::new(Path::new(":memory:"), dim)
    }

    /// Dummy embedding stub — produces a deterministic vector from text by hashing.
    ///
    /// Real embeddings should be provided externally (e.g. from Python / an LLM).
    pub fn embed(&self, text: &str) -> Vec<f64> {
        let mut vec = vec![0.0f64; self.dim];
        for (i, byte) in text.bytes().enumerate() {
            vec[i % self.dim] += byte as f64;
        }
        // L2-normalise so cosine similarity is meaningful.
        let norm = vec.iter().map(|x| x * x).sum::<f64>().sqrt();
        if norm > 0.0 {
            for v in &mut vec {
                *v /= norm;
            }
        }
        vec
    }

    /// Store a document with a pre-computed embedding.
    pub fn store_with_embedding(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
        embedding: &[f64],
    ) -> Result<String, FridayAIError> {
        let doc_id = Uuid::new_v4().to_string();
        let meta_str = metadata
            .map(|m| serde_json::to_string(m).unwrap_or_default())
            .unwrap_or_else(|| "{}".to_string());
        let emb_bytes = embedding_to_bytes(embedding);

        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO faiss_documents (id, content, source, metadata, embedding)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            rusqlite::params![doc_id, content, source, meta_str, emb_bytes],
        )
        .map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(doc_id)
    }

    /// Retrieve the top-k documents closest to a pre-computed query embedding.
    pub fn retrieve_by_embedding(
        &self,
        query_embedding: &[f64],
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError> {
        let conn = self.conn.lock();

        let mut stmt = conn
            .prepare(
                "SELECT id, content, source, metadata, embedding FROM faiss_documents",
            )
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let rows: Vec<(String, String, String, Vec<f64>)> = stmt
            .query_map([], |row| {
                let content: String = row.get(1)?;
                let source: String = row.get::<_, String>(2).unwrap_or_default();
                let meta_str: String = row.get::<_, String>(3).unwrap_or_else(|_| "{}".into());
                let emb_bytes: Vec<u8> = row.get(4)?;
                Ok((content, source, meta_str, bytes_to_embedding(&emb_bytes)))
            })
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?
            .filter_map(|r| r.ok())
            .collect();

        let mut scored: Vec<(RetrievalResult, f64)> = rows
            .into_iter()
            .map(|(content, source, meta_str, emb)| {
                let score = cosine_similarity(query_embedding, &emb);
                let metadata: HashMap<String, Value> =
                    serde_json::from_str(&meta_str).unwrap_or_default();
                (
                    RetrievalResult {
                        content,
                        source,
                        score,
                        metadata,
                    },
                    score,
                )
            })
            .collect();

        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(top_k);

        Ok(scored.into_iter().map(|(r, _)| r).collect())
    }
}

impl MemoryBackend for FAISSMemory {
    fn backend_id(&self) -> &str {
        "faiss"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, FridayAIError> {
        let embedding = self.embed(content);
        self.store_with_embedding(content, source, metadata, &embedding)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError> {
        let query_embedding = self.embed(query);
        self.retrieve_by_embedding(&query_embedding, top_k)
    }

    fn delete(&self, doc_id: &str) -> Result<bool, FridayAIError> {
        let conn = self.conn.lock();
        let changes = conn
            .execute(
                "DELETE FROM faiss_documents WHERE id = ?1",
                rusqlite::params![doc_id],
            )
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(changes > 0)
    }

    fn clear(&self) -> Result<(), FridayAIError> {
        let conn = self.conn.lock();
        conn.execute_batch("DELETE FROM faiss_documents")
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(())
    }

    fn count(&self) -> Result<usize, FridayAIError> {
        let conn = self.conn.lock();
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM faiss_documents", [], |row| row.get(0))
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(count as usize)
    }
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/// Cosine similarity between two vectors.
fn cosine_similarity(a: &[f64], b: &[f64]) -> f64 {
    let len = a.len().min(b.len());
    let mut dot = 0.0f64;
    let mut norm_a = 0.0f64;
    let mut norm_b = 0.0f64;
    for i in 0..len {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }
    let denom = norm_a.sqrt() * norm_b.sqrt();
    if denom == 0.0 {
        0.0
    } else {
        dot / denom
    }
}

/// Serialize a `&[f64]` embedding into little-endian bytes for SQLite BLOB storage.
fn embedding_to_bytes(embedding: &[f64]) -> Vec<u8> {
    embedding.iter().flat_map(|f| f.to_le_bytes()).collect()
}

/// Deserialize a byte slice back into a `Vec<f64>`.
fn bytes_to_embedding(bytes: &[u8]) -> Vec<f64> {
    bytes
        .chunks_exact(8)
        .map(|chunk| {
            let arr: [u8; 8] = chunk.try_into().unwrap_or([0u8; 8]);
            f64::from_le_bytes(arr)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_faiss_store_and_retrieve() {
        let mem = FAISSMemory::in_memory().unwrap();
        let id = mem
            .store("Rust is a systems programming language", "test", None)
            .unwrap();
        assert!(!id.is_empty());

        let results = mem.retrieve("Rust programming", 5).unwrap();
        assert!(!results.is_empty());
        assert!(results[0].content.contains("Rust"));
    }

    #[test]
    fn test_faiss_cosine_ranking() {
        let mem = FAISSMemory::in_memory().unwrap();
        mem.store("Rust is fast and safe", "doc1", None).unwrap();
        mem.store("Python is easy to learn", "doc2", None).unwrap();
        mem.store("Rust and C++ are systems languages", "doc3", None)
            .unwrap();

        let results = mem.retrieve("Rust systems", 3).unwrap();
        assert!(!results.is_empty());
        // The top result should mention Rust
        assert!(results[0].content.contains("Rust"));
    }

    #[test]
    fn test_faiss_delete() {
        let mem = FAISSMemory::in_memory().unwrap();
        let id = mem.store("test content", "test", None).unwrap();
        assert_eq!(mem.count().unwrap(), 1);
        assert!(mem.delete(&id).unwrap());
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_faiss_clear() {
        let mem = FAISSMemory::in_memory().unwrap();
        mem.store("doc 1", "s1", None).unwrap();
        mem.store("doc 2", "s2", None).unwrap();
        assert_eq!(mem.count().unwrap(), 2);
        mem.clear().unwrap();
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_faiss_with_real_embeddings() {
        let mem = FAISSMemory::in_memory().unwrap();
        let emb1 = vec![1.0, 0.0, 0.0];
        let emb2 = vec![0.0, 1.0, 0.0];
        let emb3 = vec![0.9, 0.1, 0.0];

        mem.store_with_embedding("doc A", "s1", None, &emb1)
            .unwrap();
        mem.store_with_embedding("doc B", "s2", None, &emb2)
            .unwrap();
        mem.store_with_embedding("doc C", "s3", None, &emb3)
            .unwrap();

        let query_emb = vec![1.0, 0.0, 0.0];
        let results = mem.retrieve_by_embedding(&query_emb, 2).unwrap();
        assert_eq!(results.len(), 2);
        // doc A should be closest to query (identical vector)
        assert_eq!(results[0].content, "doc A");
        // doc C should be second (0.9 cosine similarity)
        assert_eq!(results[1].content, "doc C");
    }

    #[test]
    fn test_faiss_empty_retrieve() {
        let mem = FAISSMemory::in_memory().unwrap();
        let results = mem.retrieve("anything", 5).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn test_embed_deterministic() {
        let mem = FAISSMemory::in_memory().unwrap();
        let e1 = mem.embed("hello world");
        let e2 = mem.embed("hello world");
        assert_eq!(e1, e2);
    }

    #[test]
    fn test_cosine_similarity_identical() {
        let a = vec![1.0, 2.0, 3.0];
        assert!((cosine_similarity(&a, &a) - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_cosine_similarity_orthogonal() {
        let a = vec![1.0, 0.0];
        let b = vec![0.0, 1.0];
        assert!((cosine_similarity(&a, &b)).abs() < 1e-10);
    }

    #[test]
    fn test_embedding_roundtrip() {
        #[allow(clippy::approx_constant)]
        let emb = vec![1.0, -2.5, 3.14, 0.0];
        let bytes = embedding_to_bytes(&emb);
        let recovered = bytes_to_embedding(&bytes);
        assert_eq!(emb, recovered);
    }
}
