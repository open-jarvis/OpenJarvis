# Serena Compliance / Policy Guard Full Operator v1

Legacy sources:

- `legacy/serena-skills/24-compliance-guard.js`
- `legacy/serena-skills/25-compliance.js`

Related skills to inspect for compliance hooks:

- `legacy/serena-skills/23-telehealth.js`
- `legacy/serena-skills/37-ocr.js`
- `legacy/serena-skills/57-LabResultsInterpreter.js`
- `legacy/serena-skills/13-wordpress.js`
- `legacy/serena-skills/17-newsletter.js`
- `legacy/serena-skills/19-email-marketing.js`
- `legacy/serena-skills/04-calendar.js`
- `legacy/serena-skills/03-gdrive.js`
- `legacy/serena-skills/08-google-docs.js`

Goal:

Turn Serena Compliance into a central policy, privacy, clinical-safety, marketing-safety, and workflow guard system.

Primary role:

Serena must keep her actions inside the policies she is required to follow.

She must inspect, classify, warn, block, report, and maintain policy awareness across:
- POPIA / privacy
- health information confidentiality
- patient/client data handling
- HPCSA ethical advertising and social media rules
- patient records
- medical/clinical boundaries
- OCR/camera/screen/video data handling
- Google Drive / Google Docs sharing
- Calendar appointments
- CRM/business records
- finance/accounting records
- WordPress/social/newsletter/marketing content
- autonomous/self-evolution actions

Operator standard:

Serena should not merely check text.

Serena should act like a compliance operator:
- inspect the request/action/content
- classify data sensitivity
- identify policy risks
- assign risk level
- recommend changes
- block dangerous actions
- require approval when needed
- write a report
- never expose secrets
- never silently disclose sensitive data
- never silently update policy rules

Risk levels:

LOW:
- general business content
- no personal data
- no health data
- no clinical claims

MEDIUM:
- health education content
- personal information without health detail
- marketing claims needing review
- business-sensitive documents

HIGH:
- patient/client/health data
- lab results
- medical records
- identifiable stories/images
- external sharing
- Drive/Docs uploads containing sensitive info
- bulk exports
- autonomous actions involving sensitive data

BLOCKED:
- silent disclosure of patient/client data
- publishing identifiable patient info without authorization
- autonomous clinical decision
- diagnosis/prescription automation
- destructive bulk patient/client data operations
- hidden camera/audio/screen watching
- secret credential exposure
- silent policy updates

Required v1 commands:

Foundation:
- compliance status
- compliance policy-list
- compliance policy-info
- compliance source-list
- compliance plan
- compliance audit

Core checks:
- compliance quick-check
- compliance full-check
- compliance popia-check
- compliance hpcsa-check
- compliance patient-data-check
- compliance marketing-check
- compliance document-check

Workflow guards:
- compliance ocr-check
- compliance drive-sharing-check
- compliance docs-check
- compliance calendar-check
- compliance crm-check

Policy maintenance:
- compliance update-check
- compliance refresh-plan
- compliance policy-diff
- compliance blocked-policy-update

Safety blocks:
- compliance blocked-disclosure
- compliance blocked-clinical-decision
- compliance blocked-bulk-export
- compliance blocked-hidden-capture

Hub Adapter Layer:

Compliance must be future Serena Hub compatible.

Future widgets:
- compliance risk widget
- policy library widget
- active warning widget
- blocked action widget
- approval requirement widget
- policy update monitor widget
- audit report widget

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

Safety model:

Allowed:
- classify risks
- check content
- check documents
- check workflow actions
- create local reports
- maintain local policy library
- check official/public policy sources
- propose policy updates

Blocked in v1:
- final legal advice
- autonomous clinical decisions
- silent disclosure
- hidden capture
- silent policy rewriting
- destructive/bulk exports
- secret exposure
- committing credentials

Policy update model:

Serena may check if policies changed.
Serena may write a refresh plan.
Serena may propose policy updates.
Serena may not silently activate new policy rules without owner approval.

Status target:

`complete_v1_hub_adapter_pending`
