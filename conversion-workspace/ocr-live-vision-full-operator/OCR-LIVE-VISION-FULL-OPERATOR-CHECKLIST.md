# Serena OCR / Live Vision Full Operator v1

Legacy source:

- `legacy/serena-skills/37-ocr.js`

Goal:

Transform Serena OCR into a full OCR, camera capture, and controlled live vision operator.

Primary role:

Serena should be able to see, capture, inspect, extract text, classify visible content, and hand off extracted information into Documents, Google Docs, Google Drive, and Files workflows.

Target capability:

still image -> document OCR -> webcam capture -> controlled live vision -> best-frame extraction -> Google Docs/Drive handoff -> reports

Level 1 capability:

- inspect image files
- extract text from image files
- extract text from document scans where possible
- assess readability
- classify visible content
- describe captured image content
- save artifacts and reports

Level 2 capability:

- open webcam only on explicit command
- start controlled live vision session
- capture frames at limited intervals
- watch for documents/text/scenes/objects
- save useful frames
- extract text from best frames
- stop immediately on command
- auto-stop after configured max duration
- write live session report

Required v1 commands:

Foundation:
- ocr status
- ocr engines
- ocr camera-status
- ocr plan
- ocr safety-policy

Still image OCR:
- ocr inspect-image
- ocr extract-image
- ocr readability
- ocr extract-pdf

Webcam still capture:
- ocr cameras
- ocr capture
- ocr capture-doc
- ocr describe-capture

Live vision:
- ocr live-start
- ocr live-status
- ocr live-stop
- ocr live-snapshot
- ocr live-report
- ocr live-watch-doc
- ocr live-watch-text
- ocr best-frame
- ocr extract-live-text

Handoff:
- ocr to-google-doc
- ocr to-drive
- ocr to-document
- ocr document-flow

Safety/audit:
- ocr artifacts
- ocr audit
- ocr blocked-hidden-watch
- ocr blocked-delete

Safety model:

Allowed:
- capture on explicit command
- analyze still images
- use webcam only during active commanded session
- extract visible text
- classify visible document/object/scene type
- save captures and extracted text
- create reports
- hand off to Google Docs / Google Drive / Documents / Files

Blocked:
- silent camera use
- hidden/background watching
- always-on camera
- face identity recognition
- biometric recognition
- audio recording
- uploading captures without reporting
- deleting captures automatically
- running live vision after stop command

Operator standard:

Serena should not merely OCR files.

Serena should act like a visual document/camera operator:
inspect, capture, assess readability, extract text, classify, save artifacts, create usable documents, hand off to Drive/Docs/Documents, and report exactly what happened.
