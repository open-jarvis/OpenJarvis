//! MCP (Model Context Protocol) — JSON-RPC server/client for tool exposure.

pub mod protocol;
pub mod server;

pub use protocol::{McpRequest, McpResponse};
pub use server::McpServer;
