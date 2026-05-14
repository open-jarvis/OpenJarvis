# Serena Bookings / Appointments / Reminders Full Operator v1

Status: complete_v1_hub_adapter_pending

Legacy sources:
- legacy/serena-skills/20-bookings.js
- legacy/serena-skills/58-appointment-reminders.js

Related inspected skills:
- legacy/serena-skills/04-calendar.js
- legacy/serena-skills/25-compliance.js
- legacy/serena-skills/02-reporting.js
- legacy/serena-skills/03-gdrive.js
- legacy/serena-skills/08-google-docs.js
- legacy/serena-skills/01-crm.js
- legacy/serena-skills/09-finance.js
- legacy/serena-skills/10-payfast.js
- legacy/serena-skills/45-payflow.js

Legacy triggers:
- BOOK SLOT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE
- CANCEL APPOINTMENT:
- ADD PATIENT:
- GET PATIENT:
- UPDATE PATIENT:
- GENERATE INVOICE:
- PAYMENT LINK:
- PAYMENT STATUS:
- PAYFLOW:
- SUBSCRIPTION:

Purpose:
Serena Bookings is the practice appointment workflow operator for booking requests, appointments, reminders, follow-ups, no-show risk, Calendar handoff, Docs/Drive/Reporting handoff, audit, and safety blocks.

Architecture:
Google Calendar is the raw scheduling engine.
Bookings is the workflow layer above Calendar.

Bookings handles:
- appointment workflow evidence
- patient/client appointment context
- reminder/follow-up planning
- no-show risk tracking
- Calendar handoff
- Docs/Drive/Reporting handoff
- sensitive appointment guardrails
- audit and reporting

Foundation commands:
- status
- env-check
- plan
- source-list
- source-info

Booking request and record commands:
- availability-plan
- booking-request
- create-booking
- booking-info
- booking-list

Reschedule and cancellation commands:
- reschedule-booking
- cancel-booking
- cancellation-policy
- no-show-policy

Reminder and follow-up commands:
- reminder-plan
- reminder-schedule
- reminder-status
- no-show-risk
- follow-up-plan

Calendar handoff commands:
- calendar-handoff
- calendar-create-plan
- calendar-update-plan
- calendar-cancel-plan

Docs/Drive/Reporting handoff commands:
- docs-handoff
- drive-handoff
- reporting-handoff
- appointment-summary

Audit and safety commands:
- audit
- blocked-bulk-cancel
- blocked-unapproved-reminder-send
- blocked-patient-data-exposure
- blocked-silent-calendar-change

Current v1 behavior:
- External APIs are not called by Bookings.
- Calendar writes are not performed by Bookings.
- Reminder messages are not sent by Bookings.
- Google Docs are not created by Bookings.
- Drive uploads are not performed by Bookings.
- Reports are created locally as JSON and Markdown where needed.
- Local booking/request/reminder/follow-up/handoff/audit records are created as JSON evidence.
- Sensitive appointment handoffs require approval.
- Dangerous scheduling actions are blocked.

Source model:
- local-bookings: active local workflow evidence layer
- google-calendar: raw scheduling engine, already completed as separate operator
- compliance: privacy/POPIA/HPCSA/patient/client guardrails
- docs-drive: appointment summaries and evidence handoff
- reporting: appointment operational summaries
- accounting: booking-to-invoice/payment context later

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

Blocked:
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
Serena should act like a practice scheduling coordinator:
- understand booking intent
- create local booking evidence
- protect patient/client data
- prepare Calendar actions safely
- schedule reminder plans safely
- flag no-show risk
- create follow-up plans
- prepare Docs/Drive/Reporting handoff only when approved
- report exactly what changed
- block dangerous actions

Hub Adapter Layer:
Bookings is future Serena Hub compatible.

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

Completion notes:
Bookings / Appointments / Reminders Full Operator v1 is complete and safety-tested. Live Calendar writes remain delegated to the Calendar operator with explicit approval. Hub Adapter remains pending until Serena Hub dashboard/event bus exists.
