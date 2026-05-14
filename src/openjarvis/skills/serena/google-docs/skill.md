# Serena Google Docs Full Operator v1

Status: complete v1.

Serena Google Docs is the professional Google Docs creation, editing, export, and document-operations skill.

## Purpose

The Google Docs skill lets Serena create, read, edit, copy, export, link, and audit professional Google Docs using the configured Google account and approved Google Drive root.

Serena can create structured documents, notes, reports, SOPs, checklists, summaries, consultation notes, content drafts, and business documents.

## Required environment variables

Serena reads these from local environment variables:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GDRIVE_ROOT_FOLDER_ID`

The refresh token must include both Drive and Docs scopes:

- `https://www.googleapis.com/auth/drive`
- `https://www.googleapis.com/auth/documents`

Secret values must never be printed, committed, logged, or written into reports.

## Commands

Google Docs v1 includes:

- `status`
- `env-check`
- `connect-check`
- `plan`
- `create`
- `read`
- `append`
- `update-title`
- `link`
- `copy`
- `export`
- `create-note`
- `create-report`
- `save-output`
- `audit`
- `blocked-delete`

## Capabilities

Serena can:

- check Google Docs and Drive configuration
- connect-check the Docs and Drive APIs
- create professional Google Docs
- read Google Doc text content
- append content with optional headings
- update document titles
- return existing Google Docs links
- copy documents
- export documents as PDF, DOCX, TXT, or HTML
- create structured notes
- create structured reports
- convert existing Serena output/checklist text files into Google Docs
- audit visible Google Docs
- write local reports for every operation

## Professional document workflow

Serena should create documents with structure, not plain text dumps.

For notes, Serena should include:

- title
- prepared by Serena
- notes section
- next actions section

For reports, Serena should include:

- title
- prepared by Serena
- executive summary
- key points
- next actions

## Drive integration

Serena can place created and copied Google Docs inside the configured Google Drive root and target folder paths, such as:

- `Serena Test/Operator Proof`
- `Serena/Documents/Reports`
- `Serena/Google Docs Outputs`

Every create/copy/save-output command should return the Google Docs link.

## Export workflow

Serena can export Google Docs locally under:

- `outputs/google-docs/exports`

Supported formats:

- PDF
- DOCX
- TXT
- HTML

## Audit workflow

Serena can audit visible Google Docs and report:

- query used
- number of docs scanned
- duplicate name groups
- document IDs
- modified timestamps
- Google Docs links
- local report path

Audit is read-only.

## Delete safety

Google Docs delete is deliberately blocked in v1.

Blocked:

- delete
- trash
- permanent delete
- ownership changes
- destructive bulk edits

The `blocked-delete` command exists to prove delete remains blocked and to report attempted delete requests safely.

## Safety model

Allowed in v1:

- inspect env presence
- connect-check
- create Google Docs
- read Google Docs
- append content
- update title
- copy documents
- export/download documents
- return existing links
- create notes
- create reports
- save Serena outputs as Google Docs
- audit visible Docs
- write local reports

Blocked in v1:

- delete
- trash
- permanent delete
- ownership changes
- exposing secrets
- committing credentials
- destructive bulk edits

## Integration with other Serena skills

Google Drive:

- stores Docs inside the configured root/folders
- provides links and folder structure

Documents:

- can hand off generated reports and cleaned text to Google Docs

Files:

- can save approved local outputs as Google Docs

WordPress:

- can draft long-form content in Google Docs before publishing

OCR / Camera future skill:

- can send extracted document text into Google Docs

VS Code / VS Code Builder:

- can store project docs, reports, SOPs, and handoff notes in Google Docs

## Operator standard

Serena should operate Google Docs like a professional document assistant:

- plan first
- create structured documents
- preserve links
- place docs in approved Drive folders
- read and inspect when asked
- append or rename safely
- export when needed
- report exactly what changed
- never delete in v1
