//! File read/write tools.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use openjarvis_security::file_policy::is_sensitive_file;
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

static READ_SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "file_read".into(),
    description: "Read the contents of a file".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "path": { "type": "string", "description": "File path to read" }
        },
        "required": ["path"]
    }),
    category: "filesystem".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: false,
    timeout_seconds: 10.0,
    required_capabilities: vec!["file:read".into()],
    metadata: HashMap::new(),
});

static WRITE_SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "file_write".into(),
    description: "Write content to a file".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "path": { "type": "string", "description": "File path to write" },
            "content": { "type": "string", "description": "Content to write" }
        },
        "required": ["path", "content"]
    }),
    category: "filesystem".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: true,
    timeout_seconds: 10.0,
    required_capabilities: vec!["file:write".into()],
    metadata: HashMap::new(),
});

pub struct FileReadTool;

impl BaseTool for FileReadTool {
    fn tool_id(&self) -> &str {
        "file_read"
    }
    fn spec(&self) -> &ToolSpec {
        &READ_SPEC
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let path_str = params["path"].as_str().unwrap_or("");
        let path = Path::new(path_str);

        if is_sensitive_file(path) {
            return Ok(ToolResult::failure(
                "file_read",
                format!("Access denied: '{path_str}' is a sensitive file"),
            ));
        }

        match std::fs::read_to_string(path) {
            Ok(content) => Ok(ToolResult::success("file_read", content)),
            Err(e) => Ok(ToolResult::failure(
                "file_read",
                format!("Error reading '{path_str}': {e}"),
            )),
        }
    }
}

pub struct FileWriteTool;

impl BaseTool for FileWriteTool {
    fn tool_id(&self) -> &str {
        "file_write"
    }
    fn spec(&self) -> &ToolSpec {
        &WRITE_SPEC
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let path_str = params["path"].as_str().unwrap_or("");
        let content = params["content"].as_str().unwrap_or("");
        let path = Path::new(path_str);

        if is_sensitive_file(path) {
            return Ok(ToolResult::failure(
                "file_write",
                format!("Access denied: '{path_str}' is a sensitive file"),
            ));
        }

        if let Some(parent) = path.parent() {
            if !parent.exists() {
                if let Err(e) = std::fs::create_dir_all(parent) {
                    return Ok(ToolResult::failure(
                        "file_write",
                        format!("Error creating directory: {e}"),
                    ));
                }
            }
        }

        match std::fs::write(path, content) {
            Ok(()) => Ok(ToolResult::success(
                "file_write",
                format!("Written {} bytes to {}", content.len(), path_str),
            )),
            Err(e) => Ok(ToolResult::failure(
                "file_write",
                format!("Error writing '{path_str}': {e}"),
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_file_read_sensitive_blocked() {
        let tool = FileReadTool;
        let result = tool
            .execute(&serde_json::json!({"path": ".env"}))
            .unwrap();
        assert!(!result.success);
        assert!(result.content.contains("sensitive"));
    }

    #[test]
    fn test_file_write_sensitive_blocked() {
        let tool = FileWriteTool;
        let result = tool
            .execute(&serde_json::json!({"path": "id_rsa", "content": "secret"}))
            .unwrap();
        assert!(!result.success);
    }
}
