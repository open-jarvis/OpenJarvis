# Serena Files Full Operator v1

Status: complete v1.

Serena is now a trusted local file operator for approved folders and safe local file workflows.

## Purpose

The Files skill gives Serena controlled local file-system capability.

Serena can:

- inspect approved folders
- index files
- search by filename
- search safe text content
- read safe text files
- audit folders
- snapshot files
- copy files safely
- move files only with explicit approval
- find cleanup candidates without deleting anything
- plan backups
- create local zip backups
- organize files by copying them into categorized folders
- operate on registered approved folder aliases

## Approved file roots

Serena uses a registered folder system instead of roaming the computer blindly.

Approved file roots are stored in:

- `config/serena_file_roots.json`

Current root aliases include:

- `serena-project`
- `serena-outputs`
- `drpiet-documents`
- `drpiet-downloads`
- `drpiet-desktop`

Each root has:

- path
- description
- category
- allow_search
- allow_audit
- allow_backup
- allow_organize

Serena should prefer approved root aliases over raw paths when operating on important folders.

Natural examples:

- ?Serena, search Dr Piet documents for medical aid billing.?
- ?Serena, audit Dr Piet downloads.?
- ?Serena, back up Serena outputs.?
- ?Serena, organize the approved outputs folder.?
- ?Serena, find cleanup candidates in Dr Piet desktop.?

## Core commands

Serena Files v1 includes:

- `status`
- `index`
- `search`
- `read`
- `audit`
- `snapshot`
- `snapshots`
- `copy`
- `move`
- `cleanup-candidates`
- `backup-plan`
- `backup`
- `roots`
- `root-info`
- `root-index`
- `root-search`
- `root-audit`
- `root-backup-plan`
- `root-backup`
- `root-organize`
- `root-cleanup-candidates`

## Safety rules

Serena must follow these file safety rules:

1. Do not roam the entire computer blindly.
2. Prefer approved file roots.
3. Copy is allowed by default.
4. Move requires explicit approval.
5. Snapshot before approved moves.
6. Do not overwrite existing files; create unique target names.
7. Permanent delete is excluded from Files v1.
8. Cleanup-candidates only reports; it does not delete.
9. Backups are local zip backups under `outputs/files/backups/`.
10. Reports, indexes, and manifests are saved under `outputs/files/`.
11. Serena must report exactly what changed.
12. Serena must preserve originals unless an approved move is requested.

## Output folders

Files output root:

- `outputs/files/`

Reports:

- `outputs/files/reports/`

Indexes:

- `outputs/files/indexes/`

Snapshots:

- `outputs/files/snapshots/`

Backups:

- `outputs/files/backups/`

Organized copies:

- `outputs/files/organized/`

## File reading

Serena can safely preview common text/code/config file types such as:

- `.txt`
- `.md`
- `.rtf`
- `.json`
- `.yaml`
- `.yml`
- `.csv`
- `.log`
- `.py`
- `.js`
- `.ts`
- `.tsx`
- `.jsx`
- `.html`
- `.css`
- `.xml`
- `.toml`
- `.ini`
- `.cfg`
- `.ps1`
- `.bat`
- `.sh`
- `.sql`

Binary files are not read as text by Files. For document content extraction, Serena should use the Documents skill.

## Backup behavior

Serena can plan backups before creating them.

Backup-plan reports:

- source folder
- recursive setting
- number of files
- estimated size
- planned backup path

Backup creates:

- zip file
- manifest JSON
- file count
- backup location

## Organization behavior

Serena can organize files by copying them into categorized folders.

Examples of categories:

- `billing-finance`
- `healthcare`
- `legal-compliance`
- `documents`
- `images`
- `audio`
- `video`
- `code-config`
- `archives`
- `general`

Organizing does not move or delete originals.

## Cleanup behavior

Serena can find cleanup candidates:

- duplicate groups
- empty files
- large files
- unsupported extensions

Files v1 does not delete anything.

## Integration with Documents

Files manages where documents live.

Documents handles document understanding.

Use Files for:

- finding files
- organizing folders
- copying
- moving with approval
- backups
- snapshots
- cleanup candidates

Use Documents for:

- extracting text
- summarizing
- classifying
- extracting structured fields
- PDF/DOCX handling
- document reports

## Future integration: Webcam document capture

Serena should later support a camera/document-capture workflow:

1. Use an approved webcam or camera source.
2. Look at a physical paper/document.
3. Capture a readable image.
4. Extract text using OCR or vision.
5. Send extracted text into the Documents skill.
6. Clean, classify, summarize, and extract fields.
7. Export the result as Word/DOCX or PDF.
8. Store the generated file through the Files skill.
9. Organize it into an approved folder/root.
10. Preserve capture artifacts and generated outputs.

This should likely be implemented as a separate Camera/Vision/OCR skill that integrates with Documents and Files.

Files skill responsibility:

- store outputs
- organize outputs
- index outputs
- back up outputs
- protect originals
- manage approved folders

Documents skill responsibility:

- clean extracted text
- classify
- summarize
- extract fields
- generate DOCX/PDF reports

Camera/OCR skill responsibility:

- capture image
- validate readability
- extract text
- flag low-confidence or unreadable captures

## Operator standard

Serena should act like a careful local file operator:

- use approved roots
- inspect before acting
- plan before backups
- snapshot before risky operations
- copy safely
- move only with approval
- never delete in v1
- report exactly what changed
- preserve originals
