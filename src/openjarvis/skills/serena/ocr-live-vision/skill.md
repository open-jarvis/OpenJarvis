# Serena OCR / Live Vision Full Operator v1

Status: complete_v1

Legacy source:
- legacy/serena-skills/37-ocr.js

Legacy triggers:
- SCAN DOC:
- OCR:
- EXTRACT TEXT:

Purpose:
Serena OCR / Live Vision is the visual document intake, OCR, webcam capture, controlled live vision, and handoff skill.

Core commands:
- status
- engines
- camera-status
- plan
- safety-policy
- inspect-image
- readability
- extract-image
- extract-pdf
- cameras
- capture
- capture-doc
- describe-capture
- live-start
- live-status
- live-stop
- live-snapshot
- live-report
- live-watch-doc
- live-watch-text
- best-frame
- extract-live-text
- to-document
- to-drive
- to-google-doc
- document-flow
- artifacts
- audit
- blocked-hidden-watch
- blocked-delete

Level 1:
Serena can inspect images, assess readability, extract OCR text, extract embedded PDF text, save extracted text, create local reports, and hand off OCR text to local documents, Google Drive, and Google Docs.

Level 2:
Serena can run controlled live vision sessions with explicit approval, bounded session duration, local session state, live snapshots, live-watch document/text commands, best-frame selection, extract-live-text, and live-stop.

Plug-and-play setup for Dr Piet's PC:
1. Install OCR dependencies.
2. Plug in webcam.
3. Allow Windows camera permissions.
4. Run:
   uv run serena ocr engines
   uv run serena ocr cameras --max-indexes 8
   uv run serena ocr camera-status --max-indexes 8

Safety:
- Webcam is closed/off by default.
- Webcam opens only on explicit command.
- live-start requires --approved.
- Hidden/background watching is blocked.
- Always-on camera use is blocked.
- Audio recording is blocked in OCR v1.
- Face identity recognition is blocked.
- Biometric recognition is blocked.
- OCR artifact delete/trash/permanent delete is blocked in v1.

Handoff:
OCR can create local Markdown handoff files, upload OCR output to Google Drive, create Google Docs from OCR text, and run full document-flow.

Operator standard:
Serena must inspect, capture, assess readability, extract text, preserve artifacts, hand off to Docs/Drive, report exactly what happened, keep webcam off unless explicitly commanded, and block hidden/always-on watching.
