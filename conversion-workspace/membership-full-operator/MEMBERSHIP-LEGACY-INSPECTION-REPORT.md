# Serena Membership Legacy Inspection Report

Target:

- Serena Membership / Subscriptions / Patient Programmes Full Operator v1

Inspected files:

## `legacy\serena-skills\21-membership.js`

- Lines: 204
- Characters: 7650
- Triggers found: 4
- Functions found: 0
- Dependencies found: 2
- Membership terms found: 14
- Env/integration mentions: 3

Triggers:
- CREATE MEMBERSHIP:
- ENROL MEMBER:
- MEMBER STATUS:
- MEMBERSHIP PLANS

Functions:
- none detected

Membership terms:
- booking
- enrol
- enroll
- health
- member
- members
- membership
- patient
- payment
- plan
- plans
- renewal
- subscription
- woocommerce

Env/integration mentions:
- MEMBER
- MEMBERSHIP
- PATIENT

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\45-payflow.js`

- Lines: 77
- Characters: 2706
- Triggers found: 2
- Functions found: 1
- Dependencies found: 1
- Membership terms found: 12
- Env/integration mentions: 2

Triggers:
- PAYFLOW:
- SUBSCRIPTION:

Functions:
- parsePayload

Membership terms:
- member
- members
- membership
- order
- payfast
- payflow
- payment
- plan
- plans
- renewal
- revenue
- subscription

Env/integration mentions:
- PAYFLOW
- SUBSCRIPTION

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\10-payfast.js`

- Lines: 120
- Characters: 4830
- Triggers found: 2
- Functions found: 1
- Dependencies found: 2
- Membership terms found: 6
- Env/integration mentions: 6

Triggers:
- PAYMENT LINK:
- PAYMENT STATUS:

Functions:
- buildPayfastUrl

Membership terms:
- cancel
- docs
- order
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


## `legacy\serena-skills\09-finance.js`

- Lines: 171
- Characters: 6730
- Triggers found: 5
- Functions found: 2
- Dependencies found: 2
- Membership terms found: 4
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

Membership terms:
- invoice
- patient
- payfast
- payment

Env/integration mentions:
- PAYFAST_ENABLED

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\01-crm.js`

- Lines: 205
- Characters: 7663
- Triggers found: 3
- Functions found: 0
- Dependencies found: 2
- Membership terms found: 3
- Env/integration mentions: 2

Triggers:
- ADD PATIENT:
- GET PATIENT:
- UPDATE PATIENT:

Functions:
- none detected

Membership terms:
- crm
- health
- patient

Env/integration mentions:
- CRM
- PATIENT

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\25-compliance.js`

- Lines: 98
- Characters: 4160
- Triggers found: 4
- Functions found: 0
- Dependencies found: 1
- Membership terms found: 8
- Env/integration mentions: 0

Triggers:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Functions:
- none detected

Membership terms:
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
- Membership terms found: 10
- Env/integration mentions: 0

Triggers:
- KPI REPORT
- MORNING BRIEF
- WEEKLY REPORT

Functions:
- none detected

Membership terms:
- appointment
- booking
- member
- members
- membership
- patient
- plan
- report
- revenue
- woocommerce

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
- Membership terms found: 1
- Env/integration mentions: 2

Triggers:
- DRIVE FOLDER:
- DRIVE LIST:
- DRIVE SAVE:
- DRIVE UPLOAD:

Functions:
- none detected

Membership terms:
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
- Membership terms found: 2
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

Membership terms:
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


## `legacy\serena-skills\29-ecommerce.js`

- Lines: 152
- Characters: 6105
- Triggers found: 6
- Functions found: 5
- Dependencies found: 1
- Membership terms found: 4
- Env/integration mentions: 2

Triggers:
- POST
- WC ORDER:
- WC ORDERS
- WC PRODUCT:
- WC PRODUCTS
- WC REVENUE

Functions:
- base
- items
- wcGet
- wcPost
- wcUrl

Membership terms:
- cancel
- order
- revenue
- woocommerce

Env/integration mentions:
- WOOCOMMERCE_KEY
- WOOCOMMERCE_SECRET

Dependencies:
- ../helpers/logger


## Missing files

- legacy\serena-skills\20-bookings.js
- legacy\serena-skills\58-appointment-reminders.js
- legacy\serena-skills\77-ecommerce-ops.js

## Upgrade target

Membership must become a patient/client programme and subscription workflow operator, not merely a plan/status checker.

It must support member profiles, plans, enrollments, subscription records, payment handoff, accounting handoff, booking handoff, programme progress, follow-ups, Docs/Drive/Reporting handoff, audit, safety blocks, and future Hub widgets.