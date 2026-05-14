# Serena Files Full Operator v1

Legacy source:

- `legacy\serena-skills\63-files.js`

Initial inspection:

- Lines: 99
- Characters: 3900
- Functions found: 0
- Dependencies found: 1

Target:

Serena Files Full Operator v1 should let Serena operate local files safely and professionally.

Required lifecycle:

1. Check file operator status.
2. Index folders.
3. Search files by filename and extension.
4. Search readable text content.
5. Read safe text files.
6. Create folders.
7. Copy files safely.
8. Move files only with explicit approval.
9. Snapshot files before risky changes.
10. List snapshots.
11. Audit folders.
12. Detect duplicate, empty, large, unsupported, and cleanup-candidate files.
13. Plan backups.
14. Create local controlled backups.
15. Protect originals.
16. Never permanently delete files in v1.

Safety rules:

- Copy is allowed.
- Move requires explicit approval.
- Delete/permanent cleanup is excluded from v1.
- Snapshot before risky operations.
- Do not overwrite existing files; create unique target names.
- Do not modify original files unless explicitly approved.
- Generated outputs go under `outputs/files/`.

Operator standard:

Serena should act like a careful local file operator:
- inspect first
- plan before acting
- snapshot before risky operations
- copy safely
- move only with approval
- report exactly what changed
- never delete in v1

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
