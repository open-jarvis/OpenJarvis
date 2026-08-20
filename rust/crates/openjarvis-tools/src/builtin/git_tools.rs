//! Git tools — status, diff, log.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;
use std::process::Command;

fn run_git(args: &[&str], cwd: Option<&str>) -> Result<String, String> {
    let mut cmd = Command::new("git");
    cmd.args(args);
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    match cmd.output() {
        Ok(output) => {
            if output.status.success() {
                Ok(String::from_utf8_lossy(&output.stdout).to_string())
            } else {
                Err(String::from_utf8_lossy(&output.stderr).to_string())
            }
        }
        Err(e) => Err(format!("Failed to run git: {e}")),
    }
}

macro_rules! git_tool {
    ($struct_name:ident, $tool_id:expr, $desc:expr, $git_cmd:expr) => {
        static $struct_name: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
            name: $tool_id.into(),
            description: $desc.into(),
            parameters: serde_json::json!({
                "type": "object",
                "properties": {
                    "cwd": { "type": "string", "description": "Repository directory (optional)" }
                }
            }),
            category: "git".into(),
            cost_estimate: 0.0,
            latency_estimate: 0.0,
            requires_confirmation: false,
            timeout_seconds: 10.0,
            required_capabilities: vec!["file:read".into()],
            metadata: HashMap::new(),
        });
    };
}

git_tool!(GIT_STATUS_SPEC, "git_status", "Show git status", "status");
git_tool!(GIT_DIFF_SPEC, "git_diff", "Show git diff", "diff");
git_tool!(GIT_LOG_SPEC, "git_log", "Show git log", "log");

pub struct GitStatusTool;
impl BaseTool for GitStatusTool {
    fn tool_id(&self) -> &str { "git_status" }
    fn spec(&self) -> &ToolSpec { &GIT_STATUS_SPEC }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let cwd = params["cwd"].as_str();
        match run_git(&["status", "--short"], cwd) {
            Ok(output) => Ok(ToolResult::success("git_status", output)),
            Err(e) => Ok(ToolResult::failure("git_status", e)),
        }
    }
}

pub struct GitDiffTool;
impl BaseTool for GitDiffTool {
    fn tool_id(&self) -> &str { "git_diff" }
    fn spec(&self) -> &ToolSpec { &GIT_DIFF_SPEC }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let cwd = params["cwd"].as_str();
        match run_git(&["diff"], cwd) {
            Ok(output) => Ok(ToolResult::success("git_diff", output)),
            Err(e) => Ok(ToolResult::failure("git_diff", e)),
        }
    }
}

pub struct GitLogTool;
impl BaseTool for GitLogTool {
    fn tool_id(&self) -> &str { "git_log" }
    fn spec(&self) -> &ToolSpec { &GIT_LOG_SPEC }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let cwd = params["cwd"].as_str();
        let n = params["n"].as_i64().unwrap_or(10);
        match run_git(&["log", "--oneline", &format!("-{n}")], cwd) {
            Ok(output) => Ok(ToolResult::success("git_log", output)),
            Err(e) => Ok(ToolResult::failure("git_log", e)),
        }
    }
}
