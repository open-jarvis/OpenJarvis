//! Demo protocol v1. These JSON types are intentionally independent of A2A.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

pub const PROTOCOL_VERSION: u16 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeviceKind {
    Laptop,
    Phone,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Capability {
    MobileContext,
    PhotoInterests,
    CalendarAvailability,
    TravelResearch,
    ItineraryPlanning,
    SaveDraft,
}

impl Capability {
    /// An uncertain write must be reconciled with its owner, never blindly retried.
    pub fn is_read_only(self) -> bool {
        // Exhaustive classification makes adding a capability require an explicit
        // retry decision, instead of silently treating new actions as safe reads.
        match self {
            Self::MobileContext
            | Self::PhotoInterests
            | Self::CalendarAvailability
            | Self::TravelResearch
            | Self::ItineraryPlanning => true,
            Self::SaveDraft => false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Device {
    pub id: String,
    pub kind: DeviceKind,
    pub online: bool,
    pub capabilities: Vec<Capability>,
}

/// A small, sequential plan in dependency order. Device kind is a placement
/// constraint, so a laptop advertising photos cannot impersonate the phone.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskSpec {
    pub id: String,
    pub capability: Capability,
    pub device_kind: DeviceKind,
    pub depends_on: Vec<String>,
    pub optional: bool,
    pub input: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TaskRequest {
    pub version: u16,
    pub workflow_id: String,
    pub task_id: String,
    pub attempt: u32,
    pub from_device: String,
    pub to_device: String,
    pub capability: Capability,
    pub input: Value,
    /// Only successful, explicitly declared dependency outputs cross the boundary.
    pub context: BTreeMap<String, Value>,
    /// The transport must bound execution/waiting by this budget. A timeout is
    /// not proof that execution stopped or that a side effect did not occur.
    pub timeout_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    NoCapability,
    DeviceUnavailable,
    Timeout,
    PermissionDenied,
    ExecutionFailed,
    ProtocolError,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TaskError {
    pub code: ErrorCode,
    pub message: String,
    pub retryable: bool,
}

impl TaskError {
    pub fn new(code: ErrorCode, message: impl Into<String>, retryable: bool) -> Self {
        Self {
            code,
            message: message.into(),
            retryable,
        }
    }
}

impl std::fmt::Display for TaskError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}: {}", self.code, self.message)
    }
}

impl std::error::Error for TaskError {}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Outcome {
    Succeeded { output: Value },
    Failed { error: TaskError },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TaskResponse {
    pub version: u16,
    pub workflow_id: String,
    pub task_id: String,
    pub attempt: u32,
    pub device_id: String,
    pub outcome: Outcome,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum TraceEvent {
    Dispatch {
        request: TaskRequest,
    },
    Response {
        response: TaskResponse,
    },
    Failure {
        task_id: String,
        attempt: u32,
        error: TaskError,
    },
    Skipped {
        task_id: String,
        reason: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunReport {
    pub workflow_id: String,
    pub devices: Vec<Device>,
    pub tasks: Vec<TaskSpec>,
    pub events: Vec<TraceEvent>,
    pub results: BTreeMap<String, Outcome>,
    pub aborted: bool,
}
