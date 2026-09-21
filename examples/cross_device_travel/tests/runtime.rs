use openjarvis_cross_device_travel::{protocol::*, runtime::*};
use serde_json::{json, Value};
use std::{cell::RefCell, collections::VecDeque, rc::Rc};

enum Reply {
    Output(Value),
    TransportError(TaskError),
    DeviceError(TaskError),
    Corrupt(fn(&mut TaskResponse)),
}

struct MockTransport {
    devices: Vec<Device>,
    calls: Rc<RefCell<Vec<TaskRequest>>>,
    replies: VecDeque<Reply>,
}

impl DeviceTransport for MockTransport {
    fn discover(&self) -> Vec<Device> {
        self.devices.clone()
    }

    fn execute(&mut self, request: &TaskRequest) -> Result<TaskResponse, TaskError> {
        self.calls.borrow_mut().push(request.clone());
        let mut response = TaskResponse {
            version: request.version,
            workflow_id: request.workflow_id.clone(),
            task_id: request.task_id.clone(),
            attempt: request.attempt,
            device_id: request.to_device.clone(),
            outcome: Outcome::Succeeded {
                output: json!({"source": request.task_id}),
            },
        };
        match self.replies.pop_front() {
            Some(Reply::Output(output)) => response.outcome = Outcome::Succeeded { output },
            Some(Reply::TransportError(error)) => return Err(error),
            Some(Reply::DeviceError(error)) => response.outcome = Outcome::Failed { error },
            Some(Reply::Corrupt(corrupt)) => corrupt(&mut response),
            None => {}
        }
        Ok(response)
    }
}

fn device(id: &str, kind: DeviceKind, online: bool, capabilities: Vec<Capability>) -> Device {
    Device {
        id: id.into(),
        kind,
        online,
        capabilities,
    }
}

fn mock(replies: Vec<Reply>) -> MockTransport {
    MockTransport {
        devices: vec![device(
            "phone",
            DeviceKind::Phone,
            true,
            vec![Capability::MobileContext, Capability::SaveDraft],
        )],
        calls: Rc::new(RefCell::new(Vec::new())),
        replies: replies.into(),
    }
}

fn task(id: &str, depends_on: &[&str], optional: bool) -> TaskSpec {
    TaskSpec {
        id: id.into(),
        capability: Capability::MobileContext,
        device_kind: DeviceKind::Phone,
        depends_on: depends_on.iter().map(|id| (*id).into()).collect(),
        optional,
        input: json!({"requested": id}),
    }
}

fn error(code: ErrorCode, retryable: bool) -> TaskError {
    TaskError::new(code, "simulated failure", retryable)
}

fn failed(report: &RunReport, id: &str) -> ErrorCode {
    match &report.results[id] {
        Outcome::Failed { error } => error.code,
        other => panic!("expected failure for {id}, got {other:?}"),
    }
}

#[test]
fn routing_requires_placement_and_capability_and_distinguishes_offline() {
    let requested = task("context", &[], false);
    let wrong_kind = device(
        "laptop",
        DeviceKind::Laptop,
        true,
        vec![Capability::MobileContext],
    );
    let wrong_capability = device(
        "phone",
        DeviceKind::Phone,
        true,
        vec![Capability::SaveDraft],
    );
    let offline = device(
        "offline",
        DeviceKind::Phone,
        false,
        vec![Capability::MobileContext],
    );
    assert_eq!(
        route(&[wrong_kind.clone(), wrong_capability.clone()], &requested)
            .unwrap_err()
            .code,
        ErrorCode::NoCapability
    );
    assert_eq!(
        route(&[wrong_kind, wrong_capability, offline.clone()], &requested)
            .unwrap_err()
            .code,
        ErrorCode::DeviceUnavailable
    );
    let a = device(
        "a",
        DeviceKind::Phone,
        true,
        vec![Capability::MobileContext],
    );
    let z = device(
        "z",
        DeviceKind::Phone,
        true,
        vec![Capability::MobileContext],
    );
    for devices in [
        vec![z.clone(), offline.clone(), a.clone()],
        vec![a, offline, z],
    ] {
        assert_eq!(route(&devices, &requested).unwrap().id, "a");
    }
}

