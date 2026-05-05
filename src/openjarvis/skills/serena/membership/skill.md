# Serena Membership / Subscriptions / Patient Programmes Full Operator v1

Status: complete_v1_hub_adapter_pending

Legacy sources:
- legacy/serena-skills/21-membership.js

Related inspected skills:
- legacy/serena-skills/45-payflow.js
- legacy/serena-skills/10-payfast.js
- legacy/serena-skills/09-finance.js
- legacy/serena-skills/20-bookings.js
- legacy/serena-skills/58-appointment-reminders.js
- legacy/serena-skills/01-crm.js
- legacy/serena-skills/25-compliance.js
- legacy/serena-skills/02-reporting.js
- legacy/serena-skills/03-gdrive.js
- legacy/serena-skills/08-google-docs.js
- legacy/serena-skills/29-ecommerce.js
- legacy/serena-skills/77-ecommerce-ops.js

Important design decision:
Payflow is not a standalone Serena skill.
Legacy Payflow concepts are absorbed as subscription/payment-flow context under:
- Serena Membership for member/subscription/programme workflow
- Serena Accounting for payment, PayFast, Xero, invoice, and money reality

Purpose:
Serena Membership is the member, subscription, and patient/client programme workflow operator.

Membership handles:
- membership plans
- member profiles
- enrollments
- lifecycle plans
- subscription records
- payment/accounting handoff
- booking handoff
- programme plans
- programme enrollment
- programme progress
- programme follow-up
- Docs/Drive/Reporting handoff
- audit and safety blocks

Architecture:
Membership is the programme/member workflow layer.
Accounting handles invoice/payment/PayFast/Xero readiness.
Bookings handles appointment workflow.
Compliance guards patient/client/health/POPIA/HPCSA-sensitive flows.
Docs/Drive/Reporting handle documentation and reporting handoff.

Foundation commands:
- status
- env-check
- plan
- source-list
- source-info

Membership plan and member profile commands:
- plan-list
- plan-info
- create-member-profile
- member-info
- member-list
- update-member-status

Enrollment and lifecycle commands:
- enrollment-plan
- enroll-member
- cancel-membership-plan
- pause-membership-plan
- renewal-plan

Subscription and handoff commands:
- subscription-plan
- subscription-record
- payment-handoff
- accounting-handoff
- booking-handoff

Programme commands:
- programme-plan
- programme-enroll
- programme-progress
- programme-follow-up

Docs/Drive/Reporting commands:
- docs-handoff
- drive-handoff
- reporting-handoff
- member-summary

Audit and safety commands:
- audit
- blocked-bulk-cancel
- blocked-unapproved-payment-change
- blocked-patient-data-exposure
- blocked-silent-programme-change

Current v1 behavior:
- External APIs are not called by Membership.
- Live payment actions are not performed by Membership.
- Live PayFast actions are not performed by Membership.
- Live Xero/accounting writes are not performed by Membership.
- Live booking/calendar writes are not performed by Membership.
- Google Docs are not created by Membership.
- Drive uploads are not performed by Membership.
- Reports and summaries are created locally as JSON and Markdown where needed.
- Sensitive member/programme handoffs require approval.
- Dangerous membership/payment/programme actions are blocked.

Source model:
- local-membership: local membership/programme evidence layer
- accounting-payments: Accounting / PayFast / Xero handoff
- bookings: appointment/reminder/calendar handoff
- compliance: privacy/POPIA/HPCSA/patient/client guardrails
- docs-drive: member summaries and evidence handoff
- reporting: membership/programme operational summaries
- woocommerce: future ecommerce connector, not called in Membership v1

Allowed:
- create local membership plans
- create local member profiles
- create local enrollment records
- create local subscription records
- prepare payment/accounting handoff
- prepare booking handoff
- create programme progress records
- create follow-up plans
- prepare Docs/Drive/Reporting handoff
- audit membership state
- report exact changes

Guarded:
- patient/client data
- health programme context
- subscription/payment changes
- cancellation/pause/renewal workflows
- external exports
- marketing or reminder use of member data
- Docs/Drive/Reporting handoff
- Accounting/payment handoff

Blocked:
- bulk membership cancellation
- silent programme changes
- unapproved payment amount changes
- changing subscription price silently
- exposing patient/client data
- destructive membership cleanup
- deleting membership evidence
- committing credentials
- final medical, legal, tax, or financial advice

Operator standard:
Serena should act like a membership/programme coordinator:
- understand membership intent
- create local member evidence
- enroll safely
- track subscription and payment state locally
- hand off to Accounting/PayFast/Xero only safely
- hand off to Bookings for appointments
- track programme progress and follow-up
- protect patient/client data
- report exactly what changed
- block dangerous actions

Hub Adapter Layer:
Membership is future Serena Hub compatible.

Future widgets:
- membership_overview_widget
- member_profile_widget
- subscription_status_widget
- programme_progress_widget
- renewal_pipeline_widget
- membership_payment_widget
- membership_approval_widget
- membership_exceptions_widget

Future events:
- membership_plan_created
- member_profile_created
- member_enrolled
- membership_status_updated
- subscription_record_created
- programme_progress_updated
- membership_handoff_created
- membership_report_created
- membership_action_blocked

Future operator state:
- current_business_id
- current_member_id
- current_patient_or_client_id
- current_membership_plan_id
- current_subscription_id
- current_programme_id
- current_payment_status
- current_required_approval
- current_report_path

Completion notes:
Membership / Subscriptions / Patient Programmes Full Operator v1 is complete and safety-tested.
Payflow standalone skill is intentionally skipped because it is covered as subscription/payment-flow context.
Hub Adapter remains pending until Serena Hub dashboard/event bus exists.
