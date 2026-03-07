//! OpenJarvis A2A — Agent-to-Agent protocol types and in-memory task store.
//!
//! Implements the Google Agent-to-Agent JSON-RPC 2.0 protocol with typed
//! request/response envelopes, task lifecycle management, and an in-memory
//! task store.

use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// Task lifecycle
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskState {
    Pending,
    Active,
    Completed,
    Cancelled,
    Failed,
}

impl std::fmt::Display for TaskState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Pending => write!(f, "pending"),
            Self::Active => write!(f, "active"),
            Self::Completed => write!(f, "completed"),
            Self::Cancelled => write!(f, "cancelled"),
            Self::Failed => write!(f, "failed"),
        }
    }
}

// ---------------------------------------------------------------------------
// Agent card (capability advertisement)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentCard {
    pub name: String,
    pub description: String,
    pub version: String,
    pub url: String,
    pub skills: Vec<String>,
    pub supported_modes: Vec<String>,
}

impl AgentCard {
    pub fn new(name: &str, description: &str, version: &str, url: &str) -> Self {
        Self {
            name: name.into(),
            description: description.into(),
            version: version.into(),
            url: url.into(),
            skills: Vec::new(),
            supported_modes: Vec::new(),
        }
    }

    pub fn with_skills(mut self, skills: &[&str]) -> Self {
        self.skills = skills.iter().map(|s| (*s).into()).collect();
        self
    }

    pub fn with_modes(mut self, modes: &[&str]) -> Self {
        self.supported_modes = modes.iter().map(|s| (*s).into()).collect();
        self
    }
}

// ---------------------------------------------------------------------------
// Task
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct A2ATask {
    pub id: String,
    pub state: TaskState,
    pub input: String,
    pub output: Option<String>,
    pub metadata: Value,
    pub created_at: f64,
    pub updated_at: f64,
}

