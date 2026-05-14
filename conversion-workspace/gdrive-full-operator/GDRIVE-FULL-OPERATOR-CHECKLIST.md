# Serena Google Drive Full Operator Upgrade

Goal:
Turn Serena Google Drive from a simple legacy Drive helper into a full Google Drive operator for Serena workflows.

Primary role:
Serena must be able to safely use Google Drive as an approved storage and organization layer for:
- WordPress content and media workflows
- Documents skill outputs
- Files skill backups and organized copies
- future Google Docs workflows
- future OCR / camera document capture workflows
- reports, summaries, audits, and operator artifacts

Target capability:
plan -> connect -> inspect -> list -> search -> folder-manage -> upload -> download -> export -> organize -> audit -> report

Expected v1 direction:
- Drive status / connection check
- list files/folders
- search Drive
- create/find folders
- upload files
- download files
- save Serena outputs to Drive
- organize files into approved folders
- audit Drive folder contents
- report clearly on actions taken

Safety model:
- local-to-Drive uploads are allowed
- safe listing/search/reporting allowed
- organization actions should be explicit and inspectable
- destructive delete/permanent removal should be blocked in v1
- Serena should always report exactly what she changed

Operator standard:
Serena should not just "send files to Drive".
She should be able to manage Drive like an operator:
inspect, organize, store, retrieve, and report.
