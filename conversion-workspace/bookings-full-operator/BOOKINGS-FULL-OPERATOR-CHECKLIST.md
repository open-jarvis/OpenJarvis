# Serena Bookings / Appointments / Reminders Full Operator v1

Legacy sources:

- `legacy/serena-skills/20-bookings.js`
- `legacy/serena-skills/58-appointment-reminders.js`

Related skills to inspect:

- `legacy/serena-skills/04-calendar.js`
- `legacy/serena-skills/25-compliance.js`
- `legacy/serena-skills/02-reporting.js`
- `legacy/serena-skills/03-gdrive.js`
- `legacy/serena-skills/08-google-docs.js`
- `legacy/serena-skills/01-crm.js`
- `legacy/serena-skills/09-finance.js`
- `legacy/serena-skills/10-payfast.js`
- `legacy/serena-skills/45-payflow.js`

Goal:

Turn legacy bookings and appointment reminders into a complete practice/client/patient appointment workflow operator.

Primary role:

Serena should manage booking requests, appointments, reminders, follow-ups, no-show risks, cancellation/rescheduling workflows, calendar handoff, document handoff, reporting handoff, and safety blocks.

Architecture:

Google Calendar is the raw scheduling engine.
Bookings is the workflow layer above Calendar.

Target capability:

request -> classify -> availability plan -> booking record -> calendar handoff -> reminder plan -> follow-up plan -> reporting -> audit -> safety block when needed

Required v1 commands:

Layer 1 — Foundation:
- bookings status
- bookings env-check
- bookings plan
- bookings source-list
- bookings source-info

Layer 2 — Booking requests and records:
- bookings availability-plan
- bookings booking-request
- bookings create-booking
- bookings booking-info
- bookings booking-list

Layer 3 — Reschedule and cancel:
- bookings reschedule-booking
- bookings cancel-booking
- bookings cancellation-policy
- bookings no-show-policy

Layer 4 — Reminders:
- bookings reminder-plan
- bookings reminder-schedule
- bookings reminder-status
- bookings no-show-risk
- bookings follow-up-plan

Layer 5 — Calendar handoff:
- bookings calendar-handoff
- bookings calendar-create-plan
- bookings calendar-update-plan
- bookings calendar-cancel-plan

Layer 6 — Docs/Drive/Reporting handoff:
- bookings docs-handoff
- bookings drive-handoff
- bookings reporting-handoff
- bookings appointment-summary

Layer 7 — Audit and safety:
- bookings audit
- bookings blocked-bulk-cancel
- bookings blocked-unapproved-reminder-send
- bookings blocked-patient-data-exposure
- bookings blocked-silent-calendar-change

Safety model:

Allowed:
- create local booking plans
- create local booking records
- create local reminder plans
- create local follow-up plans
- prepare Calendar handoff
- prepare Docs/Drive/Reporting handoff
- audit appointment state
- flag no-show risk
- report exact changes

Guarded:
- patient/client data
- health appointment context
- external reminders
- calendar writes
- cancellations
- reschedules
- reminders containing sensitive details
- Docs/Drive exports
- Reporting handoff

Blocked in v1 unless explicit approval layer exists:
- bulk appointment cancellation
- silent cancellation
- silent reschedule
- unapproved SMS/email/WhatsApp reminder send
- exposing patient/client data
- hidden calendar changes
- destructive appointment cleanup
- deleting appointment evidence
- committing credentials

Operator standard:

Serena should not merely add calendar events.

Serena should act like a practice scheduling coordinator:
- understand booking intent
- prepare appointment details
- check scheduling context
- create local booking evidence
- prepare calendar actions
- schedule reminders safely
- flag no-shows and follow-ups
- protect patient/client data
- report exactly what changed

Hub Adapter Layer:

Bookings must be future Serena Hub compatible.

Future widgets:
- bookings_overview_widget
- calendar_schedule_widget
- appointment_detail_widget
- reminders_widget
- no_show_risk_widget
- followups_widget
- booking_requests_widget
- booking_approval_widget

Future events:
- booking_request_created
- booking_created
- booking_reschedule_planned
- booking_cancel_planned
- reminder_plan_created
- followup_plan_created
- booking_calendar_handoff_created
- booking_report_created
- booking_action_blocked

Future operator state:
- current_business_id
- current_patient_or_client_id
- current_booking_id
- current_calendar_event_id
- current_appointment_status
- current_reminder_status
- current_required_approval
- current_report_path

Status target:

`complete_v1_hub_adapter_pending`
