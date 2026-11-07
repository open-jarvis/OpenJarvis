//! Hybrid memory backend — Reciprocal Rank Fusion (RRF) over multiple backends.
//!
//! Combines results from multiple `MemoryBackend` implementations by fusing their
//! ranked result lists using the RRF formula:
//!
//! ```text
//! score(doc) = sum_over_backends( 1 / (k + rank_i) )
//! ```
//!
//! where `k` is a smoothing constant (default 60) and `rank_i` is the 1-based rank
//! of the document in backend `i`'s result list (or absent if not returned).

use crate::storage::traits::MemoryBackend;
use friday_ai_core::{FridayAIError, RetrievalResult};
use std::collections::HashMap;

/// Default RRF smoothing constant.
const DEFAULT_K: f64 = 60.0;

/// Hybrid memory backend that fuses results from multiple backends via RRF.
pub struct HybridMemory {
    backends: Vec<Box<dyn MemoryBackend>>,
    k: f64,
}

impl HybridMemory {
    /// Create a new `HybridMemory` combining the given backends with default `k=60`.
    pub fn new(backends: Vec<Box<dyn MemoryBackend>>) -> Self {
        Self {
            backends,
            k: DEFAULT_K,
        }
    }

    /// Create a new `HybridMemory` with a custom RRF smoothing constant.
    pub fn with_k(backends: Vec<Box<dyn MemoryBackend>>, k: f64) -> Self {
        Self { backends, k }
    }

    /// Fuse ranked result lists from multiple backends using Reciprocal Rank Fusion.
    ///
    /// Each result is keyed by its `content` field.  When the same document appears
    /// in multiple backends, scores are summed.
    fn fuse_results(
        &self,
        per_backend_results: Vec<Vec<RetrievalResult>>,
        top_k: usize,
    ) -> Vec<RetrievalResult> {
        // Map: content -> (accumulated_rrf_score, best_result)
        let mut fused: HashMap<String, (f64, RetrievalResult)> = HashMap::new();

        for results in &per_backend_results {
            for (rank_0, result) in results.iter().enumerate() {
                let rrf_score = 1.0 / (self.k + (rank_0 + 1) as f64);
                let entry = fused
                    .entry(result.content.clone())
                    .or_insert_with(|| (0.0, result.clone()));
                entry.0 += rrf_score;
            }
        }

        let mut scored: Vec<(f64, RetrievalResult)> = fused
            .into_values()
            .map(|(rrf_score, mut result)| {
                result.score = rrf_score;
                (rrf_score, result)
            })
            .collect();

        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(top_k);

        scored.into_iter().map(|(_, r)| r).collect()
    }
}

impl MemoryBackend for HybridMemory {
    fn backend_id(&self) -> &str {
        "hybrid"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&serde_json::Value>,
    ) -> Result<String, FridayAIError> {
        let mut last_id = String::new();
        for backend in &self.backends {
            last_id = backend.store(content, source, metadata)?;
        }
        Ok(last_id)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError> {
        // Ask each backend for a generous number of results to give RRF enough data.
        let fetch_k = top_k * 3;
        let mut per_backend: Vec<Vec<RetrievalResult>> = Vec::with_capacity(self.backends.len());
        for backend in &self.backends {
            per_backend.push(backend.retrieve(query, fetch_k)?);
        }
        Ok(self.fuse_results(per_backend, top_k))
    }

    fn delete(&self, doc_id: &str) -> Result<bool, FridayAIError> {
        let mut any_deleted = false;
        for backend in &self.backends {
            if backend.delete(doc_id)? {
                any_deleted = true;
            }
        }
        Ok(any_deleted)
    }

    fn clear(&self) -> Result<(), FridayAIError> {
        for backend in &self.backends {
            backend.clear()?;
        }
        Ok(())
    }

    fn count(&self) -> Result<usize, FridayAIError> {
        // Return count from the first backend (all should be in sync after store/delete).
        self.backends
            .first()
            .map(|b| b.count())
            .unwrap_or(Ok(0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::bm25::BM25Memory;
    use crate::storage::sqlite::SQLiteMemory;

    fn make_hybrid() -> HybridMemory {
        let sqlite = SQLiteMemory::in_memory().unwrap();
        let bm25 = BM25Memory::default();
        HybridMemory::new(vec![Box::new(sqlite), Box::new(bm25)])
    }

    #[test]
    fn test_hybrid_store_and_retrieve() {
        let mem = make_hybrid();
        mem.store("Rust is fast and safe", "doc1", None).unwrap();
        mem.store("Python is easy to learn", "doc2", None).unwrap();
        mem.store("Rust and C++ are systems languages", "doc3", None)
            .unwrap();

        let results = mem.retrieve("Rust programming", 3).unwrap();
        assert!(!results.is_empty());
        // Top result should mention Rust (both backends agree)
        assert!(results[0].content.contains("Rust"));
    }

    #[test]
    fn test_hybrid_rrf_scores() {
        let mem = make_hybrid();
        mem.store("alpha beta gamma", "s1", None).unwrap();
        mem.store("beta gamma delta", "s2", None).unwrap();

        let results = mem.retrieve("beta", 5).unwrap();
        // Both docs should appear; RRF scores should be > 0
        for r in &results {
            assert!(r.score > 0.0);
        }
    }

    #[test]
    fn test_hybrid_delete() {
        let mem = make_hybrid();
        let id = mem.store("test content", "test", None).unwrap();
        // At least one backend should report deletion
        assert!(mem.delete(&id).unwrap());
    }

    #[test]
    fn test_hybrid_clear() {
        let mem = make_hybrid();
        mem.store("doc 1", "s1", None).unwrap();
        mem.store("doc 2", "s2", None).unwrap();
        mem.clear().unwrap();
        assert_eq!(mem.count().unwrap(), 0);
    }

    #[test]
    fn test_hybrid_empty() {
        let mem = make_hybrid();
        let results = mem.retrieve("anything", 5).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn test_hybrid_no_backends() {
        let mem = HybridMemory::new(vec![]);
        assert_eq!(mem.count().unwrap(), 0);
        let results = mem.retrieve("test", 5).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn test_hybrid_custom_k() {
        let sqlite = SQLiteMemory::in_memory().unwrap();
        let bm25 = BM25Memory::default();
        let mem = HybridMemory::with_k(vec![Box::new(sqlite), Box::new(bm25)], 10.0);
        mem.store("hello world", "s1", None).unwrap();

        let results = mem.retrieve("hello", 5).unwrap();
        assert!(!results.is_empty());
        // With k=10, RRF score for rank-1 from both backends:
        // 2 * (1 / (10 + 1)) = 2/11 ~ 0.1818
        let expected = 2.0 / 11.0;
        assert!((results[0].score - expected).abs() < 1e-6);
    }

    #[test]
    fn test_fuse_deduplication() {
        let mem = HybridMemory::with_k(vec![], 60.0);
        // Two backends returning the same doc at rank 1
        let r1 = vec![RetrievalResult {
            content: "same doc".to_string(),
            source: "s1".to_string(),
            score: 5.0,
            metadata: HashMap::new(),
        }];
        let r2 = vec![RetrievalResult {
            content: "same doc".to_string(),
            source: "s1".to_string(),
            score: 3.0,
            metadata: HashMap::new(),
        }];
        let fused = mem.fuse_results(vec![r1, r2], 10);
        assert_eq!(fused.len(), 1);
        // RRF: 1/(60+1) + 1/(60+1) = 2/61
        let expected = 2.0 / 61.0;
        assert!((fused[0].score - expected).abs() < 1e-10);
    }
}
