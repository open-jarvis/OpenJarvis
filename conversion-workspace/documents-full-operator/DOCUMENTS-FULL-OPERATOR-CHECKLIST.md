# Serena Documents Full Operator v1

Legacy source:

- `legacy\serena-skills\67-documents.js`

Initial inspection:

- Lines: 145
- Characters: 5333
- Functions found: 4
- Dependencies found: 2

Target:

Serena Documents Full Operator v1 should let Serena work with documents professionally.

Required lifecycle:

1. Locate documents.
2. Read supported document types.
3. Extract text safely.
4. Summarize content.
5. Classify document purpose/type.
6. Inspect document quality and completeness.
7. Extract important fields.
8. Create structured reports.
9. Save outputs locally.
10. Protect original files from accidental overwrite.
11. Audit document folders.
12. Prepare future Google Drive support after the Google Drive skill is converted.

Supported starting formats:

- `.txt`
- `.md`
- `.rtf`
- `.pdf`
- `.docx`

Future formats:

- `.xlsx`
- `.csv`
- images/OCR
- Google Docs
- Google Drive files

Safety rules:

- Do not overwrite original documents.
- Store generated outputs in `outputs/documents/`.
- Use snapshots before modifying or moving files.
- Ask approval before deleting documents.
- Do not claim a document was reviewed unless Serena actually read/extracted it.
- For medical/legal/financial documents, provide summaries and flags, not final professional decisions.

Operator standard:

Serena should not just summarize documents.
Serena should inspect, classify, extract, organize, and report like a real document operator.
