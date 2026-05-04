# Serena Google Docs Full Operator v1

Legacy source:

- `legacy/serena-skills/08-google-docs.js`

Goal:

Turn Serena Google Docs into a full document operator that can create, read, edit, copy, export, and link professional Google Docs.

Primary role:

Serena should use Google Docs as a professional document creation and editing layer for:

- medical/business notes
- reports
- SOPs
- meeting notes
- summaries
- checklists
- patient education drafts
- WordPress/content drafts
- Google Drive document workflows
- OCR/camera-capture outputs later

Target capability:

plan -> connect -> create -> read -> update -> append -> copy -> export -> link -> save-output -> audit -> report

Required v1 commands:

- google-docs status
- google-docs env-check
- google-docs connect-check
- google-docs create
- google-docs read
- google-docs append
- google-docs update-title
- google-docs copy
- google-docs export
- google-docs link
- google-docs create-note
- google-docs create-report
- google-docs save-output
- google-docs audit
- google-docs blocked-delete

Safety model:

Allowed:
- create Google Docs
- read Google Docs
- append content
- update title
- copy documents
- export/download documents
- return existing Drive links
- save local Serena outputs into Google Docs
- store docs in configured Drive root/folders
- write local reports

Blocked in v1:
- delete Google Docs
- trash documents
- permanent delete
- ownership changes
- exposing credentials
- committing credentials
- destructive bulk edits

Operator standard:

Serena should not merely create plain docs.

Serena should create professional structured documents, use headings and sections, preserve links, report exactly what changed, and return the Google Drive link.
