# Serena Google Drive Full Operator v1

Legacy source:

- `legacy\serena-skills\03-gdrive.js`

Initial inspection:

- Lines: 96
- Characters: 3508
- Functions found: 0
- Dependencies found: 2
- Triggers found: 4
- Env variable names mentioned: 1

Triggers:

- DRIVE SAVE:
- DRIVE LIST:
- DRIVE FOLDER:
- DRIVE UPLOAD:

Environment variables expected:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `GDRIVE_ROOT_FOLDER_ID`

Security rule:

Real credential values must never be committed, logged, printed, or written into reports.

Target:

Serena Google Drive Full Operator v1 should let Serena use Google Drive as a safe storage and organization layer.

Required lifecycle:

1. Check Google Drive operator status.
2. Check required env variable presence without printing secrets.
3. Check configured root folder ID.
4. List files/folders.
5. Search Drive.
6. Create/find folders.
7. Upload local files.
8. Download files.
9. Save Serena outputs to Drive.
10. Audit folder contents.
11. Write local reports.
12. Block destructive delete/permanent removal in v1.

Operator standard:

Serena should not just upload files.
Serena should inspect, organize, store, retrieve, audit, and report.
