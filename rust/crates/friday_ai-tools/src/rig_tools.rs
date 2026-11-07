//! Rig-core tool adapters — typed Args structs implementing rig's `Tool` trait.
//!
//! Each builtin tool gets a rig-core adapter with compile-time JSON schema
//! generation via `schemars::JsonSchema`.

use rig::completion::request::ToolDefinition;
use rig::tool::Tool as RigTool;
use schemars::JsonSchema;
use serde::Deserialize;

// ---------------------------------------------------------------------------
// Calculator
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct CalculatorArgs {
    /// Mathematical expression to evaluate.
    pub expression: String,
}

#[derive(Debug, thiserror::Error)]
#[error("Calculator error: {0}")]
pub struct CalculatorError(String);

pub struct RigCalculatorTool;

impl RigTool for RigCalculatorTool {
    type Error = CalculatorError;
    type Args = CalculatorArgs;
    type Output = String;

    const NAME: &'static str = "calculator";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "calculator".into(),
            description: "Evaluate a mathematical expression".into(),
            parameters: serde_json::to_value(schemars::schema_for!(CalculatorArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::calculator::CalculatorTool;
        use crate::traits::BaseTool;
        let params = serde_json::json!({"expression": args.expression});
        let result = CalculatorTool
            .execute(&params)
            .map_err(|e| CalculatorError(e.to_string()))?;
        Ok(result.content)
    }
}

// ---------------------------------------------------------------------------
// Think
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct ThinkArgs {
    /// Internal reasoning thought to record.
    pub thought: String,
}

#[derive(Debug, thiserror::Error)]
#[error("Think error: {0}")]
pub struct ThinkError(String);

pub struct RigThinkTool;

impl RigTool for RigThinkTool {
    type Error = ThinkError;
    type Args = ThinkArgs;
    type Output = String;

    const NAME: &'static str = "think";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "think".into(),
            description: "Record an internal reasoning step".into(),
            parameters: serde_json::to_value(schemars::schema_for!(ThinkArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::think::ThinkTool;
        use crate::traits::BaseTool;
        let params = serde_json::json!({"thought": args.thought});
        let result = ThinkTool
            .execute(&params)
            .map_err(|e| ThinkError(e.to_string()))?;
        Ok(result.content)
    }
}

// ---------------------------------------------------------------------------
// FileRead
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct FileReadArgs {
    /// Path to the file to read.
    pub path: String,
}

#[derive(Debug, thiserror::Error)]
#[error("FileRead error: {0}")]
pub struct FileReadError(String);

pub struct RigFileReadTool;

impl RigTool for RigFileReadTool {
    type Error = FileReadError;
    type Args = FileReadArgs;
    type Output = String;

    const NAME: &'static str = "file_read";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "file_read".into(),
            description: "Read the contents of a file".into(),
            parameters: serde_json::to_value(schemars::schema_for!(FileReadArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::file_tools::FileReadTool;
        use crate::traits::BaseTool;
        let params = serde_json::json!({"path": args.path});
        let result = FileReadTool
            .execute(&params)
            .map_err(|e| FileReadError(e.to_string()))?;
        Ok(result.content)
    }
}

// ---------------------------------------------------------------------------
// FileWrite
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct FileWriteArgs {
    /// Path to the file to write.
    pub path: String,
    /// Content to write to the file.
    pub content: String,
}

#[derive(Debug, thiserror::Error)]
#[error("FileWrite error: {0}")]
pub struct FileWriteError(String);

pub struct RigFileWriteTool;

impl RigTool for RigFileWriteTool {
    type Error = FileWriteError;
    type Args = FileWriteArgs;
    type Output = String;

    const NAME: &'static str = "file_write";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "file_write".into(),
            description: "Write content to a file".into(),
            parameters: serde_json::to_value(schemars::schema_for!(FileWriteArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::file_tools::FileWriteTool;
        use crate::traits::BaseTool;
        let params = serde_json::json!({"path": args.path, "content": args.content});
        let result = FileWriteTool
            .execute(&params)
            .map_err(|e| FileWriteError(e.to_string()))?;
        Ok(result.content)
    }
}

// ---------------------------------------------------------------------------
// ShellExec
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct ShellExecArgs {
    /// Shell command to execute.
    pub command: String,
    /// Optional working directory.
    pub cwd: Option<String>,
}

#[derive(Debug, thiserror::Error)]
#[error("ShellExec error: {0}")]
pub struct ShellExecError(String);

pub struct RigShellExecTool;

impl RigTool for RigShellExecTool {
    type Error = ShellExecError;
    type Args = ShellExecArgs;
    type Output = String;

