# Serena OCR / Live Vision Legacy Inspection Report

Legacy source:

- `legacy\serena-skills\37-ocr.js`

Initial inspection:

- Lines: 148
- Characters: 5369
- Functions found: 2
- Dependencies found: 3
- Triggers found: 3
- Env variable names mentioned: 4

Triggers:

- SCAN DOC:
- OCR:
- EXTRACT TEXT:

Environment / integration mentions:

- `HF`
- `HUGGINGFACE_API_KEY`
- `MISTRAL_API_KEY`
- `OCR`

Target:

Serena OCR / Live Vision Full Operator v1 should let Serena inspect images, extract visible text, use webcam capture on explicit command, run controlled live vision sessions, hand off extracted information to Google Docs / Google Drive / Documents / Files, and block silent or hidden camera behavior.

Required lifecycle:

1. Check OCR / vision operator status.
2. Check available OCR / image / camera engines.
3. Inspect legacy OCR triggers.
4. List and check cameras.
5. Capture still image from webcam on explicit command.
6. Inspect image quality and readability.
7. Extract text from image or PDF where possible.
8. Start controlled live vision only on explicit command.
9. Track live session state.
10. Capture frames at limited intervals.
11. Stop immediately on command.
12. Save artifacts and reports.
13. Hand off extracted text to Google Docs / Drive / Documents.
14. Block hidden watching, always-on camera, biometric recognition, and delete.

Operator standard:

Serena should not merely OCR files.
Serena should act like a visual document/camera operator: inspect, capture, assess readability, extract text, classify, save artifacts, create usable documents, hand off to Drive/Docs/Documents, and report exactly what happened.
