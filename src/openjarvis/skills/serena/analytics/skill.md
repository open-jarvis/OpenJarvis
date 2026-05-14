# Serena Analytics Full Operator v1

Status: complete_v1_hub_adapter_pending

Legacy source:
- legacy/serena-skills/12-analytics.js

Related inspected skills:
- legacy/serena-skills/73-website-revenue-audit.js
- legacy/serena-skills/13-wordpress.js
- legacy/serena-skills/17-newsletter.js
- legacy/serena-skills/19-email-marketing.js
- legacy/serena-skills/02-reporting.js
- legacy/serena-skills/25-compliance.js
- legacy/serena-skills/03-gdrive.js
- legacy/serena-skills/08-google-docs.js
- legacy/serena-skills/43-clickup.js
- legacy/serena-skills/09-finance.js

Legacy triggers:
- ANALYTICS REPORT
- SITE ANALYTICS

Purpose:
Serena Analytics is the multi-source analytics, business intelligence, marketing insight, website performance, social performance, Google Business Profile, and recommendation operator.

Serena Analytics covers:
- WordPress / WooCommerce / Jetpack analytics planning and summaries
- Google Analytics 4 planning
- Google Business Profile planning, summaries, and keyword analytics
- Meta / Facebook Page planning and summaries
- Combined social summaries
- Local Serena operator analytics
- Business overviews
- Marketing funnel analysis
- Content performance analysis
- Recommendations
- Analytics audit and safety blocks

Foundation commands:
- status
- env-check
- plan
- source-list
- source-info

Local analytics commands:
- from-json
- from-file
- from-folder
- snapshot
- compare

Website analytics commands:
- wordpress-plan
- wordpress-summary
- ga4-plan
- website-summary

Google Business Profile commands:
- gbp-env-check
- gbp-plan
- gbp-summary
- gbp-keywords

Meta/Facebook commands:
- meta-env-check
- facebook-pages
- facebook-page-summary
- social-summary

Insight commands:
- business-overview
- marketing-funnel
- content-performance
- recommendations

Audit and safety commands:
- audit
- blocked-token-exposure
- blocked-unapproved-posting
- blocked-sensitive-export

Current v1 behavior:
- External APIs are not called unless future live connector credentials are configured.
- Serena can analyze pasted/exported metrics immediately.
- Serena can create local snapshots and markdown analytics reports.
- Serena can compare JSON metrics.
- Serena can audit readiness for WordPress, GA4, GBP, Facebook, and local Serena analytics.
- Serena can verify environment variable presence without exposing values.

Required future live credentials:
WordPress:
- WORDPRESS_SITE_URL
- WORDPRESS_USERNAME
- WORDPRESS_APP_PASSWORD
- WOOCOMMERCE_CONSUMER_KEY
- WOOCOMMERCE_CONSUMER_SECRET
- JETPACK_SITE_ID

GA4:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- GA4_PROPERTY_ID

Google Business Profile:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- GBP_ACCOUNT_ID
- GBP_LOCATION_IDS

Meta/Facebook:
- META_APP_ID
- META_APP_SECRET
- META_ACCESS_TOKEN
- FACEBOOK_PAGE_IDS

Safety model:
Allowed:
- read analytics data
- summarize analytics data
- compare periods
- create local analytics snapshots
- create reports
- recommend actions
- hand off summaries to Reporting, Google Docs, or Google Drive later with approval

Guarded:
- analytics involving patient/client/health/financial data
- exports of business-sensitive metrics
- combining analytics with CRM or revenue data
- public sharing of business analytics

Blocked:
- exposing access tokens or API secrets
- modifying campaigns/pages/posts
- posting content
- deleting analytics data
- altering tracking settings
- unapproved external exports
- final financial/legal/clinical conclusions

Operator standard:
Serena should not merely fetch numbers. Serena should act like a business analytics operator:
- identify source and date range
- collect or load metrics
- explain trends
- compare periods
- identify wins, losses, bottlenecks, and anomalies
- recommend next actions
- create professional reports
- preserve evidence paths
- stay compliance-aware

Hub Adapter Layer:
Analytics is future Serena Hub compatible.

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

Completion notes:
Analytics Full Operator v1 is complete and safety-tested. Hub Adapter remains pending until Serena Hub dashboard/event bus exists.