// ---------------------------------------------------------------------------
// JSON-RPC 2.0 envelope
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct A2ARequest {
    pub jsonrpc: String,
    pub method: String,
    pub params: Value,
    pub id: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct A2AError {
    pub code: i32,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct A2AResponse {
    pub jsonrpc: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<A2AError>,
    pub id: Value,
}

// ---------------------------------------------------------------------------
// Helper constructors
// ---------------------------------------------------------------------------

pub fn parse_request(json_str: &str) -> Result<A2ARequest, String> {
    serde_json::from_str(json_str).map_err(|e| format!("Invalid A2A request: {e}"))
}

pub fn make_response(id: Value, result: Value) -> A2AResponse {
    A2AResponse {
        jsonrpc: "2.0".into(),
        result: Some(result),
        error: None,
        id,
    }
}

pub fn make_error_response(id: Value, code: i32, message: &str) -> A2AResponse {
    A2AResponse {
        jsonrpc: "2.0".into(),
        result: None,
        error: Some(A2AError {
            code,
            message: message.into(),
            data: None,
        }),
        id,
    }
}

/// Serialize any `Serialize` type into a `serde_json::Value`.
pub fn to_value<T: Serialize>(item: &T) -> Result<Value, String> {
    serde_json::to_value(item).map_err(|e| format!("Serialization failed: {e}"))
}

// ---------------------------------------------------------------------------
// In-memory task store
// ---------------------------------------------------------------------------

fn now_timestamp() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

#[derive(Debug)]
pub struct A2ATaskStore {
    tasks: Vec<A2ATask>,
}

impl A2ATaskStore {
    pub fn new() -> Self {
        Self { tasks: Vec::new() }
    }

    pub fn create_task(&mut self, input: &str) -> A2ATask {
        let now = now_timestamp();
        let task = A2ATask {
            id: uuid::Uuid::new_v4().to_string(),
            state: TaskState::Pending,
            input: input.into(),
            output: None,
            metadata: Value::Object(serde_json::Map::new()),
            created_at: now,
            updated_at: now,
        };
        self.tasks.push(task.clone());
        task
    }

    pub fn get_task(&self, id: &str) -> Option<&A2ATask> {
        self.tasks.iter().find(|t| t.id == id)
    }

    pub fn update_state(&mut self, id: &str, state: TaskState) -> bool {
        if let Some(task) = self.tasks.iter_mut().find(|t| t.id == id) {
            task.state = state;
            task.updated_at = now_timestamp();
            true
        } else {
            false
        }
    }

    pub fn set_output(&mut self, id: &str, output: &str) -> bool {
        if let Some(task) = self.tasks.iter_mut().find(|t| t.id == id) {
            task.output = Some(output.into());
            task.updated_at = now_timestamp();
            true
        } else {
            false
        }
    }

    pub fn list_tasks(&self) -> &[A2ATask] {
        &self.tasks
    }

    /// Return tasks matching a generic predicate.
    pub fn find_tasks<F>(&self, predicate: F) -> Vec<&A2ATask>
    where
        F: Fn(&A2ATask) -> bool,
    {
        self.tasks.iter().filter(|t| predicate(t)).collect()
    }
}

impl Default for A2ATaskStore {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_task_lifecycle() {
        let mut store = A2ATaskStore::new();
        let task = store.create_task("Summarize this document");
        assert_eq!(task.state, TaskState::Pending);
        assert!(task.output.is_none());

        let id = task.id.clone();
        assert!(store.update_state(&id, TaskState::Active));
        assert_eq!(store.get_task(&id).unwrap().state, TaskState::Active);

        assert!(store.set_output(&id, "Summary: ..."));
        assert!(store.update_state(&id, TaskState::Completed));

        let completed = store.get_task(&id).unwrap();
        assert_eq!(completed.state, TaskState::Completed);
        assert_eq!(completed.output.as_deref(), Some("Summary: ..."));
    }

    #[test]
    fn test_request_parsing_and_response() {
        let json = r#"{
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": {"input": "hello"},
            "id": 1
        }"#;

        let req = parse_request(json).unwrap();
        assert_eq!(req.method, "tasks/send");
        assert_eq!(req.jsonrpc, "2.0");

        let resp = make_response(req.id.clone(), serde_json::json!({"status": "ok"}));
        assert!(resp.error.is_none());
        assert_eq!(resp.id, serde_json::json!(1));

        let err_resp = make_error_response(serde_json::json!(2), -32600, "Invalid request");
        assert!(err_resp.result.is_none());
        assert_eq!(err_resp.error.as_ref().unwrap().code, -32600);
    }

    #[test]
    fn test_invalid_request_parsing() {
        let result = parse_request("not valid json");
        assert!(result.is_err());
    }

    #[test]
    fn test_find_tasks_with_predicate() {
        let mut store = A2ATaskStore::new();
        store.create_task("task A");
        let b = store.create_task("task B");
        store.create_task("task C");

        store.update_state(&b.id, TaskState::Active);

        let active = store.find_tasks(|t| t.state == TaskState::Active);
        assert_eq!(active.len(), 1);
        assert_eq!(active[0].input, "task B");

        let pending = store.find_tasks(|t| t.state == TaskState::Pending);
        assert_eq!(pending.len(), 2);
    }

    #[test]
    fn test_update_nonexistent_task() {
        let mut store = A2ATaskStore::new();
        assert!(!store.update_state("no-such-id", TaskState::Failed));
        assert!(!store.set_output("no-such-id", "data"));
    }

    #[test]
    fn test_agent_card_builder() {
        let card = AgentCard::new("analyzer", "Analyzes data", "1.0", "http://localhost:9000")
            .with_skills(&["summarize", "extract"])
            .with_modes(&["sync", "async"]);

        assert_eq!(card.skills.len(), 2);
        assert_eq!(card.supported_modes, vec!["sync", "async"]);
    }

    #[test]
    fn test_task_state_serde_roundtrip() {
        for state in [
            TaskState::Pending,
            TaskState::Active,
            TaskState::Completed,
            TaskState::Cancelled,
            TaskState::Failed,
        ] {
            let json = serde_json::to_string(&state).unwrap();
            let parsed: TaskState = serde_json::from_str(&json).unwrap();
            assert_eq!(parsed, state);
        }
    }

    #[test]
    fn test_to_value_generic() {
        let card = AgentCard::new("test", "desc", "0.1", "http://example.com");
        let val = to_value(&card).unwrap();
        assert_eq!(val["name"], "test");
        assert_eq!(val["version"], "0.1");
    }
}
