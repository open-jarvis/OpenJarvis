//! HTTP request tool.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use openjarvis_security::ssrf::check_ssrf;
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;

static SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "http_request".into(),
    description: "Make an HTTP request".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "URL to request" },
            "method": { "type": "string", "description": "HTTP method (GET, POST, etc.)" },
            "body": { "type": "string", "description": "Request body (optional)" },
            "headers": { "type": "object", "description": "HTTP headers (optional)" }
        },
        "required": ["url"]
    }),
    category: "network".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: false,
    timeout_seconds: 30.0,
    required_capabilities: vec!["network:fetch".into()],
    metadata: HashMap::new(),
});

pub struct HttpRequestTool;

impl BaseTool for HttpRequestTool {
    fn tool_id(&self) -> &str {
        "http_request"
    }
    fn spec(&self) -> &ToolSpec {
        &SPEC
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let url = params["url"].as_str().unwrap_or("");
        let method = params["method"].as_str().unwrap_or("GET").to_uppercase();

        if let Some(ssrf_error) = check_ssrf(url) {
            return Ok(ToolResult::failure("http_request", ssrf_error));
        }

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .map_err(|e| {
                OpenJarvisError::Io(std::io::Error::other(e.to_string()))
            })?;

        let mut request = match method.as_str() {
            "POST" => client.post(url),
            "PUT" => client.put(url),
            "DELETE" => client.delete(url),
            "PATCH" => client.patch(url),
            "HEAD" => client.head(url),
            _ => client.get(url),
        };

        if let Some(body) = params["body"].as_str() {
            request = request.body(body.to_string());
        }

        if let Some(headers) = params["headers"].as_object() {
            for (k, v) in headers {
                if let Some(val) = v.as_str() {
                    request = request.header(k.as_str(), val);
                }
            }
        }

        match request.send() {
            Ok(resp) => {
                let status = resp.status().as_u16();
                let body = resp.text().unwrap_or_default();
                let truncated = if body.len() > 10000 {
                    format!("{}...(truncated)", &body[..10000])
                } else {
                    body
                };
                let content = format!("Status: {status}\n{truncated}");
                if status < 400 {
                    Ok(ToolResult::success("http_request", content))
                } else {
                    Ok(ToolResult::failure("http_request", content))
                }
            }
            Err(e) => Ok(ToolResult::failure(
                "http_request",
                format!("Request failed: {e}"),
            )),
        }
    }
}
