//! Pub/sub event bus for cross-cutting concerns.
//!
//! Rust translation of `src/friday_ai/core/events.py`.

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

// ---------------------------------------------------------------------------
// Event types
// ---------------------------------------------------------------------------

/// All event types published through the event bus.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    // Inference
    InferenceStart,
    InferenceEnd,

    // Tools
    ToolCallStart,
    ToolCallEnd,
    ToolTimeout,

    // Memory
    MemoryStore,
    MemoryRetrieve,

    // Agents
    AgentTurnStart,
    AgentTurnEnd,

    // Telemetry
    TelemetryRecord,

    // Traces
    TraceStep,
    TraceComplete,

    // Security
    SecurityScan,
    SecurityAlert,
    SecurityBlock,
    CapabilityDenied,
    TaintViolation,

    // Loop guard
    LoopGuardTriggered,

    // Workflow
    WorkflowStart,
    WorkflowEnd,

    // Skills
    SkillExecuteStart,
    SkillExecuteEnd,

    // Sessions
    SessionStart,
    SessionEnd,

    // Scheduler
    SchedulerTaskStart,
    SchedulerTaskEnd,

    // Operators
    OperatorTickStart,
    OperatorTickEnd,

    // Channels
    ChannelMessageReceived,
    ChannelMessageSent,
}

impl std::fmt::Display for EventType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = serde_json::to_value(self)
            .ok()
            .and_then(|v| v.as_str().map(String::from))
            .unwrap_or_else(|| format!("{self:?}"));
        write!(f, "{s}")
    }
}

impl std::str::FromStr for EventType {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let quoted = format!("\"{s}\"");
        serde_json::from_str(&quoted).map_err(|_| format!("Unknown event type: {s}"))
    }
}

// ---------------------------------------------------------------------------
// Event
// ---------------------------------------------------------------------------

/// A single event published through the event bus.
#[derive(Debug, Clone)]
pub struct Event {
    pub event_type: EventType,
    pub timestamp: f64,
    pub data: HashMap<String, serde_json::Value>,
}

impl Event {
    /// Create a new event with the current timestamp.
    pub fn new(event_type: EventType, data: HashMap<String, serde_json::Value>) -> Self {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        Self {
            event_type,
            timestamp,
            data,
        }
    }
}

// ---------------------------------------------------------------------------
// Event bus
// ---------------------------------------------------------------------------

/// Callback type for event subscribers.
pub type Subscriber = Arc<dyn Fn(&Event) + Send + Sync>;

/// Thread-safe pub/sub event bus.
///
/// Subscribers register for specific event types and are called synchronously
/// when events of that type are published.
pub struct EventBus {
    subscribers: Mutex<HashMap<EventType, Vec<Subscriber>>>,
    record_history: bool,
    history: Mutex<Vec<Event>>,
}

impl EventBus {
    /// Create a new event bus.
    ///
    /// If `record_history` is `true`, all published events are retained
    /// and can be retrieved via [`Self::history()`].
    pub fn new(record_history: bool) -> Self {
        Self {
            subscribers: Mutex::new(HashMap::new()),
            record_history,
            history: Mutex::new(Vec::new()),
        }
    }

    /// Subscribe to events of a specific type.
    pub fn subscribe(&self, event_type: EventType, callback: Subscriber) {
        let mut subs = self.subscribers.lock();
        subs.entry(event_type).or_default().push(callback);
    }

    /// Publish an event, calling all registered subscribers.
    ///
    /// Returns the published event.
    pub fn publish(
        &self,
        event_type: EventType,
        data: HashMap<String, serde_json::Value>,
    ) -> Event {
        let event = Event::new(event_type, data);

        // Notify subscribers
        let subs = self.subscribers.lock();
        if let Some(callbacks) = subs.get(&event_type) {
            for callback in callbacks {
                callback(&event);
            }
        }

        // Record history if enabled
        if self.record_history {
            self.history.lock().push(event.clone());
        }

        event
    }

