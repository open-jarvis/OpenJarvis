//! MemoryBackend trait for all storage backends.

use friday_ai_core::{FridayAIError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, FridayAIError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, FridayAIError>;
    fn delete(&self, doc_id: &str) -> Result<bool, FridayAIError>;
    fn clear(&self) -> Result<(), FridayAIError>;
    fn count(&self) -> Result<usize, FridayAIError>;
}
