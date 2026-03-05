//! Rig-core model adapter — bridges `InferenceEngine` into rig's `CompletionModel`.

use crate::traits::InferenceEngine;
use openjarvis_core::{GenerateResult, Message};
use rig::completion::message::Message as RigMessage;
use rig::completion::request::{
    CompletionError, CompletionRequest, CompletionResponse, ToolDefinition,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;

/// Raw response wrapper for our engine results.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OjRawResponse {
    pub content: String,
    pub model: String,
    pub finish_reason: String,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
}

impl rig::completion::request::GetTokenUsage for OjRawResponse {
    fn token_usage(&self) -> Option<rig::completion::Usage> {
        Some(rig::completion::Usage {
            input_tokens: self.prompt_tokens as u64,
            output_tokens: self.completion_tokens as u64,
            total_tokens: (self.prompt_tokens + self.completion_tokens) as u64,
            cached_input_tokens: 0,
        })
    }
}

/// Bridges any `InferenceEngine` implementation into rig-core's `CompletionModel`.
///
/// Uses `tokio::task::spawn_blocking` to bridge the sync `generate()` method
/// into rig's async completion interface.
pub struct RigModelAdapter<E: InferenceEngine> {
    engine: Arc<E>,
    model_id: String,
}

impl<E: InferenceEngine> RigModelAdapter<E> {
    pub fn new(engine: Arc<E>, model_id: String) -> Self {
        Self { engine, model_id }
    }
}

impl<E: InferenceEngine> Clone for RigModelAdapter<E> {
    fn clone(&self) -> Self {
        Self {
            engine: Arc::clone(&self.engine),
            model_id: self.model_id.clone(),
        }
    }
}

/// Convert rig-core messages to openjarvis Messages.
fn rig_request_to_oj_messages(request: &CompletionRequest) -> Vec<Message> {
    let mut messages = Vec::new();

    // Add preamble as system message
    if let Some(ref preamble) = request.preamble {
        messages.push(Message::system(preamble));
    }

    // Add chat history
    for msg in request.chat_history.iter() {
        match msg {
            RigMessage::User { content } => {
                let text = content
                    .iter()
                    .filter_map(|c| {
                        if let rig::completion::message::UserContent::Text(t) = c {
                            Some(t.text.as_str())
                        } else {
                            None
                        }
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                messages.push(Message::user(&text));
            }
            RigMessage::Assistant { content, .. } => {
                let text = content
                    .iter()
                    .filter_map(|c| {
                        if let rig::completion::message::AssistantContent::Text(t) = c {
                            Some(t.text.as_str())
                        } else {
                            None
                        }
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                messages.push(Message::assistant(&text));
            }
        }
    }

    // Add document context
    if !request.documents.is_empty() {
        let doc_context: String = request
            .documents
            .iter()
            .map(|d| format!("[{}]\n{}", d.id, d.text))
            .collect::<Vec<_>>()
            .join("\n\n");
        messages.push(Message::system(&format!(
            "Relevant context:\n{}",
            doc_context
        )));
    }

    messages
}

/// Build the `extra` JSON Value for tool definitions.
fn tools_to_extra(tools: &[ToolDefinition]) -> Option<Value> {
    if tools.is_empty() {
        return None;
    }
    let tool_specs: Vec<Value> = tools
        .iter()
        .map(|t| {
            serde_json::json!({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
            })
        })
        .collect();
    Some(serde_json::json!({ "tools": tool_specs }))
}

fn make_usage(result: &GenerateResult) -> rig::completion::Usage {
    rig::completion::Usage {
        input_tokens: result.usage.prompt_tokens as u64,
        output_tokens: result.usage.completion_tokens as u64,
        total_tokens: result.usage.total_tokens as u64,
        cached_input_tokens: 0,
    }
}

fn make_raw(result: &GenerateResult) -> OjRawResponse {
    OjRawResponse {
        content: result.content.clone(),
        model: result.model.clone(),
        finish_reason: result.finish_reason.clone(),
        prompt_tokens: result.usage.prompt_tokens,
        completion_tokens: result.usage.completion_tokens,
    }
}

impl<E: InferenceEngine + 'static> rig::completion::request::CompletionModel
    for RigModelAdapter<E>
{
    type Response = OjRawResponse;
    type StreamingResponse = OjRawResponse;
    type Client = ();

    fn make(_client: &Self::Client, _model: impl Into<String>) -> Self {
        unimplemented!(
            "Use RigModelAdapter::new() directly instead of CompletionModel::make()"
        );
    }

    fn completion(
        &self,
        request: CompletionRequest,
    ) -> impl std::future::Future<
        Output = Result<CompletionResponse<Self::Response>, CompletionError>,
    > + Send {
        let engine = Arc::clone(&self.engine);
        let model_id = self.model_id.clone();

        async move {
            let messages = rig_request_to_oj_messages(&request);
            let temperature = request.temperature.unwrap_or(0.7);
            let max_tokens = request.max_tokens.unwrap_or(2048) as i64;
            let extra = tools_to_extra(&request.tools);

            let result: Result<GenerateResult, _> =
                tokio::task::spawn_blocking(move || {
                    engine.generate(
                        &messages,
                        &model_id,
                        temperature,
                        max_tokens,
                        extra.as_ref(),
                    )
                })
                .await
                .map_err(|e| CompletionError::ProviderError(e.to_string()))?;

            let result =
                result.map_err(|e| CompletionError::ProviderError(e.to_string()))?;

            let raw = make_raw(&result);
            let usage = make_usage(&result);

            let choice = rig::one_or_many::OneOrMany::one(
                rig::completion::message::AssistantContent::text(&result.content),
            );

            Ok(CompletionResponse {
                choice,
                usage,
                raw_response: raw,
                message_id: None,
            })
        }
    }

    fn stream(
        &self,
        _request: CompletionRequest,
    ) -> impl std::future::Future<
        Output = Result<
            rig::streaming::StreamingCompletionResponse<Self::StreamingResponse>,
            CompletionError,
        >,
    > + Send {
        async move {
            // Our engines use blocking HTTP clients. Streaming is not supported
            // through the rig adapter — callers should use `completion()` instead.
            Err(CompletionError::ProviderError(
                "Streaming not supported through RigModelAdapter; use completion() instead".into(),
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use openjarvis_core::Role;

    #[test]
    fn test_rig_request_to_oj_messages_basic() {
        let request = CompletionRequest {
            model: None,
            preamble: Some("You are helpful".into()),
            chat_history: rig::one_or_many::OneOrMany::one(RigMessage::user("Hello")),
            documents: vec![],
            tools: vec![],
            temperature: None,
            max_tokens: None,
            tool_choice: None,
            additional_params: None,
            output_schema: None,
        };

        let msgs = rig_request_to_oj_messages(&request);
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[0].role, Role::System);
        assert_eq!(msgs[1].role, Role::User);
        assert_eq!(msgs[1].content, "Hello");
    }

    #[test]
    fn test_tools_to_extra() {
        let tools = vec![ToolDefinition {
            name: "calculator".into(),
            description: "Compute math".into(),
            parameters: serde_json::json!({"type": "object"}),
        }];
        let extra = tools_to_extra(&tools);
        assert!(extra.is_some());
        let v = extra.unwrap();
        assert!(v["tools"].is_array());
    }

    #[test]
    fn test_tools_to_extra_empty() {
        assert!(tools_to_extra(&[]).is_none());
    }
}
