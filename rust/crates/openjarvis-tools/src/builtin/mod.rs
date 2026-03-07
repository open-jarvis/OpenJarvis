//! Built-in tool implementations.

pub mod calculator;
pub mod file_tools;
pub mod git_tools;
pub mod http_tools;
pub mod shell;
pub mod think;

pub use calculator::CalculatorTool;
pub use file_tools::{FileReadTool, FileWriteTool};
pub use git_tools::{GitDiffTool, GitLogTool, GitStatusTool};
pub use http_tools::HttpRequestTool;
pub use shell::ShellExecTool;
pub use think::ThinkTool;

use crate::traits::BaseTool;
use openjarvis_core::{ToolResult, ToolSpec};
use serde_json::Value;

pub enum BuiltinTool {
    Calculator(calculator::CalculatorTool),
    Think(think::ThinkTool),
    FileRead(file_tools::FileReadTool),
    FileWrite(file_tools::FileWriteTool),
    ShellExec(shell::ShellExecTool),
    HttpRequest(http_tools::HttpRequestTool),
    GitStatus(git_tools::GitStatusTool),
    GitDiff(git_tools::GitDiffTool),
    GitLog(git_tools::GitLogTool),
}

macro_rules! delegate_tool {
    ($self:expr, $method:ident $(, $arg:expr)*) => {
        match $self {
            BuiltinTool::Calculator(t) => t.$method($($arg),*),
            BuiltinTool::Think(t) => t.$method($($arg),*),
            BuiltinTool::FileRead(t) => t.$method($($arg),*),
            BuiltinTool::FileWrite(t) => t.$method($($arg),*),
            BuiltinTool::ShellExec(t) => t.$method($($arg),*),
            BuiltinTool::HttpRequest(t) => t.$method($($arg),*),
            BuiltinTool::GitStatus(t) => t.$method($($arg),*),
            BuiltinTool::GitDiff(t) => t.$method($($arg),*),
            BuiltinTool::GitLog(t) => t.$method($($arg),*),
        }
    };
}

impl BaseTool for BuiltinTool {
    fn tool_id(&self) -> &str {
        delegate_tool!(self, tool_id)
    }
    fn spec(&self) -> &ToolSpec {
        delegate_tool!(self, spec)
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, openjarvis_core::OpenJarvisError> {
        delegate_tool!(self, execute, params)
    }
}
