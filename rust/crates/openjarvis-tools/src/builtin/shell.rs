//! Shell execution tool.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;
use std::process::Command;

static SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "shell_exec".into(),
    description: "Execute a shell command and return its output".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "command": { "type": "string", "description": "Shell command to execute" },
            "cwd": { "type": "string", "description": "Working directory (optional)" }
        },
        "required": ["command"]
    }),
    category: "system".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: true,
    timeout_seconds: 30.0,
    required_capabilities: vec!["code:execute".into()],
    metadata: HashMap::new(),
});

pub struct ShellExecTool;

impl BaseTool for ShellExecTool {
    fn tool_id(&self) -> &str {
        "shell_exec"
    }
    fn spec(&self) -> &ToolSpec {
        &SPEC
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let command = params["command"].as_str().unwrap_or("");
        let cwd = params["cwd"].as_str();

        let mut cmd = if cfg!(target_os = "windows") {
            let mut c = Command::new("cmd");
            c.args(["/C", command]);
            c
        } else {
            let mut c = Command::new("sh");
            c.args(["-c", command]);
            c
        };

        if let Some(dir) = cwd {
            cmd.current_dir(dir);
        }

        match cmd.output() {
            Ok(output) => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let stderr = String::from_utf8_lossy(&output.stderr);
                let exit_code = output.status.code().unwrap_or(-1);

                let content = format!(
                    "Exit code: {exit_code}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
                );

                if output.status.success() {
                    Ok(ToolResult::success("shell_exec", content))
                } else {
                    Ok(ToolResult::failure("shell_exec", content))
                }
            }
            Err(e) => Ok(ToolResult::failure(
                "shell_exec",
                format!("Failed to execute: {e}"),
            )),
        }
    }
}
