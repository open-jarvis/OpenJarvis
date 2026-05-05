# Serena Analytics Legacy Inspection Report

Target:

- Serena Analytics Full Operator v1

Inspected files:

## `legacy\serena-skills\12-analytics.js`

- Lines: 134
- Characters: 5395
- Triggers found: 3
- Functions found: 2
- Dependencies found: 2
- Analytics terms found: 11
- Env/integration mentions: 4

Triggers:
- ANALYTICS REPORT
- N/A
- SITE ANALYTICS

Functions:
- fetchTelemetrySummary
- fetchWooMetrics

Analytics terms:
- analytics
- booking
- export
- json
- metric
- page
- report
- revenue
- summary
- woocommerce
- wordpress

Env/integration mentions:
- ANALYTICS
- WOOCOMMERCE_KEY
- WOOCOMMERCE_SECRET
- WORDPRESS_URL

Dependencies:
- ../helpers/logger
- ../helpers/revenue-engine


## `legacy\serena-skills\73-website-revenue-audit.js`

- Lines: 108
- Characters: 3956
- Triggers found: 4
- Functions found: 2
- Dependencies found: 3
- Analytics terms found: 8
- Env/integration mentions: 1

Triggers:
- MONETIZATION AUDIT:
- REVENUE AUDIT:
- SITE MONETIZATION:
- WEBSITE REVENUE AUDIT

Functions:
- formatAudit
- formatOutputSync

Analytics terms:
- audit
- export
- json
- meta
- page
- revenue
- summary
- wordpress

Env/integration mentions:
- WORDPRESS_URL

Dependencies:
- ../helpers/github-content-sync
- ../helpers/logger
- ../helpers/revenue-engine


## `legacy\serena-skills\17-newsletter.js`

- Lines: 120
- Characters: 5433
- Triggers found: 3
- Functions found: 1
- Dependencies found: 2
- Analytics terms found: 1
- Env/integration mentions: 0

Triggers:
- HEALTH NEWSLETTER:
- NEWSLETTER:
- WEEKLY NEWSLETTER

Functions:
- shouldSend

Analytics terms:
- export

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger
- nodemailer


## `legacy\serena-skills\19-email-marketing.js`

- Lines: 131
- Characters: 5140
- Triggers found: 2
- Functions found: 0
- Dependencies found: 2
- Analytics terms found: 3
- Env/integration mentions: 1

Triggers:
- EMAIL CAMPAIGN:
- EMAIL DRAFT:

Functions:
- none detected

Analytics terms:
- campaign
- export
- google

Env/integration mentions:
- API

Dependencies:
- ../helpers/logger
- nodemailer


## `legacy\serena-skills\02-reporting.js`

- Lines: 105
- Characters: 3818
- Triggers found: 3
- Functions found: 0
- Dependencies found: 1
- Analytics terms found: 10
- Env/integration mentions: 0

Triggers:
- KPI REPORT
- MORNING BRIEF
- WEEKLY REPORT

Functions:
- none detected

Analytics terms:
- booking
- dashboard
- export
- google
- kpi
- metric
- report
- revenue
- summary
- woocommerce

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\25-compliance.js`

- Lines: 98
- Characters: 4160
- Triggers found: 4
- Functions found: 0
- Dependencies found: 1
- Analytics terms found: 4
- Env/integration mentions: 1

Triggers:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Functions:
- none detected

Analytics terms:
- export
- impression
- meta
- report

Env/integration mentions:
- META

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\03-gdrive.js`

- Lines: 96
- Characters: 3508
- Triggers found: 4
- Functions found: 0
- Dependencies found: 2
- Analytics terms found: 2
- Env/integration mentions: 0

Triggers:
- DRIVE FOLDER:
- DRIVE LIST:
- DRIVE SAVE:
- DRIVE UPLOAD:

Functions:
- none detected

Analytics terms:
- export
- google

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/google-drive
- ../helpers/logger


## `legacy\serena-skills\08-google-docs.js`

- Lines: 100
- Characters: 3259
- Triggers found: 5
- Functions found: 3
- Dependencies found: 2
- Analytics terms found: 2
- Env/integration mentions: 4

Triggers:
- CREATE DOC:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- UPDATE DOC:

Functions:
- generateDocContent
- parsePayload
- replaceExisting

Analytics terms:
- export
- google

Env/integration mentions:
- GOOGLE
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN

Dependencies:
- ../helpers/google-docs-service
- ../helpers/logger


## `legacy\serena-skills\43-clickup.js`

- Lines: 840
- Characters: 35816
- Triggers found: 36
- Functions found: 27
- Dependencies found: 4
- Analytics terms found: 4
- Env/integration mentions: 3

Triggers:
- CU ASK:
- CU CREATE FOLDER:
- CU CREATE LIST:
- CU CREATE SPACE:
- CU CREATE TASK:
- CU DELETE FOLDER:
- CU DELETE LIST:
- CU DELETE SPACE:
- CU DELETE TASK:
- CU FOLDERS
- CU FOLDERS:
- CU LIST
- CU LIST SPACES
- CU LIST SPACES:
- CU LIST TASKS
- CU LIST TASKS:
- CU LIST:
- CU LISTS
- CU LISTS:
- CU MCP COMMENT:
- CU MCP REPORT:
- CU MCP SEARCH:
- CU MCP TIME:
- CU SETUP
- CU SPACES:
- CU STRUCTURE
- CU STRUCTURE:
- CU SUBTASK:
- CU TASK:
- CU UPDATE FOLDER:
- CU UPDATE LIST:
- CU UPDATE SPACE:
- CU UPDATE:
- CU WORKSPACES
- CU WORKSPACES:
- TASK:

Functions:
- buildRestFallback
- configMessage
- formatMcpResultForTelegram
- formatRestFallback
- formatSingleMcpItem
- formatSpaces
- formatTimestamp
- formatTree
- formatWorkspaces
- humanizeHierarchy
- inferMcpIntent
- isConfigured
- maybeCallClickUpMcp
- mergeRequest
- normalizeTriggerPayload
- parseLooseFields
- parseOperationRequest
- resolveFolder
- resolveList
- resolveSpace
- resolveTask
- resolveWorkspaceId
- safeParseMcpJson
- sanitizeLine
- searchTasksAcrossWorkspace
- stripCodeFences
- summarizeItem

Analytics terms:
- export
- json
- report
- summary

Env/integration mentions:
- API
- CLICKUP_API_KEY
- SEARCH

Dependencies:
- ../helpers/clickup
- ../helpers/clickup-mcp
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\09-finance.js`

- Lines: 171
- Characters: 6730
- Triggers found: 5
- Functions found: 2
- Dependencies found: 2
- Analytics terms found: 3
- Env/integration mentions: 0

Triggers:
- GENERATE INVOICE:
- INVOICE SUMMARY
- PAID
- PENDING
- RECORD PAYMENT:

Functions:
- totalAmount
- vatAmount

Analytics terms:
- export
- json
- summary

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## Missing files

- legacy\serena-skills\13-wordpress.js

## Upgrade target

Analytics must become a multi-source business intelligence operator.

It must support WordPress, Google Business Profile, Meta/Facebook, website metrics, content performance, marketing funnels, recommendations, reports, exports, and future Hub widgets.