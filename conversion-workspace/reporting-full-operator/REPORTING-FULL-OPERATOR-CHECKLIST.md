# Serena Reporting Full Operator v1

Legacy source:

- `legacy/serena-skills/02-reporting.js`

Related skills to inspect for reporting hooks:

- `legacy/serena-skills/12-analytics.js`
- `legacy/serena-skills/25-compliance.js`
- `legacy/serena-skills/24-compliance-guard.js`
- `legacy/serena-skills/03-gdrive.js`
- `legacy/serena-skills/08-google-docs.js`
- `legacy/serena-skills/37-ocr.js`
- `legacy/serena-skills/04-calendar.js`
- `legacy/serena-skills/09-finance.js`
- `legacy/serena-skills/43-clickup.js`
- `legacy/serena-skills/73-website-revenue-audit.js`

Goal:

Turn Serena Reporting into a full professional reporting operator.

Primary role:

Serena should create clear, useful, professional reports from her own activity and business data.

Reporting must help Kyle and Dr Piet see:
- what Serena did
- what changed
- what was created
- what was blocked
- what needs approval
- what risks were found
- what actions are next
- what business/operational patterns are visible

Target capability:

inspect -> collect -> summarize -> classify -> create report -> export -> handoff -> audit -> dashboard widget later

Required v1 commands:

Foundation:
- reporting status
- reporting plan
- reporting templates
- reporting template-info

Core reports:
- reporting daily
- reporting weekly
- reporting activity-summary
- reporting compliance-summary
- reporting operator-summary
- reporting business-summary

Source reports:
- reporting from-file
- reporting from-folder
- reporting from-json
- reporting from-text

Handoff:
- reporting save-report
- reporting to-google-doc
- reporting to-drive
- reporting export-md
- reporting export-json

Audit and safety:
- reporting audit
- reporting blocked-sensitive-report
- reporting blocked-unredacted-export

Safety model:

Allowed:
- create reports from local Serena outputs
- summarize local JSON/text/markdown reports
- create professional markdown reports
- save local report artifacts
- hand off reports to Google Docs/Drive when approved and compliance-safe
- preserve source paths and evidence
- report exactly what was included

Guarded:
- reports containing patient/client/health/financial data
- unredacted exports
- sharing externally
- publishing reports
- bulk export summaries
- sensitive compliance reports

Blocked in v1:
- silent export of sensitive reports
- unredacted patient/client/health data export without approval
- final legal/clinical conclusions
- destructive changes to source reports
- deleting source evidence
- exposing secrets/credentials

Operator standard:

Serena should not merely summarize text.

Serena should act like a professional reporting analyst:
- identify source material
- classify report type
- extract key facts
- separate evidence from interpretation
- generate clean sections
- list decisions, blockers, approvals, and next actions
- preserve report paths
- hand off to Docs/Drive only with clear reporting
- stay compliance-aware

Hub Adapter Layer:

Reporting must be future Serena Hub compatible.

Future widgets:
- report_viewer_widget
- daily_report_widget
- weekly_report_widget
- compliance_report_widget
- activity_feed_summary_widget
- approval_summary_widget
- business_kpi_report_widget
- export_status_widget

Future events:
- report_created
- report_exported
- report_handoff_created
- report_blocked
- reporting_audit_completed
- sensitive_report_detected

Future operator state:
- current_business_id
- current_report_type
- current_report_path
- current_report_sources
- current_report_risk_level
- current_export_target
- current_required_approval

Status target:

`complete_v1_hub_adapter_pending`
