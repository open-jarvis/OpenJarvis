# Serena Bookings Legacy Inspection Report

Target:

- Serena Bookings / Appointments / Reminders Full Operator v1

Inspected files:

## `legacy\serena-skills\04-calendar.js`

- Lines: 183
- Characters: 6910
- Triggers found: 4
- Functions found: 1
- Dependencies found: 2
- Booking terms found: 11
- Env/integration mentions: 5

Triggers:
- BOOK SLOT:
- CANCEL APPOINTMENT:
- CHECK AVAILABILITY:
- TODAY SCHEDULE

Functions:
- getCalendarClient

Booking terms:
- appointment
- appointments
- availability
- calendar
- cancel
- client
- consultation
- patient
- reminder
- schedule
- slot

Env/integration mentions:
- BOOK
- CALENDAR
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN

Dependencies:
- ../helpers/logger
- googleapis


## `legacy\serena-skills\25-compliance.js`

- Lines: 98
- Characters: 4160
- Triggers found: 4
- Functions found: 0
- Dependencies found: 1
- Booking terms found: 8
- Env/integration mentions: 0

Triggers:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Functions:
- none detected

Booking terms:
- compliance
- consent
- health
- hpcsa
- patient
- popia
- privacy
- report

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\02-reporting.js`

- Lines: 105
- Characters: 3818
- Triggers found: 3
- Functions found: 0
- Dependencies found: 1
- Booking terms found: 8
- Env/integration mentions: 0

Triggers:
- KPI REPORT
- MORNING BRIEF
- WEEKLY REPORT

Functions:
- none detected

Booking terms:
- appointment
- appointments
- booking
- bookings
- calendar
- membership
- patient
- report

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\03-gdrive.js`

- Lines: 96
- Characters: 3508
- Triggers found: 4
- Functions found: 0
- Dependencies found: 2
- Booking terms found: 1
- Env/integration mentions: 2

Triggers:
- DRIVE FOLDER:
- DRIVE LIST:
- DRIVE SAVE:
- DRIVE UPLOAD:

Functions:
- none detected

Booking terms:
- drive

Env/integration mentions:
- GDRIVE
- GDRIVE_ROOT_FOLDER_ID

Dependencies:
- ../helpers/google-drive
- ../helpers/logger


## `legacy\serena-skills\08-google-docs.js`

- Lines: 100
- Characters: 3259
- Triggers found: 5
- Functions found: 3
- Dependencies found: 2
- Booking terms found: 2
- Env/integration mentions: 5

Triggers:
- CREATE DOC:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- UPDATE DOC:

Functions:
- generateDocContent
- parsePayload
- replaceExisting

Booking terms:
- client
- docs

Env/integration mentions:
- DOCS
- GOOGLE
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN

Dependencies:
- ../helpers/google-docs-service
- ../helpers/logger


## `legacy\serena-skills\01-crm.js`

- Lines: 205
- Characters: 7663
- Triggers found: 3
- Functions found: 0
- Dependencies found: 2
- Booking terms found: 3
- Env/integration mentions: 2

Triggers:
- ADD PATIENT:
- GET PATIENT:
- UPDATE PATIENT:

Functions:
- none detected

Booking terms:
- crm
- health
- patient

Env/integration mentions:
- CRM
- PATIENT

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\09-finance.js`

- Lines: 171
- Characters: 6730
- Triggers found: 5
- Functions found: 2
- Dependencies found: 2
- Booking terms found: 5
- Env/integration mentions: 1

Triggers:
- GENERATE INVOICE:
- INVOICE SUMMARY
- PAID
- PENDING
- RECORD PAYMENT:

Functions:
- totalAmount
- vatAmount

Booking terms:
- consultation
- invoice
- patient
- payfast
- payment

Env/integration mentions:
- PAYFAST_ENABLED

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\10-payfast.js`

- Lines: 120
- Characters: 4830
- Triggers found: 2
- Functions found: 1
- Dependencies found: 2
- Booking terms found: 6
- Env/integration mentions: 6

Triggers:
- PAYMENT LINK:
- PAYMENT STATUS:

Functions:
- buildPayfastUrl

Booking terms:
- cancel
- consultation
- docs
- patient
- payfast
- payment

Env/integration mentions:
- PAYFAST
- PAYFAST_ENABLED
- PAYFAST_MERCHANT_ID
- PAYFAST_MERCHANT_KEY
- PAYFAST_PASSPHRASE
- PAYFAST_SANDBOX

Dependencies:
- ../helpers/logger
- crypto


## `legacy\serena-skills\45-payflow.js`

- Lines: 77
- Characters: 2706
- Triggers found: 2
- Functions found: 1
- Dependencies found: 1
- Booking terms found: 3
- Env/integration mentions: 0

Triggers:
- PAYFLOW:
- SUBSCRIPTION:

Functions:
- parsePayload

Booking terms:
- membership
- payfast
- payment

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger


## Missing files

- legacy\serena-skills\20-bookings.js
- legacy\serena-skills\58-appointment-reminders.js

## Upgrade target

Bookings must become a practice appointment workflow operator, not merely a calendar event creator.

It must support booking requests, local booking records, reschedules, cancellations, reminders, no-show risk, follow-ups, Calendar handoff, Docs/Drive/Reporting handoff, audit, safety blocks, and future Hub widgets.