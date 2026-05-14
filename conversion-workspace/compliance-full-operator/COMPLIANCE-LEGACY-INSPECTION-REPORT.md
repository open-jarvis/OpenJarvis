# Serena Compliance Legacy Inspection Report

Target:

- Serena Compliance / Policy Guard Full Operator v1

Inspected files:

## `legacy\serena-skills\24-compliance-guard.js`

- Lines: 113
- Characters: 4932
- Triggers found: 1
- Functions found: 0
- Dependencies found: 1
- Policy terms found: 7
- Env/integration mentions: 3

Triggers:
- QUICK CHECK:

Functions:
- none detected

Policy terms:
- HPCSA
- POPIA
- advertising
- compliance
- health
- medical
- patient

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\25-compliance.js`

- Lines: 98
- Characters: 4160
- Triggers found: 4
- Functions found: 0
- Dependencies found: 1
- Policy terms found: 11
- Env/integration mentions: 4

Triggers:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Functions:
- none detected

Policy terms:
- HPCSA
- POPIA
- advertising
- compliance
- consent
- health
- lab
- medical
- patient
- privacy
- social media

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\23-telehealth.js`

- Lines: 59
- Characters: 2196
- Triggers found: 2
- Functions found: 2
- Dependencies found: 2
- Policy terms found: 4
- Env/integration mentions: 0

Triggers:
- CONSULT PREP:
- TELEHEALTH PREP:

Functions:
- generatePrep
- parsePayload

Policy terms:
- health
- lab
- patient
- telehealth

Dependencies:
- ../helpers/document-service
- ../helpers/logger


## `legacy\serena-skills\37-ocr.js`

- Lines: 148
- Characters: 5369
- Triggers found: 3
- Functions found: 2
- Dependencies found: 3
- Policy terms found: 2
- Env/integration mentions: 2

Triggers:
- EXTRACT TEXT:
- OCR:
- SCAN DOC:

Functions:
- ocrViaHuggingFace
- ocrViaMistral

Policy terms:
- lab
- medical

Dependencies:
- ../helpers/logger
- fs
- path


## `legacy\serena-skills\57-LabResultsInterpreter.js`

- Lines: 66
- Characters: 2852
- Triggers found: 3
- Functions found: 0
- Dependencies found: 1
- Policy terms found: 3
- Env/integration mentions: 0

Triggers:
- INTERPRET LAB:
- LAB RESULTS:
- READ LAB:

Functions:
- none detected

Policy terms:
- clinical
- lab
- patient

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\17-newsletter.js`

- Lines: 120
- Characters: 5433
- Triggers found: 3
- Functions found: 1
- Dependencies found: 2
- Policy terms found: 4
- Env/integration mentions: 1

Triggers:
- HEALTH NEWSLETTER:
- NEWSLETTER:
- WEEKLY NEWSLETTER

Functions:
- shouldSend

Policy terms:
- HPCSA
- health
- lab
- patient

Dependencies:
- ../helpers/logger
- nodemailer


## `legacy\serena-skills\19-email-marketing.js`

- Lines: 131
- Characters: 5140
- Triggers found: 2
- Functions found: 0
- Dependencies found: 2
- Policy terms found: 4
- Env/integration mentions: 0

Triggers:
- EMAIL CAMPAIGN:
- EMAIL DRAFT:

Functions:
- none detected

Policy terms:
- health
- lab
- medical
- patient

Dependencies:
- ../helpers/logger
- nodemailer


## `legacy\serena-skills\04-calendar.js`

- Lines: 183
- Characters: 6910
- Triggers found: 4
- Functions found: 1
- Dependencies found: 2
- Policy terms found: 2
- Env/integration mentions: 4

Triggers:
- BOOK SLOT:
- CANCEL APPOINTMENT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE

Functions:
- getCalendarClient

Policy terms:
- lab
- patient

Dependencies:
- ../helpers/logger
- googleapis


## `legacy\serena-skills\03-gdrive.js`

- Lines: 96
- Characters: 3508
- Triggers found: 4
- Functions found: 0
- Dependencies found: 2
- Policy terms found: 0
- Env/integration mentions: 3

Triggers:
- DRIVE FOLDER:
- DRIVE LIST:
- DRIVE SAVE:
- DRIVE UPLOAD:

Functions:
- none detected

Policy terms:
- none detected

Dependencies:
- ../helpers/google-drive
- ../helpers/logger


## `legacy\serena-skills\08-google-docs.js`

- Lines: 100
- Characters: 3259
- Triggers found: 2
- Functions found: 3
- Dependencies found: 2
- Policy terms found: 0
- Env/integration mentions: 5

Triggers:
- CREATE DOC:
- UPDATE DOC:

Functions:
- generateDocContent
- parsePayload
- replaceExisting

Policy terms:
- none detected

Dependencies:
- ../helpers/google-docs-service
- ../helpers/logger


## Missing files

- legacy\serena-skills\13-wordpress.js

## Upgrade target

Compliance must become a central Serena guardrail, not merely a text checker.

It must inspect requests, classify data sensitivity, assign risk levels, warn, block dangerous actions, require approval when needed, maintain a local policy library, produce audit reports, and later expose Hub widget metadata.