//! MCP server — handles JSON-RPC tool discovery and invocation.

use crate::protocol::{McpRequest, McpResponse};
use openjarvis_tools::executor::ToolExecutor;
use serde_json::Value;
use std::sync::Arc;

pub struct McpServer {
    executor: Arc<ToolExecutor>,
    server_name: String,
    server_version: String,
}

impl McpServer {
    pub fn new(executor: Arc<ToolExecutor>) -> Self {
        Self {
            executor,
            server_name: "openjarvis".into(),
            server_version: "1.0.0".into(),
        }
    }

    pub fn handle_request(&self, request: &McpRequest) -> McpResponse {
        let id = request.id.clone().unwrap_or(Value::Null);

        match request.method.as_str() {
            "initialize" => self.handle_initialize(id),
            "tools/list" => self.handle_tools_list(id),
            "tools/call" => self.handle_tools_call(id, &request.params),
            _ => McpResponse::method_not_found(id),
        }
    }

    fn handle_initialize(&self, id: Value) -> McpResponse {
        McpResponse::success(
            id,
            serde_json::json!({
                "protocolVersion": "2025-11-25",
                "capabilities": {
                    "tools": { "listChanged": false }
                },
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                }
            }),
        )
    }

    fn handle_tools_list(&self, id: Value) -> McpResponse {
        let tools = self.executor.tool_specs();
        McpResponse::success(id, serde_json::json!({ "tools": tools }))
    }

    fn handle_tools_call(&self, id: Value, params: &Value) -> McpResponse {
        let name = match params["name"].as_str() {
            Some(n) => n,
            None => return McpResponse::invalid_params(id, "Missing 'name' field"),
        };

        let arguments = params
            .get("arguments")
            .cloned()
            .unwrap_or(serde_json::json!({}));

        match self.executor.execute(name, &arguments, None, None) {
            Ok(result) => McpResponse::success(
                id,
                serde_json::json!({
                    "content": [{
                        "type": "text",
                        "text": result.content,
                    }],
                    "isError": !result.success,
                }),
            ),
            Err(e) => McpResponse::success(
                id,
                serde_json::json!({
                    "content": [{
                        "type": "text",
                        "text": e.to_string(),
                    }],
                    "isError": true,
                }),
            ),
        }
    }

    pub fn handle_json(&self, json_str: &str) -> String {
        match serde_json::from_str::<McpRequest>(json_str) {
            Ok(request) => {
                let response = self.handle_request(&request);
                serde_json::to_string(&response).unwrap_or_default()
            }
            Err(e) => {
                let resp = McpResponse::error(
                    Value::Null,
                    -32700,
                    &format!("Parse error: {}", e),
                );
                serde_json::to_string(&resp).unwrap_or_default()
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use openjarvis_tools::builtin::calculator::CalculatorTool;
    use openjarvis_tools::traits::BaseTool;

    fn make_server() -> McpServer {
        let mut exec = ToolExecutor::new(None, None);
        exec.register(openjarvis_tools::builtin::BuiltinTool::Calculator(CalculatorTool));
        McpServer::new(Arc::new(exec))
    }

    #[test]
    fn test_initialize() {
        let server = make_server();
        let req = McpRequest::new("initialize", serde_json::json!({}), serde_json::json!(1));
        let resp = server.handle_request(&req);
        assert!(resp.result.is_some());
    }

    #[test]
    fn test_tools_list() {
        let server = make_server();
        let req = McpRequest::new("tools/list", serde_json::json!({}), serde_json::json!(2));
        let resp = server.handle_request(&req);
        let tools = &resp.result.unwrap()["tools"];
        assert!(tools.is_array());
        assert!(!tools.as_array().unwrap().is_empty());
    }

    #[test]
    fn test_tools_call() {
        let server = make_server();
        let req = McpRequest::new(
            "tools/call",
            serde_json::json!({
                "name": "calculator",
                "arguments": {"expression": "2+2"}
            }),
            serde_json::json!(3),
        );
        let resp = server.handle_request(&req);
        let result = resp.result.unwrap();
        assert_eq!(result["isError"], false);
        assert!(result["content"][0]["text"].as_str().unwrap().contains("4"));
    }
}
