//! Fixed travel example: replace decomposition, discovery, and handlers independently.
//! Every place, date, research result, and action below is a synthetic fixture.
use crate::laptop::{research_travel, LaptopPlanner, MockLaptopPlanner, PlannerRequest};
use crate::protocol::*;
use crate::runtime::{DeviceTransport, Orchestrator};
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scenario {
    Happy,
    PhoneOffline,
    PhotosDenied,
    ResearchRetry,
    SaveTimeout,
    LaptopOffline,
}

impl Scenario {
    pub const NAMES: &'static str =
        "happy | phone-offline | photos-denied | research-retry | save-timeout | laptop-offline";

    pub fn parse(name: &str) -> Result<Self, TaskError> {
        match name {
            "happy" => Ok(Self::Happy),
            "phone-offline" => Ok(Self::PhoneOffline),
            "photos-denied" => Ok(Self::PhotosDenied),
            "research-retry" => Ok(Self::ResearchRetry),
            "save-timeout" => Ok(Self::SaveTimeout),
            "laptop-offline" => Ok(Self::LaptopOffline),
            _ => Err(TaskError::new(
                ErrorCode::ExecutionFailed,
                format!("Unknown scenario {name:?}; expected {}", Self::NAMES),
                false,
            )),
        }
    }
}

/// A deterministic substitute for a model planner, deliberately limited to one prompt.
pub fn decompose(request: &str) -> Result<Vec<TaskSpec>, TaskError> {
    if request != "Make travel plans for me." {
        return Err(TaskError::new(
            ErrorCode::ExecutionFailed,
            "This fixed demo only supports: Make travel plans for me.",
            false,
        ));
    }
    use Capability::*;
    use DeviceKind::*;
    Ok([
        ("mobile_context", MobileContext, Phone, vec![], true),
        ("photo_interests", PhotoInterests, Phone, vec![], true),
        ("calendar", CalendarAvailability, Phone, vec![], true),
        (
            "research",
            TravelResearch,
            Laptop,
            vec!["mobile_context", "photo_interests"],
            false,
        ),
        (
            "plan",
            ItineraryPlanning,
            Laptop,
            vec!["mobile_context", "calendar", "research"],
            false,
        ),
        ("save_draft", SaveDraft, Phone, vec!["plan"], true),
    ]
    .into_iter()
    .map(
        |(id, capability, device_kind, dependencies, optional)| TaskSpec {
            id: id.into(),
            capability,
            device_kind,
            depends_on: dependencies.into_iter().map(String::from).collect(),
            optional,
            input: match capability {
                TravelResearch => json!({"destination": "Montreal", "synthetic": true}),
                ItineraryPlanning => json!({"model_profile": "large_local", "synthetic": true}),
                _ => json!({"request": request, "synthetic": true}),
            },
        },
    )
    .collect())
}

/// An in-memory stand-in for paired-device discovery plus an RPC transport.
/// Replace JSON round trips with authenticated, deadline-bound network I/O.
pub struct DemoTransport {
    scenario: Scenario,
    research_calls: usize,
    save_calls: usize,
    drafts: BTreeMap<String, Value>,
}

impl DemoTransport {
    pub fn new(scenario: Scenario) -> Self {
        Self {
            scenario,
            research_calls: 0,
            save_calls: 0,
            drafts: BTreeMap::new(),
        }
    }