#[test]
fn invalid_plans_and_device_identities_fail_before_any_dispatch() {
    let cases = vec![
        ("", vec![task("a", &[], false)]),
        ("run", vec![]),
        ("run", vec![task("", &[], false)]),
        ("run", vec![task("a", &[], false), task("a", &[], false)]),
        ("run", vec![task("a", &["missing"], false)]),
        ("run", vec![task("a", &["a"], false)]),
        ("run", vec![task("a", &["b"], false), task("b", &[], false)]),
        (
            "run",
            vec![task("a", &["b"], false), task("b", &["a"], false)],
        ),
    ];
    for (workflow, plan) in cases {
        let transport = mock(vec![]);
        let calls = transport.calls.clone();
        let result = Orchestrator::new("laptop", transport).run(workflow, &plan);
        assert_eq!(result.unwrap_err().code, ErrorCode::ProtocolError);
        assert!(calls.borrow().is_empty());
    }
    for duplicate in [false, true] {
        let mut transport = mock(vec![]);
        if duplicate {
            transport.devices.push(transport.devices[0].clone());
        } else {
            transport.devices[0].id.clear();
        }
        let calls = transport.calls.clone();
        let result = Orchestrator::new("laptop", transport).run("run", &[task("a", &[], false)]);
        assert_eq!(result.unwrap_err().code, ErrorCode::ProtocolError);
        assert!(calls.borrow().is_empty());
    }
}

#[test]
fn context_contains_only_declared_successes_and_omits_optional_failure() {
    let transport = mock(vec![
        Reply::Output(json!({"private": "unrelated"})),
        Reply::Output(json!({"city": "Paris"})),
        Reply::DeviceError(error(ErrorCode::PermissionDenied, false)),
    ]);
    let calls = transport.calls.clone();
    let plan = [
        task("unrelated", &[], false),
        task("location", &[], false),
        task("photos", &[], true),
        task("plan", &["location", "photos"], false),
    ];
    let report = Orchestrator::new("laptop", transport)
        .run("run", &plan)
        .unwrap();
    assert!(!report.aborted);
    assert_eq!(failed(&report, "photos"), ErrorCode::PermissionDenied);
    let calls = calls.borrow();
    assert!(calls[..3].iter().all(|request| request.context.is_empty()));
    assert_eq!(
        calls[3].context,
        [("location".into(), json!({"city": "Paris"}))].into()
    );
    assert_eq!(calls[3].input, plan[3].input);
}

#[test]
fn correlation_rejects_every_mismatched_field_including_a_late_retry_response() {
    let corruptions: [fn(&mut TaskResponse); 5] = [
        |r| r.version += 1,
        |r| r.workflow_id.push('x'),
        |r| r.task_id.push('x'),
        |r| r.attempt += 1,
        |r| r.device_id.push('x'),
    ];
    for corrupt in corruptions {
        let transport = mock(vec![Reply::Corrupt(corrupt)]);
        let calls = transport.calls.clone();
        let report = Orchestrator::new("laptop", transport)
            .run("run", &[task("a", &[], false)])
            .unwrap();
        assert_eq!(failed(&report, "a"), ErrorCode::ProtocolError);
        assert_eq!(calls.borrow().len(), 1);
        assert!(!report
            .events
            .iter()
            .any(|event| matches!(event, TraceEvent::Response { .. })));
    }
    let transport = mock(vec![
        Reply::TransportError(error(ErrorCode::Timeout, true)),
        Reply::Corrupt(|r| r.attempt = 1),
    ]);
    let calls = transport.calls.clone();
    let report = Orchestrator::new("laptop", transport)
        .run("run", &[task("a", &[], false)])
        .unwrap();
    assert_eq!(failed(&report, "a"), ErrorCode::ProtocolError);
    assert_eq!(calls.borrow().len(), 2);
}

