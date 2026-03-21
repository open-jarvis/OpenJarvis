//! MemoryBackendEnum — static dispatch over storage backends.

use super::bm25::BM25Memory;
use super::colbert::ColBERTMemory;
use super::faiss::FAISSMemory;
use super::hybrid::HybridMemory;
use super::knowledge_graph::KnowledgeGraphMemory;
use super::sqlite::SQLiteMemory;
use super::synapse::SynapseMemory;
use super::traits::MemoryBackend;
use openjarvis_core::{OpenJarvisError, RetrievalResult};
use serde_json::Value;

/// Closed enum of all supported memory/storage backends.
pub enum MemoryBackendEnum {
    Sqlite(SQLiteMemory),
    Bm25(BM25Memory),
    Faiss(FAISSMemory),
    ColBert(ColBERTMemory),
    Hybrid(HybridMemory),
    KnowledgeGraph(KnowledgeGraphMemory),
    Synapse(SynapseMemory),
}

macro_rules! delegate_memory {
    ($self:expr, $method:ident $(, $arg:expr)*) => {
        match $self {
            MemoryBackendEnum::Sqlite(m) => m.$method($($arg),*),
            MemoryBackendEnum::Bm25(m) => m.$method($($arg),*),
            MemoryBackendEnum::Faiss(m) => m.$method($($arg),*),
            MemoryBackendEnum::ColBert(m) => m.$method($($arg),*),
            MemoryBackendEnum::Hybrid(m) => m.$method($($arg),*),
            MemoryBackendEnum::KnowledgeGraph(m) => m.$method($($arg),*),
            MemoryBackendEnum::Synapse(m) => m.$method($($arg),*),
        }
    };
}

impl MemoryBackend for MemoryBackendEnum {
    fn backend_id(&self) -> &str {
        delegate_memory!(self, backend_id)
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, OpenJarvisError> {
        delegate_memory!(self, store, content, source, metadata)
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, OpenJarvisError> {
        delegate_memory!(self, retrieve, query, top_k)
    }

    fn delete(&self, doc_id: &str) -> Result<bool, OpenJarvisError> {
        delegate_memory!(self, delete, doc_id)
    }

    fn clear(&self) -> Result<(), OpenJarvisError> {
        delegate_memory!(self, clear)
    }

    fn count(&self) -> Result<usize, OpenJarvisError> {
        delegate_memory!(self, count)
    }
}

impl MemoryBackendEnum {
    /// Convenience: identify the backend variant key.
    pub fn variant_key(&self) -> &str {
        match self {
            MemoryBackendEnum::Sqlite(_) => "sqlite",
            MemoryBackendEnum::Bm25(_) => "bm25",
            MemoryBackendEnum::Faiss(_) => "faiss",
            MemoryBackendEnum::ColBert(_) => "colbert",
            MemoryBackendEnum::Hybrid(_) => "hybrid",
            MemoryBackendEnum::KnowledgeGraph(_) => "knowledge_graph",
            MemoryBackendEnum::Synapse(_) => "synapse",
        }
    }
}
