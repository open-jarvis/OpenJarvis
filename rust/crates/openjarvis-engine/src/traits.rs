//! InferenceEngine trait and shared utilities.

use openjarvis_core::{GenerateResult, Message, Role};
use serde_json::Value;
use std::pin::Pin;
use tokio_stream::Stream;

pub type StreamItem = Result<String, openjarvis_core::OpenJarvisError>;
pub type TokenStream = Pin<Box<dyn Stream<Item = StreamItem> + Send>>;

/// ABC for all inference engine backends.
///
/// Implementations must be thread-safe (`Send + Sync`).
#[async_trait::async_trait]
pub trait InferenceEngine: Send + Sync {
    fn engine_id(&self) -> &str;

    fn generate(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<GenerateResult, openjarvis_core::OpenJarvisError>;

    async fn stream(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<TokenStream, openjarvis_core::OpenJarvisError>;

    fn list_models(&self) -> Result<Vec<String>, openjarvis_core::OpenJarvisError>;

    fn health(&self) -> bool;

    fn close(&self) {}

    fn prepare(&self, _model: &str) {}
}

/// Convert `Message` structs to OpenAI-compatible JSON dicts.
pub fn messages_to_dicts(messages: &[Message]) -> Vec<Value> {
    messages
        .iter()
        .map(|m| {
            let mut d = serde_json::json!({
                "role": m.role.to_string(),
                "content": m.content,
            });
            if let Some(ref name) = m.name {
                d["name"] = Value::String(name.clone());
            }
            if let Some(ref tool_calls) = m.tool_calls {
                let tc_json: Vec<Value> = tool_calls
                    .iter()
                    .map(|tc| {
                        serde_json::json!({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            }
                        })
                    })
                    .collect();
                d["tool_calls"] = Value::Array(tc_json);
            }
            if let Some(ref tool_call_id) = m.tool_call_id {
                d["tool_call_id"] = Value::String(tool_call_id.clone());
            }
            if m.role == Role::Tool {
                if let Some(ref name) = m.name {
                    d["name"] = Value::String(name.clone());
                }
            }
            d
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use openjarvis_core::{Message, ToolCall};

    #[test]
    fn test_messages_to_dicts_basic() {
        let msgs = vec![
            Message::system("You are helpful"),
            Message::user("Hello"),
        ];
        let dicts = messages_to_dicts(&msgs);
        assert_eq!(dicts.len(), 2);
        assert_eq!(dicts[0]["role"], "system");
        assert_eq!(dicts[1]["content"], "Hello");
    }

    #[test]
    fn test_messages_to_dicts_with_tool_calls() {
        let mut msg = Message::assistant("Let me calculate");
        msg.tool_calls = Some(vec![ToolCall {
            id: "call_1".into(),
            name: "calculator".into(),
            arguments: r#"{"expression": "2+2"}"#.into(),
        }]);
        let dicts = messages_to_dicts(&[msg]);
        assert!(dicts[0]["tool_calls"].is_array());
        assert_eq!(dicts[0]["tool_calls"][0]["function"]["name"], "calculator");
    }
}
