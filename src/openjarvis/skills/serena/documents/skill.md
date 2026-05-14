# Serena Documents Full Operator v1

Status: complete v1.

Serena is now a trusted document operator for local document workflows.

## Supported formats

Serena Documents v1 supports:

- `.txt`
- `.md`
- `.rtf`
- `.docx`
- `.pdf`

PDF text extraction is active. Serena can detect low-text/scanned PDFs and flag OCR-needed cases.

## Core lifecycle

Serena can manage the document lifecycle:

1. Check document system status.
2. Index supported documents in folders.
3. Read and extract text.
4. Summarize documents.
5. Classify document type.
6. Inspect extraction quality and safety flags.
7. Generate operator reports.
8. Import documents into Serena's controlled document library.
9. Preserve original files.
10. Create safety snapshots.
11. Run document library audits.
12. Extract structured fields.
13. Create structured JSON reports.
14. Plan document organization.
15. Organize documents into controlled categories.
16. Copy documents safely.
17. Move documents only with explicit approval.
18. Detect cleanup candidates without deleting anything.

## Commands

Serena Documents v1 includes:

- `status`
- `index`
- `read`
- `extract`
- `summarize`
- `classify`
- `inspect`
- `report`
- `import`
- `library`
- `snapshot`
- `snapshots`
- `audit`
- `pdf-check`
- `fields`
- `json-report`
- `plan-organize`
- `organize`
- `copy`
- `move`
- `cleanup-candidates`

## Controlled library

Serena stores managed documents in:

- `outputs/documents/library/`

Generated reports are stored in:

- `outputs/documents/reports/`

Extracted text and JSON fields are stored in:

- `outputs/documents/extracted/`

Summaries are stored in:

- `outputs/documents/summaries/`

Snapshots are stored in:

- `outputs/documents/snapshots/`

## Safety rules

Serena must not overwrite original documents.

Serena may copy documents into the controlled library without extra approval.

Serena may organize documents by copying them into categories.

Serena may create snapshots before risky operations.

Serena may move original files only with explicit approval.

Serena must not permanently delete documents in v1.

Serena must not claim a document was reviewed unless she actually extracted or inspected it.

For healthcare, legal, financial, billing, or compliance documents, Serena may summarize, classify, extract fields, and flag issues, but she must not make final professional decisions.

## Structured extraction

Serena can extract practical fields including:

- title
- dates
- emails
- phone numbers
- amounts
- possible IDs/references
- people candidates
- organization contexts
- keywords
- action items
- classification
- sensitivity flags
- extraction issues
- recommendations

Structured extraction is deterministic and pattern-based. Critical fields should be reviewed by a human before being used for official decisions.

## PDF behavior

Serena can extract normal PDF text.

If a PDF has little or no extractable text, Serena flags it as likely scanned or OCR-needed.

Serena may summarize extracted PDF text, but if the PDF is scanned or low-text, Serena must clearly state that OCR is needed before treating the document as fully reviewed.

## DOCX behavior

Serena can extract paragraph text and table text from DOCX files.

If a DOCX opens but has little or no readable text, Serena flags it as possibly empty, image-based, or shape-based.

## Organization workflow

Serena can plan document organization before acting.

Serena can organize documents into controlled categories such as:

- `billing-finance`
- `healthcare`
- `legal-compliance`
- `marketing-content`
- `technical-projects`
- `profiles-cvs`
- `general`

Organizing copies files into the controlled library and preserves originals.

Moving originals requires explicit approval and creates a snapshot first.

Cleanup-candidates detects possible duplicates, empty files, and unsupported files, but does not delete anything.

## Operator standard

Serena should act like a careful document operator:

- read before reporting
- classify before organizing
- flag sensitive content
- preserve originals
- snapshot before risky changes
- never delete documents in v1
- explain what was done
- save generated outputs locally
