//! Laptop research and heavy-model replacement points. Everything here is a fixture;
//! no model, search provider, transport timetable, or booking service is invoked.
use crate::protocol::{ErrorCode, TaskError};
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn invalid(message: impl Into<String>) -> TaskError {
    TaskError::new(ErrorCode::ProtocolError, message, false)
}

fn text<'a>(value: &'a Value, field: &str) -> Result<&'a str, TaskError> {
    value
        .get(field)
        .and_then(Value::as_str)
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| invalid(format!("{field} must be a nonempty string")))
}

fn strings(value: &Value, field: &str) -> Result<Vec<String>, TaskError> {
    let values: Vec<String> = serde_json::from_value(value[field].clone())
        .map_err(|_| invalid(format!("{field} must be an array of strings")))?;
    if values.is_empty() || values.iter().any(|s| s.trim().is_empty()) {
        return Err(invalid(format!("{field} must contain nonempty strings")));
    }
    Ok(values)
}

fn origin(context: &BTreeMap<String, Value>) -> Result<&str, TaskError> {
    match context.get("mobile_context") {
        Some(value) => text(value, "origin"),
        None => Ok("unconfirmed"),
    }
}

/// Replace the fixture records with search-provider results behind this interface.
/// The records illustrate candidates, not verified routes or available inventory.
pub fn research_travel(
    destination: &str,
    context: &BTreeMap<String, Value>,
) -> Result<Value, TaskError> {
    if destination.trim().is_empty() {
        return Err(invalid("destination must be a nonempty string"));
    }
    let origin = origin(context)?;
    let (interests, source) = match context.get("photo_interests") {
        Some(value) => (strings(value, "interests")?, "synthetic_phone_summary"),
        None => (
            vec!["city walks".into(), "neighborhood food".into()],
            "assumed_generic_preferences",
        ),
    };
    let transport_options: Vec<_> = ["air", "rail"]
        .into_iter()
        .map(|mode| {
            json!({
                "id": format!("fixture-{mode}"), "mode": mode,
                "origin": origin, "destination": destination,
                "verification": "unverified", "synthetic": true
            })
        })
        .collect();
    Ok(json!({
        "destination": destination, "departure_origin": origin,
        "interests": interests, "interest_source": source,
        "transport_research": format!("Compare transport from {origin} to {destination}; schedules and fares unverified"),
        "lodging_research": "Compare central accommodation; availability and prices unverified",
        "transport_options": transport_options,
        "lodging_options": [{"id": "fixture-central-stay", "area": "Central area",
            "destination": destination, "verification": "unverified", "synthetic": true}],
        "evidence": "Hypothetical fixture; no live research or cited sources"
    }))
}

pub struct PlannerRequest<'a> {
    pub model_profile: &'a str,
    pub context: &'a BTreeMap<String, Value>,
}

/// A production adapter can invoke a larger local model here, retaining schema
/// validation and caller-provided context. Device routing stays in the orchestrator.
pub trait LaptopPlanner {
    fn plan(&self, request: PlannerRequest<'_>) -> Result<Value, TaskError>;
}

pub struct MockLaptopPlanner;

fn options<'a>(
    research: &'a Value,
    field: &str,
    required: &[&str],
) -> Result<&'a [Value], TaskError> {
    let records = research[field]
        .as_array()
        .filter(|v| !v.is_empty())
        .ok_or_else(|| invalid(format!("{field} must contain candidate records")))?;
    for record in records {
        for key in required {
            text(record, key)?;
        }
        if text(record, "destination")? != text(research, "destination")?
            || text(record, "verification")? != "unverified"
            || record["synthetic"] != true
        {
            return Err(invalid(format!(
                "{field} must contain matching unverified fixtures"
            )));
        }
    }
    Ok(records)
}

