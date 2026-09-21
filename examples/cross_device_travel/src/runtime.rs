//! Sequential laptop scheduler. Discovery, transport and placement policy are
//! deliberately small replacement points, not a durable distributed scheduler.
use crate::protocol::*;
use std::collections::{BTreeMap, BTreeSet};

pub trait DeviceTransport {
    /// A snapshot of paired devices and advertised capabilities. A real adapter
    /// needs authenticated discovery and liveness expiry; online is only a hint.
    fn discover(&self) -> Vec<Device>;

    /// Return a terminal device response, or a transport error. Implementations
    /// must enforce request.timeout_ms (including connection and response wait).
    fn execute(&mut self, request: &TaskRequest) -> Result<TaskResponse, TaskError>;
}

/// Match capability AND placement before considering availability. For this
/// one-phone demo discovery represents a single user's already-paired devices.
/// Production routing must also constrain data to the specific owning device.
pub fn route<'a>(devices: &'a [Device], task: &TaskSpec) -> Result<&'a Device, TaskError> {
    let candidates: Vec<_> = devices
        .iter()
        .filter(|device| {
            device.kind == task.device_kind && device.capabilities.contains(&task.capability)
        })
        .collect();
    // Stable tie break makes traces reproducible regardless of discovery order.
    candidates
        .iter()
        .filter(|device| device.online)
        .min_by_key(|device| &device.id)
        .copied()
        .ok_or_else(|| {
            if candidates.is_empty() {
                TaskError::new(
                    ErrorCode::NoCapability,
                    format!("No {:?} advertises {:?}", task.device_kind, task.capability),
                    false,
                )
            } else {
                TaskError::new(
                    ErrorCode::DeviceUnavailable,
                    format!("Devices for {:?} are offline", task.capability),
                    true,
                )
            }
        })
}

pub struct Orchestrator<T> {
    laptop_id: String,
    transport: T,
}

impl<T: DeviceTransport> Orchestrator<T> {
    pub fn new(laptop_id: &str, transport: T) -> Self {
        Self {
            laptop_id: laptop_id.into(),
            transport,
        }
    }

    pub fn run(&mut self, workflow_id: &str, tasks: &[TaskSpec]) -> Result<RunReport, TaskError> {
        validate_plan(workflow_id, tasks)?;
        let devices = self.transport.discover();
        let mut ids = BTreeSet::new();
        if devices
            .iter()
            .any(|device| device.id.is_empty() || !ids.insert(&device.id))
        {
            return Err(TaskError::new(
                ErrorCode::ProtocolError,
                "Discovery returned empty or duplicate device IDs",
                false,
            ));
        }
        let mut report = RunReport {
            workflow_id: workflow_id.into(),
            devices,
            tasks: tasks.to_vec(),
            events: Vec::new(),
            results: BTreeMap::new(),
            aborted: false,
        };
        for task in tasks {
            if report.aborted {
                report.events.push(TraceEvent::Skipped {
                    task_id: task.id.clone(),
                    reason: "Required task failed".into(),
                });
                continue;
            }
            let outcome = match route(&report.devices, task) {
                Ok(device) => {
                    let target = device.id.clone();
                    let context = task
                        .depends_on
                        .iter()
                        .filter_map(|id| {
                            match report.results.get(id) {
                                Some(Outcome::Succeeded { output }) => {
                                    Some((id.clone(), output.clone()))
                                }
                                // Optional failures are omitted: the receiving handler
                                // must explicitly choose and label its fallback.
                                _ => None,
                            }
                        })
                        .collect();
                    self.dispatch(workflow_id, task, target, context, &mut report.events)
                }
                Err(error) => {
                    // A discovery failure is not a dispatched attempt. No spinning
                    // on an unavailable device; the next user run can rediscover.
                    report.events.push(TraceEvent::Failure {
                        task_id: task.id.clone(),
                        attempt: 0,
                        error: error.clone(),
                    });
                    Outcome::Failed { error }
                }
            };
            report.aborted = !task.optional && matches!(outcome, Outcome::Failed { .. });
            report.results.insert(task.id.clone(), outcome);
        }
        Ok(report)
    }

    fn dispatch(
        &mut self,
        workflow_id: &str,
        task: &TaskSpec,
        target: String,
        context: BTreeMap<String, serde_json::Value>,
        events: &mut Vec<TraceEvent>,
    ) -> Outcome {
        // Policy constants keep this handoff small. Replace with per-capability
        // budgets/backoff later. Action requests get exactly one send attempt.
        let attempts = if task.capability.is_read_only() { 2 } else { 1 };
        for attempt in 1..=attempts {
            let request = TaskRequest {
                version: PROTOCOL_VERSION,
                workflow_id: workflow_id.into(),
                task_id: task.id.clone(),
                attempt,
                from_device: self.laptop_id.clone(),
                to_device: target.clone(),
                capability: task.capability,
                input: task.input.clone(),
                context: context.clone(),
                timeout_ms: 5_000,
            };
            events.push(TraceEvent::Dispatch {
                request: request.clone(),
            });
            let result = self.transport.execute(&request).and_then(|response| {
                validate_response(&request, &response)?;
                events.push(TraceEvent::Response {
                    response: response.clone(),
                });
                match response.outcome {
                    Outcome::Succeeded { output } => Ok(output),
                    Outcome::Failed { error } => Err(error),
                }
            });
            match result {
                Ok(output) => return Outcome::Succeeded { output },
                Err(error) => {
                    events.push(TraceEvent::Failure {
                        task_id: task.id.clone(),
                        attempt,
                        error: error.clone(),
                    });
                    // Treat only transient transport/execution failures as retry
                    // candidates, even if a peer labels a protocol error retryable.
                    let transient = matches!(
                        error.code,
                        ErrorCode::Timeout
                            | ErrorCode::DeviceUnavailable
                            | ErrorCode::ExecutionFailed
                    );
                    if !error.retryable || !transient || attempt == attempts {
                        return Outcome::Failed { error };
                    }
                }
            }
        }
        unreachable!("Every request has at least one attempt")
    }
}

fn validate_response(request: &TaskRequest, response: &TaskResponse) -> Result<(), TaskError> {
    if response.version != PROTOCOL_VERSION
        || response.workflow_id != request.workflow_id
        || response.task_id != request.task_id
        || response.attempt != request.attempt
        || response.device_id != request.to_device
    {
        return Err(TaskError::new(
            ErrorCode::ProtocolError,
            "Response version or correlation fields do not match request",
            false,
        ));
    }
    Ok(())
}

fn validate_plan(workflow_id: &str, tasks: &[TaskSpec]) -> Result<(), TaskError> {
    if workflow_id.is_empty() || tasks.is_empty() {
        return Err(TaskError::new(
            ErrorCode::ProtocolError,
            "Workflow ID and plan must be nonempty",
            false,
        ));
    }
    let mut completed_ids = BTreeSet::new();
    for task in tasks {
        // Requiring prior dependencies rejects cycles, self references and
        // misspelled IDs before any action is dispatched.
        if task.id.is_empty()
            || completed_ids.contains(&task.id)
            || task.depends_on.iter().any(|id| !completed_ids.contains(id))
        {
            return Err(TaskError::new(
                ErrorCode::ProtocolError,
                "Task IDs must be unique and dependencies must precede their task",
                false,
            ));
        }
        completed_ids.insert(task.id.clone());
    }
    Ok(())
}