#[test]
fn read_retry_preserves_identity_payload_context_and_target() {
    for first in [
        Reply::TransportError(error(ErrorCode::Timeout, true)),
        Reply::DeviceError(error(ErrorCode::ExecutionFailed, true)),
    ] {
        let transport = mock(vec![Reply::Output(json!({"city": "Paris"})), first]);
        let calls = transport.calls.clone();
        let plan = [
            task("context", &[], false),
            task("read", &["context"], false),
        ];
        let report = Orchestrator::new("laptop", transport)
            .run("run", &plan)
            .unwrap();
        assert!(!report.aborted);
        assert!(matches!(report.results["read"], Outcome::Succeeded { .. }));
        let calls = calls.borrow();
        assert_eq!(calls.len(), 3);
        assert_eq!((calls[1].attempt, calls[2].attempt), (1, 2));
        let mut retried = calls[2].clone();
        retried.attempt = 1;
        assert_eq!(calls[1], retried);
        assert!(retried.timeout_ms > 0);
        assert_eq!(retried.context["context"], json!({"city": "Paris"}));
    }
}

#[test]
fn retries_are_bounded_and_require_both_transient_code_and_retryable_flag() {
    for (code, retryable, attempts) in [
        (ErrorCode::Timeout, true, 2),
        (ErrorCode::DeviceUnavailable, true, 2),
        (ErrorCode::ExecutionFailed, true, 2),
        (ErrorCode::Timeout, false, 1),
        (ErrorCode::PermissionDenied, true, 1),
        (ErrorCode::ProtocolError, true, 1),
    ] {
        let transport = mock(vec![
            Reply::DeviceError(error(code, retryable)),
            Reply::DeviceError(error(code, retryable)),
        ]);
        let calls = transport.calls.clone();
        let report = Orchestrator::new("laptop", transport)
            .run("run", &[task("a", &[], false)])
            .unwrap();
        assert_eq!(failed(&report, "a"), code);
        assert!(report.aborted);
        assert_eq!(
            calls.borrow().len(),
            attempts,
            "{code:?}, retryable={retryable}"
        );
    }
}

#[test]
fn uncertain_writes_are_never_replayed() {
    for reply in [
        Reply::TransportError(error(ErrorCode::Timeout, true)),
        Reply::DeviceError(error(ErrorCode::ExecutionFailed, true)),
    ] {
        let transport = mock(vec![reply]);
        let calls = transport.calls.clone();
        let mut action = task("save", &[], true);
        action.capability = Capability::SaveDraft;
        let report = Orchestrator::new("laptop", transport)
            .run("run", &[action])
            .unwrap();
        assert!(matches!(report.results["save"], Outcome::Failed { .. }));
        assert_eq!(calls.borrow().len(), 1);
    }
}

#[test]
fn required_failure_skips_dependent_actions_instead_of_using_partial_context() {
    for offline in [false, true] {
        let mut transport = mock(vec![Reply::DeviceError(error(
            ErrorCode::PermissionDenied,
            false,
        ))]);
        transport.devices[0].online = !offline;
        let calls = transport.calls.clone();
        let mut action = task("save", &["required"], true);
        action.capability = Capability::SaveDraft;
        let report = Orchestrator::new("laptop", transport)
            .run("run", &[task("required", &[], false), action])
            .unwrap();
        assert!(report.aborted);
        assert!(!report.results.contains_key("save"));
        assert!(report.events.iter().any(|event| matches!(event,
            TraceEvent::Skipped { task_id, .. } if task_id == "save")));
        assert_eq!(calls.borrow().len(), usize::from(!offline));
        if offline {
            assert_eq!(failed(&report, "required"), ErrorCode::DeviceUnavailable);
            assert!(matches!(
                report.events.first(),
                Some(TraceEvent::Failure { attempt: 0, .. })
            ));
        }
    }
}
