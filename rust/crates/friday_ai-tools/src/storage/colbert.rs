//! ColBERT-style memory backend — token-level embeddings with MaxSim scoring.
//!
//! ColBERT represents queries and documents as sequences of token embeddings and
//! computes relevance via **MaxSim**: for each query token, find the maximum cosine
//! similarity to any document token, then sum across query tokens.
//!
//! Like `FAISSMemory`, actual embedding is handled externally (Python / LLM).  This
//! module provides the retrieval math and SQLite-backed persistence.

use crate::storage::traits::MemoryBackend;
use friday_ai_core::{FridayAIError, RetrievalResult};
use parking_lot::Mutex;
use rusqlite::Connection;
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use uuid::Uuid;

/// Default token embedding dimension for the dummy `embed_tokens()` stub.
const DEFAULT_TOKEN_DIM: usize = 64;

/// ColBERT-style memory backend with MaxSim scoring over token-level embeddings.
pub struct ColBERTMemory {
    conn: Mutex<Connection>,
    _db_path: PathBuf,
    token_dim: usize,
}

impl ColBERTMemory {
    pub fn new(db_path: &Path, token_dim: usize) -> Result<Self, FridayAIError> {
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
            "CREATE TABLE IF NOT EXISTS colbert_documents (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                num_tokens INTEGER NOT NULL,
                token_embeddings BLOB NOT NULL,
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
            token_dim,
        })
    }

    pub fn in_memory() -> Result<Self, FridayAIError> {
        Self::new(Path::new(":memory:"), DEFAULT_TOKEN_DIM)
    }

    pub fn with_dim(token_dim: usize) -> Result<Self, FridayAIError> {
        Self::new(Path::new(":memory:"), token_dim)
    }

    /// Dummy token-level embedding stub.
    ///
    /// Splits text on whitespace and produces one normalised vector per token by
    /// hashing the token bytes.  Real token embeddings should be supplied externally.
    pub fn embed_tokens(&self, text: &str) -> Vec<Vec<f64>> {
        text.split_whitespace()
            .map(|token| {
                let mut vec = vec![0.0f64; self.token_dim];
                for (i, byte) in token.bytes().enumerate() {
                    vec[i % self.token_dim] += byte as f64;
                }
                let norm = vec.iter().map(|x| x * x).sum::<f64>().sqrt();
                if norm > 0.0 {
                    for v in &mut vec {
                        *v /= norm;
                    }
                }
                vec
            })
            .collect()
    }

    /// Store a document with pre-computed token-level embeddings.
    ///
    /// `token_embeddings` is a slice of vectors — one per token.  All vectors must
    /// have the same dimension.
    pub fn store_with_token_embeddings(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
        token_embeddings: &[Vec<f64>],
    ) -> Result<String, FridayAIError> {
        let doc_id = Uuid::new_v4().to_string();
        let meta_str = metadata
            .map(|m| serde_json::to_string(m).unwrap_or_default())
            .unwrap_or_else(|| "{}".to_string());
        let num_tokens = token_embeddings.len() as i64;
        let emb_bytes = token_embeddings_to_bytes(token_embeddings);

        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO colbert_documents (id, content, source, metadata, num_tokens, token_embeddings)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            rusqlite::params![doc_id, content, source, meta_str, num_tokens, emb_bytes],
        )
        .map_err(|e| {
            FridayAIError::Io(std::io::Error::other(
                e.to_string(),
            ))
        })?;

        Ok(doc_id)
    }

    /// Retrieve the top-k documents using MaxSim scoring against pre-computed query
    /// token embeddings.
    pub fn retrieve_by_token_embeddings(
        &self,
        query_token_embeddings: &[Vec<f64>],
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError> {
        let conn = self.conn.lock();

        let mut stmt = conn
            .prepare(
                "SELECT id, content, source, metadata, num_tokens, token_embeddings
                 FROM colbert_documents",
            )
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;

        let rows: Vec<(String, String, String, usize, Vec<u8>)> = stmt
            .query_map([], |row| {
                let content: String = row.get(1)?;
                let source: String = row.get::<_, String>(2).unwrap_or_default();
                let meta_str: String = row.get::<_, String>(3).unwrap_or_else(|_| "{}".into());
                let num_tokens: i64 = row.get(4)?;
                let emb_bytes: Vec<u8> = row.get(5)?;
                Ok((content, source, meta_str, num_tokens as usize, emb_bytes))
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
            .map(|(content, source, meta_str, num_tokens, emb_bytes)| {
                let doc_token_embs =
                    bytes_to_token_embeddings(&emb_bytes, num_tokens, self.token_dim);
                let score = maxsim(query_token_embeddings, &doc_token_embs);
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

impl MemoryBackend for ColBERTMemory {
    fn backend_id(&self) -> &str {
        "colbert"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, FridayAIError> {
        let token_embeddings = self.embed_tokens(content);
        self.store_with_token_embeddings(content, source, metadata, &token_embeddings)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError> {
        let query_token_embeddings = self.embed_tokens(query);
        if query_token_embeddings.is_empty() {
            return Ok(vec![]);
        }
        self.retrieve_by_token_embeddings(&query_token_embeddings, top_k)
    }

    fn delete(&self, doc_id: &str) -> Result<bool, FridayAIError> {
        let conn = self.conn.lock();
        let changes = conn
            .execute(
                "DELETE FROM colbert_documents WHERE id = ?1",
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
        conn.execute_batch("DELETE FROM colbert_documents")
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
            .query_row("SELECT COUNT(*) FROM colbert_documents", [], |row| {
                row.get(0)
            })
            .map_err(|e| {
                FridayAIError::Io(std::io::Error::other(
                    e.to_string(),
                ))
            })?;
        Ok(count as usize)
    }
}

// ---------------------------------------------------------------------------
// MaxSim and helpers
// ---------------------------------------------------------------------------

/// MaxSim scoring: for each query token, find max cosine similarity across all
/// document tokens, then sum.
fn maxsim(query_tokens: &[Vec<f64>], doc_tokens: &[Vec<f64>]) -> f64 {
    if query_tokens.is_empty() || doc_tokens.is_empty() {
        return 0.0;
    }
    query_tokens
        .iter()
        .map(|q| {
            doc_tokens
                .iter()
                .map(|d| cosine_similarity(q, d))
                .fold(f64::NEG_INFINITY, f64::max)
        })
        .sum()
}

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

/// Serialize a sequence of token embeddings into a flat byte blob.
///
/// Layout: token_0[0..dim] ++ token_1[0..dim] ++ ... (all f64 little-endian).
fn token_embeddings_to_bytes(embeddings: &[Vec<f64>]) -> Vec<u8> {
    embeddings
        .iter()
        .flat_map(|tok| tok.iter().flat_map(|f| f.to_le_bytes()))
        .collect()
}

/// Deserialize a flat byte blob back into a `Vec<Vec<f64>>` of token embeddings.
fn bytes_to_token_embeddings(bytes: &[u8], num_tokens: usize, dim: usize) -> Vec<Vec<f64>> {
    let floats: Vec<f64> = bytes
        .chunks_exact(8)
        .map(|chunk| {
            let arr: [u8; 8] = chunk.try_into().unwrap_or([0u8; 8]);
            f64::from_le_bytes(arr)
        })
        .collect();

    floats
        .chunks(dim)
        .take(num_tokens)
        .map(|chunk| chunk.to_vec())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_colbert_store_and_retrieve() {
        let mem = ColBERTMemory::in_memory().unwrap();
        let id = mem
            .store("Rust is a systems programming language", "test", None)
            .unwrap();
        assert!(!id.is_empty());

        let results = mem.retrieve("Rust programming", 5).unwrap();
        assert!(!results.is_empty());
        assert!(results[0].content.contains("Rust"));
    }

    #[test]
    fn test_colbert_maxsim_ranking() {
        let mem = ColBERTMemory::with_dim(3).unwrap();

        // Doc A: two tokens
        let doc_a_tokens = vec![vec![1.0, 0.0, 0.0], vec![0.0, 1.0, 0.0]];
        // Doc B: two tokens — orthogonal to query
        let doc_b_tokens = vec![vec![0.0, 0.0, 1.0], vec![0.0, 0.0, 1.0]];

        mem.store_with_token_embeddings("doc A", "s1", None, &doc_a_tokens)
            .unwrap();
        mem.store_with_token_embeddings("doc B", "s2", None, &doc_b_tokens)
            .unwrap();

        // Query: single token close to doc A's first token
        let query_tokens = vec![vec![1.0, 0.0, 0.0]];
        let results = mem.retrieve_by_token_embeddings(&query_tokens, 2).unwrap();
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].content, "doc A");
    }

    #[test]
    fn test_colbert_delete() {
        let mem = ColBERTMemory::in_memory().unwrap();
        let id = mem.store("test content", "test", None).unwrap();
        assert_eq!(mem.count().unwrap(), 1);
        assert!(mem.delete(&id).unwrap());
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_colbert_clear() {
        let mem = ColBERTMemory::in_memory().unwrap();
        mem.store("doc 1", "s1", None).unwrap();
        mem.store("doc 2", "s2", None).unwrap();
        assert_eq!(mem.count().unwrap(), 2);
        mem.clear().unwrap();
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_colbert_empty_retrieve() {
        let mem = ColBERTMemory::in_memory().unwrap();
        let results = mem.retrieve("anything", 5).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn test_maxsim_computation() {
        // Query: 1 token = [1, 0]
        // Doc:   2 tokens = [0.5, 0.5], [1, 0]
        // MaxSim for query token [1,0] = max(cos([1,0],[0.5,0.5]), cos([1,0],[1,0]))
        //                               = max(~0.707, 1.0) = 1.0
        let q = vec![vec![1.0, 0.0]];
        let d = vec![vec![0.5, 0.5], vec![1.0, 0.0]];
        let score = maxsim(&q, &d);
        assert!((score - 1.0).abs() < 1e-10);
    }

    #[test]
    fn test_token_embeddings_roundtrip() {
        let embeddings = vec![
            vec![1.0, 2.0, 3.0],
            vec![4.0, 5.0, 6.0],
        ];
        let bytes = token_embeddings_to_bytes(&embeddings);
        let recovered = bytes_to_token_embeddings(&bytes, 2, 3);
        assert_eq!(embeddings, recovered);
    }
}
