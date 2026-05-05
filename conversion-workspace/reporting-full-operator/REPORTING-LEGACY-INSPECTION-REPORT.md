# Serena Reporting Legacy Inspection Report

Target:

- Serena Reporting Full Operator v1

Inspected files:

## `legacy\serena-skills\02-reporting.js`

- Lines: 105
- Characters: 3818
- Triggers found: 3
- Functions found: 0
- Dependencies found: 1
- Reporting terms found: 12

Triggers:
- KPI REPORT
- MORNING BRIEF
- WEEKLY REPORT

Functions:
- none detected

Reporting terms:
- calendar
- daily
- dashboard
- export
- kpi
- metric
- patient
- report
- revenue
- summary
- task
- weekly

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\12-analytics.js`

- Lines: 134
- Characters: 5395
- Triggers found: 3
- Functions found: 2
- Dependencies found: 2
- Reporting terms found: 9

Triggers:
- ANALYTICS REPORT
- N/A
- SITE ANALYTICS

Functions:
- fetchTelemetrySummary
- fetchWooMetrics

Reporting terms:
- analytics
- export
- json
- metric
- patient
- report
- revenue
- summary
- task

Dependencies:
- ../helpers/logger
- ../helpers/revenue-engine


## `legacy\serena-skills\25-compliance.js`

- Lines: 98
- Characters: 4160
- Triggers found: 4
- Functions found: 0
- Dependencies found: 1
- Reporting terms found: 4

Triggers:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Functions:
- none detected

Reporting terms:
- compliance
- export
- patient
- report

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\24-compliance-guard.js`

- Lines: 113
- Characters: 4932
- Triggers found: 1
- Functions found: 0
- Dependencies found: 1
- Reporting terms found: 4

Triggers:
- QUICK CHECK:

Functions:
- none detected

Reporting terms:
- compliance
- doc
- export
- patient

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\03-gdrive.js`

- Lines: 96
- Characters: 3508
- Triggers found: 4
- Functions found: 0
- Dependencies found: 2
- Reporting terms found: 4

Triggers:
- DRIVE FOLDER:
- DRIVE LIST:
- DRIVE SAVE:
- DRIVE UPLOAD:

Functions:
- none detected

Reporting terms:
- doc
- drive
- export
- pdf

Dependencies:
- ../helpers/google-drive
- ../helpers/logger


## `legacy\serena-skills\08-google-docs.js`

- Lines: 100
- Characters: 3259
- Triggers found: 5
- Functions found: 3
- Dependencies found: 2
- Reporting terms found: 4

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

Reporting terms:
- doc
- export
- google docs
- task

Dependencies:
- ../helpers/google-docs-service
- ../helpers/logger


## `legacy\serena-skills\37-ocr.js`

- Lines: 148
- Characters: 5369
- Triggers found: 7
- Functions found: 2
- Dependencies found: 3
- Reporting terms found: 4

Triggers:
- EXTRACT TEXT:
- HUGGINGFACE_API_KEY
- MISTRAL_API_KEY
- MODEL_LOADING
- OCR:
- POST
- SCAN DOC:

Functions:
- ocrViaHuggingFace
- ocrViaMistral

Reporting terms:
- doc
- export
- json
- report

Dependencies:
- ../helpers/logger
- fs
- path


## `legacy\serena-skills\04-calendar.js`

- Lines: 183
- Characters: 6910
- Triggers found: 4
- Functions found: 1
- Dependencies found: 2
- Reporting terms found: 4

Triggers:
- BOOK SLOT:
- CANCEL APPOINTMENT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE

Functions:
- getCalendarClient

Reporting terms:
- calendar
- export
- patient
- summary

Dependencies:
- ../helpers/logger
- googleapis


## `legacy\serena-skills\09-finance.js`

- Lines: 171
- Characters: 6730
- Triggers found: 5
- Functions found: 2
- Dependencies found: 2
- Reporting terms found: 4

Triggers:
- GENERATE INVOICE:
- INVOICE SUMMARY
- PAID
- PENDING
- RECORD PAYMENT:

Functions:
- totalAmount
- vatAmount

Reporting terms:
- export
- json
- patient
- summary

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\43-clickup.js`

- Lines: 840
- Characters: 35816
- Triggers found: 36
- Functions found: 27
- Dependencies found: 4
- Reporting terms found: 5

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

Reporting terms:
- export
- json
- report
- summary
- task

Dependencies:
- ../helpers/clickup
- ../helpers/clickup-mcp
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\73-website-revenue-audit.js`

- Lines: 108
- Characters: 3956
- Triggers found: 4
- Functions found: 2
- Dependencies found: 3
- Reporting terms found: 6

Triggers:
- MONETIZATION AUDIT:
- REVENUE AUDIT:
- SITE MONETIZATION:
- WEBSITE REVENUE AUDIT

Functions:
- formatAudit
- formatOutputSync

Reporting terms:
- audit
- export
- json
- revenue
- summary
- task

Dependencies:
- ../helpers/github-content-sync
- ../helpers/logger
- ../helpers/revenue-engine



## Upgrade target

Reporting must become a professional report factory and Serena activity summary system.

It must collect source artifacts, generate clear reports, preserve evidence paths, classify sensitive report risks, support Docs/Drive handoff, and later expose Hub widget metadata.