impl LaptopPlanner for MockLaptopPlanner {
    fn plan(&self, request: PlannerRequest<'_>) -> Result<Value, TaskError> {
        if request.model_profile != "large_local" {
            return Err(invalid(
                "The mock laptop planner supports model_profile=large_local only",
            ));
        }
        let context = request.context;
        let research = context
            .get("research")
            .ok_or_else(|| invalid("Research output required"))?;
        let destination = text(research, "destination")?;
        let origin = origin(context)?;
        if text(research, "departure_origin")? != origin {
            return Err(invalid(
                "Research departure_origin must match mobile context or its fallback",
            ));
        }
        let interests = strings(research, "interests")?;
        for field in [
            "interest_source",
            "transport_research",
            "lodging_research",
            "evidence",
        ] {
            text(research, field)?;
        }
        let transport = options(research, "transport_options", &["id", "mode", "origin"])?;
        if transport.iter().any(|record| record["origin"] != origin) {
            return Err(invalid("Transport candidates must match departure_origin"));
        }
        let lodging = options(research, "lodging_options", &["id", "area"])?;
        // Missing optional context permits a labeled fallback. Supplied malformed
        // context is a protocol failure, never evidence of calendar availability.
        let dates: [String; 3] = match context.get("calendar") {
            None => std::array::from_fn(|_| "unconfirmed".into()),
            Some(calendar) => {
                serde_json::from_value(calendar["available_dates"].clone()).map_err(|_| {
                    invalid("Calendar available_dates must contain exactly three strings")
                })?
            }
        };
        if dates.iter().any(|date| date.trim().is_empty()) {
            return Err(invalid("Calendar dates must be nonempty strings"));
        }
        let itinerary: Vec<_> = dates.iter().enumerate().map(|(day, date)| json!({
            "day": day + 1, "date": date,
            "activity": match day {
                0 => "Arrival and orientation".to_string(),
                1 => format!("Explore {} in {destination}", interests[0]),
                _ => format!("Explore {}; return travel", interests.get(1).map(String::as_str).unwrap_or("local neighborhoods"))
            }
        })).collect();
        Ok(json!({
            "title": format!("Hypothetical three-day {destination} trip"),
            "origin": origin, "research": research, "itinerary": itinerary,
            "selected_options": {"transport": transport[0], "lodging": lodging[0]},
            "execution": {"model_profile": request.model_profile, "backend": "mock"},
            "scheduling": {
                "dates": dates,
                "dates_status": if context.contains_key("calendar") {
                    "supported_by_synthetic_phone_availability"
                } else { "unconfirmed" },
                "requires_user_confirmation": true,
                "next_steps": ["Confirm origin, dates, and interests", "Verify transport, lodging, and opening hours"]
            },
            "assumptions": [format!("{destination} is an illustrative destination"), "No budget provided"],
            "synthetic": true
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn planner_consumes_research_candidates_and_destination() {
        let mut context = BTreeMap::from([
            ("mobile_context".into(), json!({"origin": "Boston"})),
            (
                "photo_interests".into(),
                json!({"interests": ["museums", "gardens"]}),
            ),
        ]);
        let mut research = research_travel("Quebec City", &context).unwrap();
        research["lodging_options"][0]["area"] = json!("Museum quarter");
        context.insert("research".into(), research);
        let plan = MockLaptopPlanner
            .plan(PlannerRequest {
                model_profile: "large_local",
                context: &context,
            })
            .unwrap();
        assert_eq!(plan["title"], "Hypothetical three-day Quebec City trip");
        assert_eq!(
            plan["itinerary"][1]["activity"],
            "Explore museums in Quebec City"
        );
        assert_eq!(
            plan["selected_options"]["lodging"]["area"],
            "Museum quarter"
        );
        assert_eq!(plan["selected_options"]["transport"]["origin"], "Boston");
        assert_eq!(
            plan["selected_options"]["transport"]["destination"],
            "Quebec City"
        );
        assert_eq!(
            plan["execution"],
            json!({"model_profile": "large_local", "backend": "mock"})
        );
    }

    #[test]
    fn unsupported_model_profile_is_a_nonretryable_protocol_error() {
        let error = MockLaptopPlanner
            .plan(PlannerRequest {
                model_profile: "cloud",
                context: &BTreeMap::new(),
            })
            .unwrap_err();
        assert_eq!(error.code, ErrorCode::ProtocolError);
        assert!(!error.retryable);
    }
}