    /// Convenience method to publish an event with no data.
    pub fn emit(&self, event_type: EventType) -> Event {
        self.publish(event_type, HashMap::new())
    }

    /// Get the recorded event history.
    pub fn history(&self) -> Vec<Event> {
        self.history.lock().clone()
    }

    /// Clear the recorded event history.
    pub fn clear_history(&self) {
        self.history.lock().clear();
    }

    /// Get the number of subscribers for a given event type.
    pub fn subscriber_count(&self, event_type: EventType) -> usize {
        self.subscribers
            .lock()
            .get(&event_type)
            .map_or(0, |v| v.len())
    }

    /// Remove all subscribers.
    pub fn clear_subscribers(&self) {
        self.subscribers.lock().clear();
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn test_event_type_serde() {
        let et = EventType::InferenceStart;
        let json = serde_json::to_string(&et).unwrap();
        assert_eq!(json, "\"inference_start\"");
        let parsed: EventType = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, et);
    }

    #[test]
    fn test_event_type_from_str() {
        let et: EventType = "tool_call_start".parse().unwrap();
        assert_eq!(et, EventType::ToolCallStart);
    }

    #[test]
    fn test_publish_subscribe() {
        let bus = EventBus::new(false);
        let counter = Arc::new(AtomicUsize::new(0));
        let counter_clone = counter.clone();

        bus.subscribe(
            EventType::InferenceStart,
            Arc::new(move |_event| {
                counter_clone.fetch_add(1, Ordering::SeqCst);
            }),
        );

        bus.emit(EventType::InferenceStart);
        bus.emit(EventType::InferenceStart);
        bus.emit(EventType::InferenceEnd); // different type, should not fire

        assert_eq!(counter.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn test_event_data() {
        let bus = EventBus::new(false);
        let received_model = Arc::new(Mutex::new(String::new()));
        let rm = received_model.clone();

        bus.subscribe(
            EventType::InferenceStart,
            Arc::new(move |event| {
                if let Some(model) = event.data.get("model").and_then(|v| v.as_str()) {
                    *rm.lock() = model.to_string();
                }
            }),
        );

        let mut data = HashMap::new();
        data.insert("model".into(), serde_json::json!("qwen3:8b"));
        bus.publish(EventType::InferenceStart, data);

        assert_eq!(*received_model.lock(), "qwen3:8b");
    }

    #[test]
    fn test_history_recording() {
        let bus = EventBus::new(true);
        bus.emit(EventType::InferenceStart);
        bus.emit(EventType::InferenceEnd);

        let history = bus.history();
        assert_eq!(history.len(), 2);
        assert_eq!(history[0].event_type, EventType::InferenceStart);
        assert_eq!(history[1].event_type, EventType::InferenceEnd);
    }

    #[test]
    fn test_history_disabled() {
        let bus = EventBus::new(false);
        bus.emit(EventType::InferenceStart);
        assert!(bus.history().is_empty());
    }

    #[test]
    fn test_clear_history() {
        let bus = EventBus::new(true);
        bus.emit(EventType::InferenceStart);
        assert_eq!(bus.history().len(), 1);
        bus.clear_history();
        assert!(bus.history().is_empty());
    }

    #[test]
    fn test_subscriber_count() {
        let bus = EventBus::new(false);
        assert_eq!(bus.subscriber_count(EventType::ToolCallStart), 0);
        bus.subscribe(EventType::ToolCallStart, Arc::new(|_| {}));
        bus.subscribe(EventType::ToolCallStart, Arc::new(|_| {}));
        assert_eq!(bus.subscriber_count(EventType::ToolCallStart), 2);
    }

    #[test]
    fn test_event_timestamp() {
        let event = Event::new(EventType::InferenceStart, HashMap::new());
        assert!(event.timestamp > 0.0);
    }
}