    fn receive(&mut self, request: &TaskRequest) -> Result<Value, TaskError> {
        // Recheck at receipt: discovery is a snapshot, not authorization or liveness.
        if request.version != PROTOCOL_VERSION || request.from_device != "laptop" {
            return Err(TaskError::new(
                ErrorCode::ProtocolError,
                "Unsupported version or source address",
                false,
            ));
        }
        let device = self
            .discover()
            .into_iter()
            .find(|d| d.id == request.to_device)
            .ok_or_else(|| {
                TaskError::new(ErrorCode::ProtocolError, "Unknown target address", false)
            })?;
        if !device.online {
            return Err(TaskError::new(
                ErrorCode::DeviceUnavailable,
                "Device went offline",
                true,
            ));
        }
        if !device.capabilities.contains(&request.capability) {
            return Err(TaskError::new(
                ErrorCode::NoCapability,
                "Endpoint does not own capability",
                false,
            ));
        }
        if request.timeout_ms == 0 {
            return Err(TaskError::new(
                ErrorCode::Timeout,
                "Execution budget exhausted",
                true,
            ));
        }
        // No actual photos, location sensor access, calendar events, or network calls.
        match request.capability {
            Capability::MobileContext => Ok(json!({
                "origin": "Boston", "timezone": "America/New_York", "synthetic": true
            })),
            Capability::PhotoInterests => {
                if self.scenario == Scenario::PhotosDenied {
                    return Err(TaskError::new(
                        ErrorCode::PermissionDenied,
                        "Photo summary permission denied; do not request raw photos elsewhere",
                        false,
                    ));
                }
                Ok(json!({"interests": ["architecture", "parks"], "synthetic": true}))
            }
            Capability::CalendarAvailability => Ok(json!({
                "available_dates": ["2026-10-16", "2026-10-17", "2026-10-18"], "synthetic": true
            })),
            Capability::TravelResearch => {
                self.research_calls += 1;
                if self.scenario == Scenario::ResearchRetry && self.research_calls == 1 {
                    return Err(TaskError::new(
                        ErrorCode::Timeout,
                        "Synthetic research timeout",
                        true,
                    ));
                }
                let destination = input_string(request, "destination")?;
                research_travel(destination, &request.context)
            }
            Capability::ItineraryPlanning => {
                // The same task can call a real laptop model through this trait.
                // The mock records the selected profile; it performs no inference.
                MockLaptopPlanner.plan(PlannerRequest {
                    model_profile: input_string(request, "model_profile")?,
                    context: &request.context,
                })
            }
            Capability::SaveDraft => {
                self.save_calls += 1;
                let plan = request.context.get("plan").ok_or_else(|| {
                    TaskError::new(ErrorCode::ExecutionFailed, "Plan output required", false)
                })?;
                let draft_id = format!("{}:{}", request.workflow_id, request.task_id);
                self.drafts.insert(draft_id.clone(), plan.clone());
                if self.scenario == Scenario::SaveTimeout {
                    // The write happened, but its reply was lost. The orchestrator
                    // must report an uncertain outcome and never retry this action.
                    return Err(TaskError::new(ErrorCode::Timeout,
                        "Draft response lost; outcome uncertain; reconcile with phone before retrying", true));
                }
                Ok(
                    json!({"draft_id": draft_id, "storage": "synthetic_in_memory", "bookings_made": false}),
                )
            }
        }
    }
}

impl DeviceTransport for DemoTransport {
    fn discover(&self) -> Vec<Device> {
        vec![
            Device {
                id: "laptop".into(),
                kind: DeviceKind::Laptop,
                online: self.scenario != Scenario::LaptopOffline,
                capabilities: vec![Capability::TravelResearch, Capability::ItineraryPlanning],
            },
            Device {
                id: "phone".into(),
                kind: DeviceKind::Phone,
                online: self.scenario != Scenario::PhoneOffline,
                capabilities: vec![
                    Capability::MobileContext,
                    Capability::PhotoInterests,
                    Capability::CalendarAvailability,
                    Capability::SaveDraft,
                ],
            },
        ]
    }

    fn execute(&mut self, request: &TaskRequest) -> Result<TaskResponse, TaskError> {
        // Exercise the actual wire representation on both sides, including errors.
        fn round_trip<T: serde::Serialize + serde::de::DeserializeOwned>(
            value: &T,
        ) -> Result<T, TaskError> {
            serde_json::to_vec(value)
                .and_then(|bytes| serde_json::from_slice(&bytes))
                .map_err(|e| TaskError::new(ErrorCode::ProtocolError, e.to_string(), false))
        }
        let received: TaskRequest = round_trip(request)?;
        let outcome = match self.receive(&received) {
            Ok(output) => Outcome::Succeeded { output },
            Err(error) => Outcome::Failed { error },
        };
        round_trip(&TaskResponse {
            version: PROTOCOL_VERSION,
            workflow_id: received.workflow_id,
            task_id: received.task_id,
            attempt: received.attempt,
            device_id: received.to_device,
            outcome,
        })
    }
}

