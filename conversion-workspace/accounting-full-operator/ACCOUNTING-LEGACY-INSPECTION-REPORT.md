# Serena Accounting Legacy Inspection Report

Target:

- Serena Accounting / Payments / Payroll / Tax Full Operator v1

Inspected files:

## `legacy\serena-skills\09-finance.js`

- Lines: 171
- Characters: 6730
- Triggers found: 5
- Functions found: 2
- Dependencies found: 2
- Accounting terms found: 9
- Env/integration mentions: 5

Triggers:
- GENERATE INVOICE:
- INVOICE SUMMARY
- PAID
- PENDING
- RECORD PAYMENT:

Functions:
- totalAmount
- vatAmount

Accounting terms:
- finance
- invoice
- invoices
- patient
- payfast
- payment
- payments
- summary
- vat

Env/integration mentions:
- FINANCE
- INVOICE
- PAYFAST_ENABLED
- PAYMENT
- VAT

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\10-payfast.js`

- Lines: 120
- Characters: 4830
- Triggers found: 2
- Functions found: 1
- Dependencies found: 2
- Accounting terms found: 5
- Env/integration mentions: 7

Triggers:
- PAYMENT LINK:
- PAYMENT STATUS:

Functions:
- buildPayfastUrl

Accounting terms:
- order
- patient
- payfast
- payment
- payments

Env/integration mentions:
- PAYFAST
- PAYFAST_ENABLED
- PAYFAST_MERCHANT_ID
- PAYFAST_MERCHANT_KEY
- PAYFAST_PASSPHRASE
- PAYFAST_SANDBOX
- PAYMENT

Dependencies:
- ../helpers/logger
- crypto


## `legacy\serena-skills\45-payflow.js`

- Lines: 77
- Characters: 2706
- Triggers found: 2
- Functions found: 1
- Dependencies found: 1
- Accounting terms found: 7
- Env/integration mentions: 1

Triggers:
- PAYFLOW:
- SUBSCRIPTION:

Functions:
- parsePayload

Accounting terms:
- membership
- order
- payfast
- payflow
- payment
- revenue
- subscription

Env/integration mentions:
- PAYMENT

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\21-membership.js`

- Lines: 204
- Characters: 7650
- Triggers found: 4
- Functions found: 0
- Dependencies found: 2
- Accounting terms found: 6
- Env/integration mentions: 1

Triggers:
- CREATE MEMBERSHIP:
- ENROL MEMBER:
- MEMBER STATUS:
- MEMBERSHIP PLANS

Functions:
- none detected

Accounting terms:
- booking
- membership
- patient
- payment
- subscription
- woocommerce

Env/integration mentions:
- PAYMENT

Dependencies:
- ../helpers/logger
- ../helpers/structured-output


## `legacy\serena-skills\29-ecommerce.js`

- Lines: 152
- Characters: 6105
- Triggers found: 6
- Functions found: 5
- Dependencies found: 1
- Accounting terms found: 6
- Env/integration mentions: 3

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

Accounting terms:
- bill
- order
- refund
- revenue
- summary
- woocommerce

Env/integration mentions:
- ECOMMERCE
- WOOCOMMERCE_KEY
- WOOCOMMERCE_SECRET

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\02-reporting.js`

- Lines: 105
- Characters: 3818
- Triggers found: 3
- Functions found: 0
- Dependencies found: 1
- Accounting terms found: 7
- Env/integration mentions: 0

Triggers:
- KPI REPORT
- MORNING BRIEF
- WEEKLY REPORT

Functions:
- none detected

Accounting terms:
- booking
- membership
- patient
- report
- revenue
- summary
- woocommerce

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/logger


## `legacy\serena-skills\12-analytics.js`

- Lines: 134
- Characters: 5395
- Triggers found: 3
- Functions found: 2
- Dependencies found: 2
- Accounting terms found: 10
- Env/integration mentions: 2

Triggers:
- ANALYTICS REPORT
- N/A
- SITE ANALYTICS

Functions:
- fetchTelemetrySummary
- fetchWooMetrics

Accounting terms:
- booking
- invoice
- invoices
- membership
- order
- patient
- report
- revenue
- summary
- woocommerce

Env/integration mentions:
- WOOCOMMERCE_KEY
- WOOCOMMERCE_SECRET

Dependencies:
- ../helpers/logger
- ../helpers/revenue-engine


## `legacy\serena-skills\25-compliance.js`

- Lines: 98
- Characters: 4160
- Triggers found: 4
- Functions found: 0
- Dependencies found: 1
- Accounting terms found: 2
- Env/integration mentions: 0

Triggers:
- ANALYSE CONTENT:
- COMPLIANCE CHECK:
- FULL COMPLIANCE:
- HPCSA CHECK:

Functions:
- none detected

Accounting terms:
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
- Accounting terms found: 0
- Env/integration mentions: 0

Triggers:
- DRIVE FOLDER:
- DRIVE LIST:
- DRIVE SAVE:
- DRIVE UPLOAD:

Functions:
- none detected

Accounting terms:
- none detected

Env/integration mentions:
- none detected

Dependencies:
- ../helpers/google-drive
- ../helpers/logger


## `legacy\serena-skills\08-google-docs.js`

- Lines: 100
- Characters: 3259
- Triggers found: 5
- Functions found: 3
- Dependencies found: 2
- Accounting terms found: 1
- Env/integration mentions: 2

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

Accounting terms:
- client

Env/integration mentions:
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN

Dependencies:
- ../helpers/google-docs-service
- ../helpers/logger


## `legacy\serena-skills\37-ocr.js`

- Lines: 148
- Characters: 5369
- Triggers found: 7
- Functions found: 2
- Dependencies found: 3
- Accounting terms found: 2
- Env/integration mentions: 3

Triggers:
- EXTRACT TEXT:
- HUGGINGFACE_API_KEY
- MISTRAL_API_KEY
- MODEL_LOADING
- OCR:
- POST
- SCAN DOC:

Functions:
- ocrViaHuggingFace
- ocrViaMistral

Accounting terms:
- report
- vat

Env/integration mentions:
- HUGGINGFACE_API_KEY
- MISTRAL_API_KEY
- TELEGRAM_TOKEN

Dependencies:
- ../helpers/logger
- fs
- path


## Missing files

- legacy\serena-skills\20-bookings.js
- legacy\serena-skills\58-appointment-reminders.js
- legacy\serena-skills\77-ecommerce-ops.js

## Upgrade target

Accounting must become a business money-control operator, not a small payment checker.

It must support Xero readiness, PayFast payment intake, invoices, payments, expenses, receipts, reconciliation, payroll prep, VAT/tax prep, reports, audit, safety blocks, and future Hub widgets.