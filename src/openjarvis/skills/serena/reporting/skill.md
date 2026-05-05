# Serena Reporting Full Operator v1

Status: complete_v1_hub_adapter_pending

Legacy source:
- legacy/serena-skills/02-reporting.js

Related inspected skills:
- legacy/serena-skills/12-analytics.js
- legacy/serena-skills/25-compliance.js
- legacy/serena-skills/24-compliance-guard.js
- legacy/serena-skills/03-gdrive.js
- legacy/serena-skills/08-google-docs.js
- legacy/serena-skills/37-ocr.js
- legacy/serena-skills/04-calendar.js
- legacy/serena-skills/09-finance.js
- legacy/serena-skills/43-clickup.js
- legacy/serena-skills/73-website-revenue-audit.js

Legacy triggers:
- MORNING BRIEF
- WEEKLY REPORT
- KPI REPORT

Purpose:
Serena Reporting is the professional reporting, activity summary, export, and handoff operator.

Serena Reporting helps Kyle and Dr Piet see:
- what Serena did
- what changed
- what was created
- what was exported
- what was handed off
- what was blocked
- what needs approval
- what risks were found
- what evidence/source paths support the report
- what should happen next

Foundation commands:
- status
- plan
- templates
- template-info

Source report commands:
- from-text
- from-json
- from-file
- from-folder

Standard report commands:
- daily
- weekly
- activity-summary
- compliance-summary
- operator-summary
- business-summary

Export and handoff commands:
- save-report
- export-md
- export-json
- to-google-doc
- to-drive

Audit and safety commands:
- audit
- blocked-sensitive-report
- blocked-unredacted-export

Templates:
- daily
- weekly
- activity-summary
- compliance-summary
- operator-summary
- business-summary

Safety model:
Allowed:
- create reports from local Serena outputs
- summarize local JSON/text/markdown reports
- create professional markdown reports
- save local report artifacts
- export local markdown and JSON
- preserve source paths and evidence
- report exactly what was included
- hand off reports to Google Docs/Drive only with explicit approval

Guarded:
- reports containing patient/client/health/financial data
- unredacted exports
- sharing externally
- publishing reports
- bulk export summaries
- sensitive compliance reports

Blocked:
- silent export of sensitive reports
- unredacted patient/client/health data export without approval
- final legal/clinical conclusions
- destructive changes to source reports
- deleting source evidence
- exposing secrets or credentials

Operator standard:
Serena should not merely summarize text. Serena should act like a professional reporting analyst:
- identify source material
- classify report type
- collect source summaries
- separate evidence from interpretation
- generate clear sections
- list decisions, blockers, approvals, and next actions
- preserve source paths
- export only with reporting
- hand off externally only when approved and compliance-safe

Hub Adapter Layer:
Reporting is future Serena Hub compatible.

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

Completion notes:
Reporting Full Operator v1 is complete and safety-tested. Hub Adapter remains pending until Serena Hub dashboard/event bus exists.
