use openjarvis_cross_device_travel::{
    protocol::*,
    runtime::{DeviceTransport, Orchestrator},
    travel::{decompose, DemoTransport, Scenario},
};
use serde_json::{json, Value};

struct MalformedCalendar {
    inner: DemoTransport,
    output: Value,
}

impl DeviceTransport for MalformedCalendar {
    fn discover(&self) -> Vec<Device> {
        self.inner.discover()
    }

    fn execute(&mut self, request: &TaskRequest) -> Result<TaskResponse, TaskError> {
        let mut response = self.inner.execute(request)?;
        if request.capability == Capability::CalendarAvailability {
            assert!(matches!(response.outcome, Outcome::Succeeded { .. }));
            response.outcome = Outcome::Succeeded {
                output: self.output.clone(),
            };
        }
        Ok(response)
    }
}

#[test]
fn malformed_successful_calendar_output_aborts_before_saving_a_plan() {
    let tasks = decompose("Make travel plans for me.").unwrap();
    for output in [
        json!({}),
        Value::Null,
        json!({"available_dates": []}),
        json!({"available_dates": ["2026-10-16", "2026-10-17"]}),
        json!({"available_dates": ["2026-10-16", null, "2026-10-18"]}),
        json!({"available_dates": ["2026-10-16", "", "2026-10-18"]}),
    ] {
        let transport = MalformedCalendar {
            inner: DemoTransport::new(Scenario::Happy),
            output: output.clone(),
        };
        let report = Orchestrator::new("laptop", transport)
            .run("calendar-validation", &tasks)
            .unwrap();
        assert!(
            matches!(&report.results["plan"], Outcome::Failed { error }
                if error.code == ErrorCode::ProtocolError),
            "calendar {output} unexpectedly produced {:?}",
            report.results["plan"]
        );
        assert!(report.aborted);
        assert!(!report.events.iter().any(|event| matches!(event,
            TraceEvent::Dispatch { request } if request.capability == Capability::SaveDraft)));
    }
}

#[test]
fn receiver_rejects_invalid_envelopes_before_acknowledging_an_action() {
    let valid = TaskRequest {
        version: PROTOCOL_VERSION,
        workflow_id: "receiver-validation".into(),
        task_id: "save_draft".into(),
        attempt: 1,
        from_device: "laptop".into(),
        to_device: "phone".into(),
        capability: Capability::SaveDraft,
        input: json!({}),
        context: [("plan".into(), json!({"synthetic": true}))].into(),
        timeout_ms: 5000,
    };
    type RejectionCase = (fn(&mut TaskRequest), ErrorCode);
    let cases: [RejectionCase; 5] = [
        (|r| r.version += 1, ErrorCode::ProtocolError),
        (|r| r.from_device = "phone".into(), ErrorCode::ProtocolError),
        (|r| r.to_device = "unknown".into(), ErrorCode::ProtocolError),
        (
            |r| r.capability = Capability::ItineraryPlanning,
            ErrorCode::NoCapability,
        ),
        (|r| r.timeout_ms = 0, ErrorCode::Timeout),
    ];
    for (invalidate, expected) in cases {
        let mut request = valid.clone();
        invalidate(&mut request);
        let response = DemoTransport::new(Scenario::Happy)
            .execute(&request)
            .unwrap();
        assert!(matches!(response.outcome, Outcome::Failed { error } if error.code == expected));
    }
    // The baseline includes the plan needed for a real synthetic save; rejection
    // above cannot pass merely because the fixture forgot that prerequisite.
    let response = DemoTransport::new(Scenario::Happy).execute(&valid).unwrap();
    assert!(matches!(response.outcome, Outcome::Succeeded { .. }));
}
