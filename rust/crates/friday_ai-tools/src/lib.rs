//! Tools primitive — BaseTool trait, ToolExecutor, built-in tools, storage backends.

pub mod builtin;
pub mod executor;
pub mod rig_tools;
pub mod storage;
pub mod traits;

pub use executor::ToolExecutor;
pub use traits::BaseTool;
