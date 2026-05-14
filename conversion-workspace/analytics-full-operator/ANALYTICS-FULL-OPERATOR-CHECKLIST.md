# Serena Analytics Full Operator v1

Legacy source:

- `legacy/serena-skills/12-analytics.js`

Related skills to inspect:

- `legacy/serena-skills/73-website-revenue-audit.js`
- `legacy/serena-skills/13-wordpress.js`
- `legacy/serena-skills/17-newsletter.js`
- `legacy/serena-skills/19-email-marketing.js`
- `legacy/serena-skills/02-reporting.js`
- `legacy/serena-skills/25-compliance.js`
- `legacy/serena-skills/03-gdrive.js`
- `legacy/serena-skills/08-google-docs.js`
- `legacy/serena-skills/43-clickup.js`
- `legacy/serena-skills/09-finance.js`

Goal:

Turn Serena Analytics into a complete multi-source analytics intelligence operator.

Primary role:

Serena should read, collect, compare, summarize, and explain analytics across:
- WordPress websites
- Google Analytics / GA4 later
- Google Business Profile pages
- Facebook pages
- Meta/Instagram later
- website revenue audits
- content performance
- marketing funnels
- leads/conversions
- Serena operator activity
- future CRM/Business OS data

Serena must be able to manage analytics for multiple businesses and multiple connected assets.

Target capability:

inspect -> connect-plan -> collect -> snapshot -> compare -> summarize -> recommend -> report -> handoff -> audit -> future dashboard widget

Required v1 commands:

Foundation:
- analytics status
- analytics env-check
- analytics plan
- analytics source-list
- analytics source-info

Local analytics:
- analytics from-json
- analytics from-file
- analytics from-folder
- analytics snapshot
- analytics compare

Website analytics:
- analytics wordpress-plan
- analytics wordpress-summary
- analytics ga4-plan
- analytics website-summary

Google Business Profile analytics:
- analytics gbp-env-check
- analytics gbp-plan
- analytics gbp-summary
- analytics gbp-keywords

Meta/Facebook analytics:
- analytics meta-env-check
- analytics facebook-pages
- analytics facebook-page-summary
- analytics social-summary

Insight reports:
- analytics business-overview
- analytics marketing-funnel
- analytics content-performance
- analytics recommendations

Audit and safety:
- analytics audit
- analytics blocked-token-exposure
- analytics blocked-unapproved-posting
- analytics blocked-sensitive-export

Safety model:

Allowed:
- read analytics data
- summarize analytics data
- compare periods
- create local analytics snapshots
- create reports
- hand off summaries to Reporting / Docs / Drive with approval
- recommend actions

Guarded:
- analytics involving patient/client/health/financial data
- exports of business-sensitive metrics
- combining analytics with CRM or revenue data
- public sharing of business analytics

Blocked in v1:
- exposing access tokens or API secrets
- modifying campaigns/pages/posts
- posting content
- deleting analytics data
- altering tracking settings
- unapproved external exports
- final financial/legal/clinical conclusions

Operator standard:

Serena should not merely fetch numbers.

Serena should act like a business analytics operator:
- identify source and date range
- collect metrics
- explain trends
- compare periods
- identify wins/losses
- detect anomalies
- recommend next actions
- create professional reports
- preserve evidence paths
- stay compliance-aware

Hub Adapter Layer:

Analytics must be future Serena Hub compatible.

Future widgets:
- analytics_overview_widget
- website_analytics_widget
- facebook_page_analytics_widget
- google_business_profile_widget
- content_performance_widget
- marketing_funnel_widget
- recommendations_widget
- analytics_export_status_widget

Future events:
- analytics_snapshot_created
- analytics_report_created
- analytics_warning_created
- analytics_export_blocked
- analytics_source_connected
- analytics_audit_completed

Future operator state:
- current_business_id
- current_analytics_source
- current_asset_id
- current_date_range
- current_metric_set
- current_report_path
- current_required_approval

Status target:

`complete_v1_hub_adapter_pending`
