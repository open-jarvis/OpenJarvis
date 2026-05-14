# Serena Compliance / Policy Guard Full Operator v1

Status: complete_v1_hub_adapter_pending

Legacy sources:
- legacy/serena-skills/24-compliance-guard.js
- legacy/serena-skills/25-compliance.js

Related inspected skills:
- legacy/serena-skills/23-telehealth.js
- legacy/serena-skills/37-ocr.js
- legacy/serena-skills/57-LabResultsInterpreter.js
- legacy/serena-skills/13-wordpress.js
- legacy/serena-skills/17-newsletter.js
- legacy/serena-skills/19-email-marketing.js
- legacy/serena-skills/04-calendar.js
- legacy/serena-skills/03-gdrive.js
- legacy/serena-skills/08-google-docs.js

Legacy triggers:
- QUICK CHECK:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Purpose:
Serena Compliance is the central policy, privacy, clinical-safety, marketing-safety, workflow-guard, and policy-update governance operator.

Serena must use Compliance to inspect, classify, warn, block, report, and maintain policy awareness across:
- POPIA / privacy
- health confidentiality
- patient/client data
- HPCSA patient records
- HPCSA social media and health marketing
- clinical boundaries
- OCR / camera / screen / video capture
- Google Drive
- Google Docs
- Google Calendar
- CRM / future Serena Hub
- finance/accounting later
- marketing/content publishing later
- autonomous/self-evolution actions later

Local policy library:
- popia
- national-health-confidentiality
- hpcsa-patient-records
- hpcsa-social-media-marketing
- clinical-boundaries
- data-sharing
- vision-capture
- policy-update-governance

Foundation commands:
- status
- policy-list
- policy-info
- source-list
- plan

Core risk checks:
- quick-check
- full-check
- popia-check
- hpcsa-check
- patient-data-check
- marketing-check
- document-check

Workflow guards:
- ocr-check
- drive-sharing-check
- docs-check
- calendar-check
- crm-check

Policy maintenance:
- update-check
- refresh-plan
- policy-diff
- blocked-policy-update

Audit and safety blocks:
- audit
- blocked-disclosure
- blocked-clinical-decision
- blocked-bulk-export
- blocked-hidden-capture

Risk levels:
- LOW
- MEDIUM
- HIGH
- BLOCKED

Core safety rules:
- Silent disclosure is blocked.
- Hidden capture is blocked.
- Autonomous clinical decisions are blocked.
- Diagnosis/prescription automation is blocked.
- Destructive or unreviewed bulk sensitive-data export is blocked.
- Silent policy rewriting is blocked.
- Secret exposure is blocked.
- Credentials must never be committed.
- High-risk health/patient/personal-data workflows require approval or human review.
- Policy updates may be checked, planned, and diffed, but not silently activated.

Operator standard:
Serena should not merely check text. Serena should act like a compliance operator:
- inspect the request/action/content
- classify sensitive data
- classify risk
- identify warnings
- identify blockers
- identify approval requirements
- write a report
- refuse unsafe actions
- preserve auditability

Policy update model:
Serena may:
- check local policy inventory
- list policy source registry entries
- create refresh plans
- compare proposed policy text
- write update reports

Serena may not:
- silently rewrite active policy rules
- silently activate new policy rules
- treat uncertain policy changes as final legal advice
- delete policy history

Hub Adapter Layer:
Compliance is future Serena Hub compatible.

Future widgets:
- compliance_risk_widget
- policy_library_widget
- active_warning_widget
- blocked_action_widget
- approval_requirement_widget
- policy_update_monitor_widget
- audit_report_widget

Future events:
- compliance_checked
- compliance_warning_created
- compliance_action_blocked
- compliance_policy_update_available
- compliance_approval_required
- compliance_audit_completed

Future operator state:
- current_business_id
- current_policy_context
- current_risk_level
- current_sensitive_data_types
- current_blocked_reason
- current_compliance_report
- current_required_approval

Completion notes:
Compliance Full Operator v1 is complete and safety-tested. Hub Adapter remains pending until Serena Hub dashboard/event bus exists.