pub fn run_demo(scenario: Scenario) -> Result<Value, TaskError> {
    let tasks = decompose("Make travel plans for me.")?;
    let report =
        Orchestrator::new("laptop", DemoTransport::new(scenario)).run("travel-demo-001", &tasks)?;
    let final_output = assemble_output(&report);
    Ok(json!({"report": report, "final_output": final_output}))
}

fn input_string<'a>(request: &'a TaskRequest, name: &str) -> Result<&'a str, TaskError> {
    request
        .input
        .get(name)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            TaskError::new(
                ErrorCode::ProtocolError,
                format!("Missing or invalid input: {name}"),
                false,
            )
        })
}

/// Summarize only verified outcomes: losing any action acknowledgement leaves
/// its result unknown, even if the transport error was not called a timeout.
fn assemble_output(report: &RunReport) -> Value {
    let warnings: Vec<_> = report
        .tasks
        .iter()
        .filter(|task| task.optional)
        .filter_map(|task| match report.results.get(&task.id) {
            Some(Outcome::Failed { error }) => Some(json!({"task_id": task.id, "error": error})),
            _ => None,
        })
        .collect();
    let plan = match report.results.get("plan") {
        Some(Outcome::Succeeded { output }) if !report.aborted => output.clone(),
        _ => Value::Null,
    };
    let draft_status = match report.results.get("save_draft") {
        Some(Outcome::Succeeded { .. }) => "saved_in_demo_memory",
        Some(Outcome::Failed { .. }) if report.events.iter().any(|event| {
            matches!(event, TraceEvent::Dispatch { request } if request.task_id == "save_draft")
        }) => "uncertain_reconcile_with_phone",
        Some(Outcome::Failed { .. }) => "not_saved",
        None => "not_attempted",
    };
    json!({
        "status": if report.aborted { "aborted" } else { "completed" },
        "plan": plan, "warnings": warnings, "draft_status": draft_status,
        "notice": "Synthetic demo only: no live research, real device access, bookings, or persistent writes."
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attempts(value: &Value, task: &str) -> usize {
        value["report"]["events"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|event| event["event"] == "dispatch" && event["request"]["task_id"] == task)
            .count()
    }

    #[test]
    fn happy_flow_uses_phone_context_and_saves_plan() {
        let value = run_demo(Scenario::Happy).unwrap();
        let plan = &value["final_output"]["plan"];
        assert_eq!(plan["origin"], "Boston");
        assert_eq!(plan["research"]["departure_origin"], "Boston");
        assert_eq!(
            plan["itinerary"][1]["activity"],
            "Explore architecture in Montreal"
        );
        assert_eq!(plan["itinerary"][0]["date"], "2026-10-16");
        assert_eq!(
            value["final_output"]["draft_status"],
            "saved_in_demo_memory"
        );
        assert_eq!(value["final_output"]["warnings"], json!([]));
        assert_eq!(value["report"]["results"].as_object().unwrap().len(), 6);
    }

    #[test]
    fn missing_phone_context_is_explicit_and_changes_plan() {
        let value = run_demo(Scenario::PhoneOffline).unwrap();
        let plan = &value["final_output"]["plan"];
        assert_eq!(plan["origin"], "unconfirmed");
        assert_eq!(plan["scheduling"]["dates_status"], "unconfirmed");
        assert_eq!(
            plan["research"]["interest_source"],
            "assumed_generic_preferences"
        );
        assert_eq!(
            plan["itinerary"][1]["activity"],
            "Explore city walks in Montreal"
        );
        assert_eq!(
            value["final_output"]["warnings"].as_array().unwrap().len(),
            4
        );
        assert_eq!(attempts(&value, "mobile_context"), 0);
    }

    #[test]
    fn photo_denial_is_optional_without_losing_calendar() {
        let value = run_demo(Scenario::PhotosDenied).unwrap();
        assert_eq!(attempts(&value, "photo_interests"), 1);
        assert_eq!(
            value["final_output"]["plan"]["research"]["interest_source"],
            "assumed_generic_preferences"
        );
        assert_eq!(
            value["final_output"]["plan"]["itinerary"][0]["date"],
            "2026-10-16"
        );
        assert_eq!(
            value["final_output"]["warnings"].as_array().unwrap().len(),
            1
        );
    }

    #[test]
    fn retries_read_but_never_uncertain_write() {
        let read = run_demo(Scenario::ResearchRetry).unwrap();
        assert_eq!(attempts(&read, "research"), 2);
        assert_eq!(read["final_output"]["status"], "completed");
        let write = run_demo(Scenario::SaveTimeout).unwrap();
        assert_eq!(attempts(&write, "save_draft"), 1);
        assert_eq!(
            write["final_output"]["draft_status"],
            "uncertain_reconcile_with_phone"
        );
        assert!(!write["final_output"]["plan"].is_null());
    }

    #[test]
    fn lost_or_invalid_save_reply_leaves_the_action_outcome_unknown() {
        struct LostSaveReply {
            inner: DemoTransport,
            corrupt_reply: bool,
        }
        impl DeviceTransport for LostSaveReply {
            fn discover(&self) -> Vec<Device> {
                self.inner.discover()
            }
            fn execute(&mut self, request: &TaskRequest) -> Result<TaskResponse, TaskError> {
                let mut response = self.inner.execute(request)?;
                if request.capability == Capability::SaveDraft {
                    // Prove the write took place before the acknowledgement failed.
                    assert_eq!(self.inner.drafts.len(), 1);
                    if self.corrupt_reply {
                        response.task_id = "wrong-task".into();
                    } else {
                        return Err(TaskError::new(
                            ErrorCode::DeviceUnavailable,
                            "Connection lost after saving",
                            true,
                        ));
                    }
                }
                Ok(response)
            }
        }
        for corrupt_reply in [false, true] {
            let transport = LostSaveReply {
                inner: DemoTransport::new(Scenario::Happy),
                corrupt_reply,
            };
            let report = Orchestrator::new("laptop", transport)
                .run(
                    "test-save",
                    &decompose("Make travel plans for me.").unwrap(),
                )
                .unwrap();
            assert!(!report.aborted);
            assert_eq!(
                assemble_output(&report)["draft_status"],
                "uncertain_reconcile_with_phone"
            );
            assert_eq!(report.events.iter().filter(|event| {
                matches!(event, TraceEvent::Dispatch { request } if request.task_id == "save_draft")
            }).count(), 1);
        }
    }

    #[test]
    fn missing_laptop_aborts_without_final_plan() {
        let value = run_demo(Scenario::LaptopOffline).unwrap();
        assert_eq!(value["final_output"]["status"], "aborted");
        assert!(value["final_output"]["plan"].is_null());
        assert_eq!(attempts(&value, "plan"), 0);
        assert_eq!(attempts(&value, "save_draft"), 0);
    }

    #[test]
    fn changed_dependency_values_reach_research_and_scheduling() {
        let mut transport = DemoTransport::new(Scenario::Happy);
        let mut request = TaskRequest {
            version: PROTOCOL_VERSION,
            workflow_id: "test".into(),
            task_id: "research".into(),
            attempt: 1,
            from_device: "laptop".into(),
            to_device: "laptop".into(),
            capability: Capability::TravelResearch,
            input: json!({"destination": "Montreal"}),
            context: BTreeMap::from([
                ("mobile_context".into(), json!({"origin": "Chicago"})),
                (
                    "photo_interests".into(),
                    json!({"interests": ["museums", "gardens"]}),
                ),
            ]),
            timeout_ms: 1000,
        };
        let research = transport.receive(&request).unwrap();
        assert_eq!(research["departure_origin"], "Chicago");
        request.capability = Capability::ItineraryPlanning;
        request.input = json!({"model_profile": "large_local"});
        request.context.insert("research".into(), research);
        request.context.insert(
            "calendar".into(),
            json!({"available_dates": ["2027-01-01", "2027-01-02", "2027-01-03"]}),
        );
        let plan = transport.receive(&request).unwrap();
        assert_eq!(plan["origin"], "Chicago");
        assert_eq!(
            plan["itinerary"][1]["activity"],
            "Explore museums in Montreal"
        );
        assert_eq!(plan["itinerary"][0]["date"], "2027-01-01");
    }
}
