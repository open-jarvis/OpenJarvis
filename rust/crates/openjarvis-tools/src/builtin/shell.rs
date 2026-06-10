//! Shell execution tool.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;
use std::process::Command;
use std::time::{Duration, Instant};

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
        let timeout_secs = params["timeout"]
            .as_u64()
            .unwrap_or(30)
            .clamp(1, 300);

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

        match cmd.spawn() {
            Ok(output) => {
                let mut child = output;
                let start = Instant::now();
                let timeout = Duration::from_secs(timeout_secs);

                loop {
                    match child.try_wait() {
                        Ok(Some(_status)) => break,
                        Ok(None) => {
                            if start.elapsed() >= timeout {
                                let _ = child.kill();
                                let _ = child.wait();
                                let content = format!(
                                    "Exit code: -1\n--- stdout ---\n\n--- stderr ---\nCommand timed out after {} seconds.",
                                    timeout_secs
                                );
                                return Ok(ToolResult::failure("shell_exec", content));
                            }
                            std::thread::sleep(Duration::from_millis(25));
                        }
                        Err(e) => {
                            return Ok(ToolResult::failure(
                                "shell_exec",
                                format!("Failed to execute: {}", e),
                            ));
                        }
                    }
                }

                let output = match child.wait_with_output() {
                    Ok(o) => o,
                    Err(e) => {
                        return Ok(ToolResult::failure(
                            "shell_exec",
                            format!("Failed to collect output: {}", e),
                        ));
                    }
                };
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shell_exec_nonzero_exit_sets_failure() {
        let tool = ShellExecTool;
        let result = tool
            .execute(&serde_json::json!({"command": "exit 7"}))
            .unwrap();
        assert!(!result.success);
        assert!(result.content.contains("Exit code: 7"));
    }

    #[cfg(not(target_os = "windows"))]
    #[test]
    fn test_shell_exec_timeout() {
        let tool = ShellExecTool;
        let result = tool
            .execute(&serde_json::json!({"command": "sleep 5", "timeout": 1}))
            .unwrap();
        assert!(!result.success);
        assert!(result.content.contains("timed out after 1 seconds"));
    }
}
