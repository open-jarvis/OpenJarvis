//! Synapse memory backend — connects to a running Synapse runtime over HTTP.

use crate::storage::traits::MemoryBackend;
use openjarvis_core::error::StorageError;
use openjarvis_core::{OpenJarvisError, RetrievalResult};
use serde_json::Value;
use std::collections::HashMap;

pub struct SynapseMemory {
    client: synapse_client::Client,
    rt: tokio::runtime::Runtime,
    store_event: String,
    retrieve_query: String,
    delete_event: String,
}

impl SynapseMemory {
    pub fn new(
        url: &str,
        store_event: &str,
        retrieve_query: &str,
        delete_event: &str,
    ) -> Result<Self, OpenJarvisError> {
        let rt = tokio::runtime::Runtime::new().map_err(|e| {
            OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                "Failed to create tokio runtime: {e}"
            )))
        })?;
        Ok(Self {
            client: synapse_client::Client::new(url),
            rt,
            store_event: store_event.to_string(),
            retrieve_query: retrieve_query.to_string(),
            delete_event: delete_event.to_string(),
        })
    }

    /// Emit an arbitrary event to the Synapse runtime.
    pub fn emit(&self, event: &str, payload: &Value) -> Result<Value, OpenJarvisError> {
        self.rt
            .block_on(self.client.emit(event, payload.clone()))
            .map_err(|e| {
                OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                    "Synapse emit({event}) failed: {e}"
                )))
            })
    }

    /// Run any named query against the Synapse runtime.
    pub fn query_raw(&self, name: &str, params: &Value) -> Result<Value, OpenJarvisError> {
        self.rt
            .block_on(self.client.query(name, params.clone()))
            .map_err(|e| {
                OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                    "Synapse query({name}) failed: {e}"
                )))
            })
    }

    pub fn health(&self) -> Result<Value, OpenJarvisError> {
        let resp = self.rt.block_on(self.client.health()).map_err(|e| {
            OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                "Synapse health check failed: {e}"
            )))
        })?;
        serde_json::to_value(resp).map_err(|e| {
            OpenJarvisError::Storage(StorageError::BackendNotAvailable(e.to_string()))
        })
    }

    pub fn status(&self) -> Result<Value, OpenJarvisError> {
        let resp = self.rt.block_on(self.client.status()).map_err(|e| {
            OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                "Synapse status failed: {e}"
            )))
        })?;
        serde_json::to_value(resp).map_err(|e| {
            OpenJarvisError::Storage(StorageError::BackendNotAvailable(e.to_string()))
        })
    }

    pub fn inspect_raw(&self) -> Result<Value, OpenJarvisError> {
        self.rt
            .block_on(self.client.inspect())
            .map_err(|e| {
                OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                    "Synapse inspect failed: {e}"
                )))
            })
    }

    pub fn reload(&self) -> Result<Value, OpenJarvisError> {
        self.rt
            .block_on(self.client.reload())
            .map_err(|e| {
                OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                    "Synapse reload failed: {e}"
                )))
            })
    }

    pub fn ping(&self) -> bool {
        self.rt.block_on(self.client.ping())
    }

    fn parse_results(value: &Value) -> Vec<RetrievalResult> {
        let items = match value {
            Value::Array(arr) => arr.clone(),
            Value::Object(obj) => {
                if let Some(Value::Array(arr)) = obj.get("results").or_else(|| obj.get("data")) {
                    arr.clone()
                } else {
                    vec![value.clone()]
                }
            }
            _ => return vec![],
        };

        items
            .iter()
            .filter_map(|item| {
                let content = item
                    .get("content")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if content.is_empty() {
                    return None;
                }
                let score = item
                    .get("_score")
                    .or_else(|| item.get("score"))
                    .and_then(|v| v.as_f64())
                    .unwrap_or(1.0);
                let source = item
                    .get("source")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let metadata: HashMap<String, Value> = item
                    .as_object()
                    .map(|obj| {
                        obj.iter()
                            .filter(|(k, _)| {
                                !matches!(
                                    k.as_str(),
                                    "content" | "_score" | "score" | "source"
                                )
                            })
                            .map(|(k, v)| (k.clone(), v.clone()))
                            .collect()
                    })
                    .unwrap_or_default();
                Some(RetrievalResult {
                    content,
                    score,
                    source,
                    metadata,
                })
            })
            .collect()
    }
}

impl MemoryBackend for SynapseMemory {
    fn backend_id(&self) -> &str {
        "synapse"
    }

    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, OpenJarvisError> {
        let mut payload = serde_json::json!({
            "content": content,
            "source": source,
        });
        if let Some(meta) = metadata {
            if let Value::Object(map) = meta {
                if let Value::Object(ref mut p) = payload {
                    for (k, v) in map {
                        p.insert(k.clone(), v.clone());
                    }
                }
            } else {
                payload["metadata"] = meta.clone();
            }
        }

        let resp = self.emit(&self.store_event.clone(), &payload)?;

        let doc_id = resp
            .get("_id")
            .or_else(|| resp.get("id"))
            .or_else(|| resp.get("doc_id"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        if doc_id.is_empty() {
            Ok(resp.to_string())
        } else {
            Ok(doc_id)
        }
    }

    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, OpenJarvisError> {
        let params = serde_json::json!({
            "query": query,
            "input": query,
            "top_k": top_k,
            "limit_n": top_k,
        });
        let resp = self.query_raw(&self.retrieve_query.clone(), &params)?;
        let mut results = Self::parse_results(&resp);
        results.truncate(top_k);
        Ok(results)
    }

    fn delete(&self, doc_id: &str) -> Result<bool, OpenJarvisError> {
        let payload = serde_json::json!({ "doc_id": doc_id, "_id": doc_id });
        let resp = self.emit(&self.delete_event.clone(), &payload)?;
        let deleted = resp
            .get("deleted")
            .and_then(|v| v.as_bool())
            .unwrap_or(true);
        Ok(deleted)
    }

    fn clear(&self) -> Result<(), OpenJarvisError> {
        self.rt
            .block_on(self.client.clear())
            .map_err(|e| {
                OpenJarvisError::Storage(StorageError::BackendNotAvailable(format!(
                    "Synapse clear failed: {e}"
                )))
            })?;
        Ok(())
    }

    fn count(&self) -> Result<usize, OpenJarvisError> {
        let resp = self.inspect_raw()?;
        if let Some(obj) = resp.as_object() {
            let total: usize = obj
                .values()
                .filter_map(|v| {
                    v.get("count")
                        .and_then(|c| c.as_u64())
                        .or_else(|| v.as_array().map(|a| a.len() as u64))
                })
                .sum::<u64>() as usize;
            Ok(total)
        } else {
            Ok(0)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_results_array() {
        let data = serde_json::json!([
            {"content": "hello", "_score": 0.9, "source": "test"},
            {"content": "world", "_score": 0.5},
        ]);
        let results = SynapseMemory::parse_results(&data);
        assert_eq!(results.len(), 2);
        assert_eq!(results[0].content, "hello");
        assert!((results[0].score - 0.9).abs() < f64::EPSILON);
        assert_eq!(results[1].content, "world");
    }

    #[test]
    fn test_parse_results_object_with_data() {
        let data = serde_json::json!({
            "data": [{"content": "fact1", "score": 0.8}]
        });
        let results = SynapseMemory::parse_results(&data);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].content, "fact1");
    }

    #[test]
    fn test_parse_results_empty() {
        let data = serde_json::json!(null);
        let results = SynapseMemory::parse_results(&data);
        assert!(results.is_empty());
    }
}
