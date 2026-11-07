//! MCP JSON-RPC 2.0 protocol types.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpRequest {
    pub jsonrpc: String,
    pub method: String,
    #[serde(default)]
    pub params: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<Value>,
}

impl McpRequest {
    pub fn new(method: &str, params: Value, id: Value) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            method: method.to_string(),
            params,
            id: Some(id),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpResponse {
    pub jsonrpc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<McpError>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpError {
    pub code: i64,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl McpResponse {
    pub fn success(id: Value, result: Value) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            result: Some(result),
            error: None,
            id: Some(id),
        }
    }

    pub fn error(id: Value, code: i64, message: &str) -> Self {
        Self {
            jsonrpc: "2.0".into(),
            result: None,
            error: Some(McpError {
                code,
                message: message.to_string(),
                data: None,
            }),
            id: Some(id),
        }
    }

    pub fn method_not_found(id: Value) -> Self {
        Self::error(id, -32601, "Method not found")
    }

    pub fn invalid_params(id: Value, msg: &str) -> Self {
        Self::error(id, -32602, msg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_request_serde() {
        let req = McpRequest::new(
            "tools/list",
            serde_json::json!({}),
            serde_json::json!(1),
        );
        let json = serde_json::to_string(&req).unwrap();
        let parsed: McpRequest = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.method, "tools/list");
    }

    #[test]
    fn test_response_success() {
        let resp = McpResponse::success(
            serde_json::json!(1),
            serde_json::json!({"tools": []}),
        );
        assert!(resp.result.is_some());
        assert!(resp.error.is_none());
    }

    #[test]
    fn test_response_error() {
        let resp = McpResponse::method_not_found(serde_json::json!(1));
        assert!(resp.error.is_some());
        assert_eq!(resp.error.unwrap().code, -32601);
    }
}
