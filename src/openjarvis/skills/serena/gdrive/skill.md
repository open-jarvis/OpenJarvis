# Serena Google Drive Full Operator v1

Status: complete v1.

Serena Google Drive is the safe Google Drive storage and organization operator.

## Purpose

The Google Drive skill lets Serena operate inside the configured Drive root folder as a file operator.

Serena can inspect Drive configuration, connect to Google Drive, list files and folders, search Drive, create folder paths, upload local files, download Drive files, inspect file metadata, return Drive links, save generated text to Drive, save existing Serena outputs to Drive, audit Drive folders, and block delete operations in v1.

## Required environment variables

Serena reads these from local environment variables:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GDRIVE_ROOT_FOLDER_ID`

Optional:

- `GDRIVE_LOCAL_PATH`

Secret values must never be printed, committed, logged, or written into reports.

## Commands

Google Drive v1 includes:

- `status`
- `env-check`
- `root-info`
- `plan`
- `connect-check`
- `list`
- `search`
- `mkdir`
- `upload`
- `download`
- `file-info`
- `share-link`
- `save-text`
- `save-output`
- `audit`
- `blocked-delete`

## Safe inspection workflow

Serena can inspect:

- configured env presence without exposing secret values
- configured Drive root folder
- Drive connection status
- root folder contents
- file/folder metadata
- existing Drive links
- folder audit summaries

## Folder workflow

Serena can create or reuse folder paths under the configured Drive root.

Example:

- `Serena Test/Operator Proof`
- `Serena/Documents/Reports`
- `Serena/Outputs`

Serena reports:

- folders created
- folders reused
- target folder ID
- changes made
- delete status

## File workflow

Serena can:

- upload safe local files to Drive
- download Drive files to `outputs/gdrive/downloads`
- save text as Drive files
- save existing Serena output files to Drive
- return Drive file links
- inspect Drive file metadata

Serena blocks uploading sensitive-looking paths such as `.env`, secrets, credentials, passwords, or tokens.

## Search workflow

Serena uses broad visible-Drive search in v1 so nested files can be found.

This is read-only and does not change Drive.

## Audit workflow

Serena can audit a Drive folder and report:

- items scanned
- folder count
- file count
- total file size
- duplicate name groups
- item links
- local audit report path

Audit is read-only.

## Delete safety

Google Drive delete is deliberately blocked in v1.

Blocked:

- delete
- trash
- permanent delete
- empty trash

The `blocked-delete` command exists to prove that delete remains blocked and report the attempted request safely.

## Safety model

Allowed in v1:

- inspect env presence
- connect-check
- list files/folders
- search Drive
- create folders inside configured root
- upload safe local files
- download non-native Drive files
- inspect file metadata
- return existing links
- save text to Drive
- save Serena output files to Drive
- audit folders
- write local reports

Blocked in v1:

- delete
- trash
- permanent delete
- ownership changes
- exposing secrets
- committing credentials
- uploading sensitive-looking files
- operating destructively outside the configured root

## Integration with other Serena skills

Documents:

- save generated reports to Drive
- store extracted/summarized documents
- support future Google Docs handoff

Files:

- save organized outputs to Drive
- back up safe files to Drive
- store operator reports

WordPress:

- store content packs, images, documents, and publish artifacts
- retrieve links to Drive assets

VS Code / VS Code Builder:

- save build reports, checklists, generated files, and project artifacts

Future OCR / Camera:

- upload captured document images
- save extracted text
- store generated Word/PDF outputs

## Operator standard

Serena should not merely upload files.

Serena should operate Google Drive like a careful file operator:

- inspect first
- use the approved Drive root
- create folders intentionally
- upload/download safely
- return links
- audit contents
- report exactly what changed
- never delete in v1