    const NAME: &'static str = "shell_exec";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "shell_exec".into(),
            description: "Execute a shell command".into(),
            parameters: serde_json::to_value(schemars::schema_for!(ShellExecArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::shell::ShellExecTool;
        use crate::traits::BaseTool;
        let mut params = serde_json::json!({"command": args.command});
        if let Some(cwd) = args.cwd {
            params["cwd"] = serde_json::Value::String(cwd);
        }
        let result = ShellExecTool
            .execute(&params)
            .map_err(|e| ShellExecError(e.to_string()))?;
        Ok(result.content)
    }
}

// ---------------------------------------------------------------------------
// HttpRequest
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct HttpRequestArgs {
    /// URL to send the request to.
    pub url: String,
    /// HTTP method (GET, POST, PUT, DELETE, PATCH). Defaults to GET.
    pub method: Option<String>,
    /// Optional request body (JSON string).
    pub body: Option<String>,
    /// Optional request headers as JSON object.
    pub headers: Option<serde_json::Value>,
}

#[derive(Debug, thiserror::Error)]
#[error("HttpRequest error: {0}")]
pub struct HttpRequestError(String);

pub struct RigHttpRequestTool;

impl RigTool for RigHttpRequestTool {
    type Error = HttpRequestError;
    type Args = HttpRequestArgs;
    type Output = String;

    const NAME: &'static str = "http_request";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "http_request".into(),
            description: "Send an HTTP request".into(),
            parameters: serde_json::to_value(schemars::schema_for!(HttpRequestArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::http_tools::HttpRequestTool;
        use crate::traits::BaseTool;
        let mut params = serde_json::json!({"url": args.url});
        if let Some(method) = args.method {
            params["method"] = serde_json::Value::String(method);
        }
        if let Some(body) = args.body {
            params["body"] = serde_json::Value::String(body);
        }
        if let Some(headers) = args.headers {
            params["headers"] = headers;
        }
        let result = HttpRequestTool
            .execute(&params)
            .map_err(|e| HttpRequestError(e.to_string()))?;
        Ok(result.content)
    }
}

// ---------------------------------------------------------------------------
// Git tools
// ---------------------------------------------------------------------------

#[derive(Deserialize, JsonSchema)]
pub struct GitStatusArgs {
    /// Optional working directory for git.
    pub cwd: Option<String>,
}

#[derive(Debug, thiserror::Error)]
#[error("GitStatus error: {0}")]
pub struct GitStatusError(String);

pub struct RigGitStatusTool;

impl RigTool for RigGitStatusTool {
    type Error = GitStatusError;
    type Args = GitStatusArgs;
    type Output = String;

    const NAME: &'static str = "git_status";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "git_status".into(),
            description: "Show git working tree status".into(),
            parameters: serde_json::to_value(schemars::schema_for!(GitStatusArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::git_tools::GitStatusTool;
        use crate::traits::BaseTool;
        let mut params = serde_json::json!({});
        if let Some(cwd) = args.cwd {
            params["cwd"] = serde_json::Value::String(cwd);
        }
        let result = GitStatusTool
            .execute(&params)
            .map_err(|e| GitStatusError(e.to_string()))?;
        Ok(result.content)
    }
}

#[derive(Deserialize, JsonSchema)]
pub struct GitDiffArgs {
    /// Optional working directory for git.
    pub cwd: Option<String>,
}

#[derive(Debug, thiserror::Error)]
#[error("GitDiff error: {0}")]
pub struct GitDiffError(String);

pub struct RigGitDiffTool;

impl RigTool for RigGitDiffTool {
    type Error = GitDiffError;
    type Args = GitDiffArgs;
    type Output = String;

    const NAME: &'static str = "git_diff";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "git_diff".into(),
            description: "Show git diff of changes".into(),
            parameters: serde_json::to_value(schemars::schema_for!(GitDiffArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::git_tools::GitDiffTool;
        use crate::traits::BaseTool;
        let mut params = serde_json::json!({});
        if let Some(cwd) = args.cwd {
            params["cwd"] = serde_json::Value::String(cwd);
        }
        let result = GitDiffTool
            .execute(&params)
            .map_err(|e| GitDiffError(e.to_string()))?;
        Ok(result.content)
    }
}

#[derive(Deserialize, JsonSchema)]
pub struct GitLogArgs {
    /// Optional working directory for git.
    pub cwd: Option<String>,
    /// Number of commits to show.
    pub count: Option<u32>,
}

#[derive(Debug, thiserror::Error)]
#[error("GitLog error: {0}")]
pub struct GitLogError(String);

pub struct RigGitLogTool;

impl RigTool for RigGitLogTool {
    type Error = GitLogError;
    type Args = GitLogArgs;
    type Output = String;

    const NAME: &'static str = "git_log";

    async fn definition(&self, _prompt: String) -> ToolDefinition {
        ToolDefinition {
            name: "git_log".into(),
            description: "Show git commit log".into(),
            parameters: serde_json::to_value(schemars::schema_for!(GitLogArgs)).unwrap_or_default(),
        }
    }

    async fn call(&self, args: Self::Args) -> Result<Self::Output, Self::Error> {
        use crate::builtin::git_tools::GitLogTool;
        use crate::traits::BaseTool;
        let mut params = serde_json::json!({});
        if let Some(cwd) = args.cwd {
            params["cwd"] = serde_json::Value::String(cwd);
        }
        if let Some(count) = args.count {
            params["count"] = serde_json::Value::Number(count.into());
        }
        let result = GitLogTool
            .execute(&params)
            .map_err(|e| GitLogError(e.to_string()))?;
        Ok(result.content)
    }
}

