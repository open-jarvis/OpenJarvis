# Serena Google Docs Legacy Inspection Report

Legacy source:

- `legacy\serena-skills\08-google-docs.js`

Initial inspection:

- Lines: 100
- Characters: 3259
- Functions found: 3
- Dependencies found: 2
- Triggers found: 2
- Env variable names mentioned: 3

Triggers:

- CREATE DOC:
- UPDATE DOC:

Environment variables expected through Google auth layer:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GDRIVE_ROOT_FOLDER_ID`

Security rule:

Real credential values must never be committed, logged, printed, or written into reports.

Target:

Serena Google Docs Full Operator v1 should let Serena create, read, edit, copy, export, link, and report on professional Google Docs.

Required lifecycle:

1. Check Google Docs operator status.
2. Check required env variable presence without printing secrets.
3. Connect-check Google Docs and Drive APIs.
4. Create professional Google Docs.
5. Read Google Docs text.
6. Append content.
7. Update document title.
8. Copy documents.
9. Export/download documents.
10. Return Google Drive links.
11. Save existing Serena outputs into Google Docs.
12. Audit created Docs outputs.
13. Block destructive delete/permanent removal in v1.

Operator standard:

Serena should not merely create plain Google Docs.
Serena should create professional structured documents and notes, preserve links, use Drive folders, and report exactly what changed.
