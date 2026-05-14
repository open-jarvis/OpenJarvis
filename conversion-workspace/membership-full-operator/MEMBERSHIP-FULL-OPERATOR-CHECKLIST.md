# Serena Membership / Subscriptions / Patient Programmes Full Operator v1

Legacy sources:

- `legacy/serena-skills/21-membership.js`
- `legacy/serena-skills/45-payflow.js`

Related skills to inspect:

- `legacy/serena-skills/10-payfast.js`
- `legacy/serena-skills/09-finance.js`
- `legacy/serena-skills/20-bookings.js`
- `legacy/serena-skills/58-appointment-reminders.js`
- `legacy/serena-skills/01-crm.js`
- `legacy/serena-skills/25-compliance.js`
- `legacy/serena-skills/02-reporting.js`
- `legacy/serena-skills/03-gdrive.js`
- `legacy/serena-skills/08-google-docs.js`
- `legacy/serena-skills/29-ecommerce.js`
- `legacy/serena-skills/77-ecommerce-ops.js`

Goal:

Turn legacy membership/subscription/payflow functionality into a complete patient/client programme and membership operator.

Primary role:

Serena should manage memberships, subscription records, patient/client programme enrollment, programme progress, renewals, cancellations, pauses, payment handoff, accounting handoff, booking handoff, Docs/Drive/Reporting handoff, audit, and safety blocks.

Architecture:

Membership is the programme/member workflow layer.
Accounting handles invoice/payment/PayFast/Xero readiness.
Bookings handles appointment workflow.
Compliance guards patient/client/health/POPIA/HPCSA-sensitive flows.
Docs/Drive/Reporting handle documentation and reporting handoff.

Target capability:

plan -> profile -> enroll -> subscription record -> payment/accounting handoff -> booking handoff -> progress -> follow-up -> renewal/cancel/pause plan -> reporting -> audit -> safety blocks

Required v1 commands:

Layer 1 — Foundation:
- membership status
- membership env-check
- membership plan
- membership source-list
- membership source-info

Layer 2 — Membership plans and member profiles:
- membership plan-list
- membership plan-info
- membership create-member-profile
- membership member-info
- membership member-list
- membership update-member-status

Layer 3 — Enrollment / pause / cancel / renewal:
- membership enrollment-plan
- membership enroll-member
- membership cancel-membership-plan
- membership pause-membership-plan
- membership renewal-plan

Layer 4 — Subscriptions and handoff:
- membership subscription-plan
- membership subscription-record
- membership payment-handoff
- membership accounting-handoff
- membership booking-handoff

Layer 5 — Patient programmes:
- membership programme-plan
- membership programme-enroll
- membership programme-progress
- membership programme-follow-up

Layer 6 — Docs/Drive/Reporting handoff:
- membership docs-handoff
- membership drive-handoff
- membership reporting-handoff
- membership member-summary

Layer 7 — Audit and safety:
- membership audit
- membership blocked-bulk-cancel
- membership blocked-unapproved-payment-change
- membership blocked-patient-data-exposure
- membership blocked-silent-programme-change

Safety model:

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
- accounting/payment handoff

Blocked in v1 unless explicit approval layer exists:
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

Membership must be future Serena Hub compatible.

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

Status target:

`complete_v1_hub_adapter_pending`
