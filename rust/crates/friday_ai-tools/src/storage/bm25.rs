//! BM25 memory backend — pure Rust BM25 scoring.

use crate::storage::traits::MemoryBackend;
use friday_ai_core::{FridayAIError, RetrievalResult};
use parking_lot::RwLock;
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

struct Document {
    id: String,
    content: String,
    source: String,
    metadata: HashMap<String, Value>,
    terms: HashMap<String, usize>,
    term_count: usize,
}

pub struct BM25Memory {
    docs: RwLock<Vec<Document>>,
    k1: f64,
    b: f64,
}

impl BM25Memory {
    pub fn new(k1: f64, b: f64) -> Self {
        Self {
            docs: RwLock::new(Vec::new()),
            k1,
            b,
        }
    }

    fn tokenize(text: &str) -> HashMap<String, usize> {
        let mut counts = HashMap::new();
        for word in text.split_whitespace() {
            let normalized = word.to_lowercase().trim_matches(|c: char| !c.is_alphanumeric()).to_string();
            if !normalized.is_empty() {
                *counts.entry(normalized).or_insert(0) += 1;
            }
        }
        counts
    }

    fn score_doc(
        &self,
        doc: &Document,
        query_terms: &HashMap<String, usize>,
        avg_dl: f64,
        n: f64,
        df: &HashMap<String, usize>,
    ) -> f64 {
        let mut score = 0.0;
        let dl = doc.term_count as f64;

        for term in query_terms.keys() {
            let tf = *doc.terms.get(term).unwrap_or(&0) as f64;
            let doc_freq = *df.get(term).unwrap_or(&0) as f64;
            if doc_freq == 0.0 || tf == 0.0 {
                continue;
            }

            let idf = ((n - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0).ln();
            let tf_norm = (tf * (self.k1 + 1.0))
                / (tf + self.k1 * (1.0 - self.b + self.b * dl / avg_dl));
            score += idf * tf_norm;
        }
        score
    }
}

impl Default for BM25Memory {
    fn default() -> Self {
        Self::new(1.2, 0.75)
    }
}

impl MemoryBackend for BM25Memory {
    fn backend_id(&self) -> &str {
        "bm25"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, FridayAIError> {
        let doc_id = Uuid::new_v4().to_string();
        let terms = Self::tokenize(content);
        let term_count = terms.values().sum();
        let meta: HashMap<String, Value> = metadata
            .and_then(|m| serde_json::from_value(m.clone()).ok())
            .unwrap_or_default();

        let doc = Document {
            id: doc_id.clone(),
            content: content.to_string(),
            source: source.to_string(),
            metadata: meta,
            terms,
            term_count,
        };

        self.docs.write().push(doc);
        Ok(doc_id)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError> {
        let docs = self.docs.read();
        if docs.is_empty() {
            return Ok(vec![]);
        }

        let query_terms = Self::tokenize(query);
        let n = docs.len() as f64;
        let avg_dl = docs.iter().map(|d| d.term_count as f64).sum::<f64>() / n;

        let mut df: HashMap<String, usize> = HashMap::new();
        for doc in docs.iter() {
            for term in doc.terms.keys() {
                *df.entry(term.clone()).or_insert(0) += 1;
            }
        }

        let mut scored: Vec<_> = docs
            .iter()
            .map(|doc| {
                let score = self.score_doc(doc, &query_terms, avg_dl, n, &df);
                (doc, score)
            })
            .filter(|(_, score)| *score > 0.0)
            .collect();

        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(top_k);

        Ok(scored
            .into_iter()
            .map(|(doc, score)| RetrievalResult {
                content: doc.content.clone(),
                score,
                source: doc.source.clone(),
                metadata: doc
                    .metadata
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
            })
            .collect())
    }

    fn delete(&self, doc_id: &str) -> Result<bool, FridayAIError> {
        let mut docs = self.docs.write();
        let len_before = docs.len();
        docs.retain(|d| d.id != doc_id);
        Ok(docs.len() < len_before)
    }

    fn clear(&self) -> Result<(), FridayAIError> {
        self.docs.write().clear();
        Ok(())
    }

    fn count(&self) -> Result<usize, FridayAIError> {
        Ok(self.docs.read().len())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bm25_store_and_retrieve() {
        let mem = BM25Memory::default();
        mem.store("Rust is fast and safe", "doc1", None).unwrap();
        mem.store("Python is easy to learn", "doc2", None).unwrap();
        mem.store("Rust and Python are both great", "doc3", None).unwrap();

        let results = mem.retrieve("Rust programming", 2).unwrap();
        assert!(!results.is_empty());
        assert!(results[0].content.contains("Rust"));
    }

    #[test]
    fn test_bm25_empty() {
        let mem = BM25Memory::default();
        let results = mem.retrieve("anything", 5).unwrap();
        assert!(results.is_empty());
    }
}
