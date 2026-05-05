# Serena Accounting / Payments / Payroll / Tax Full Operator v1

Status: complete_v1_hub_adapter_pending

Legacy sources:
- legacy/serena-skills/09-finance.js
- legacy/serena-skills/10-payfast.js
- legacy/serena-skills/45-payflow.js

Related inspected skills:
- legacy/serena-skills/20-bookings.js
- legacy/serena-skills/58-appointment-reminders.js
- legacy/serena-skills/21-membership.js
- legacy/serena-skills/29-ecommerce.js
- legacy/serena-skills/77-ecommerce-ops.js
- legacy/serena-skills/02-reporting.js
- legacy/serena-skills/12-analytics.js
- legacy/serena-skills/25-compliance.js
- legacy/serena-skills/03-gdrive.js
- legacy/serena-skills/08-google-docs.js
- legacy/serena-skills/37-ocr.js

Legacy triggers:
- GENERATE INVOICE:
- INVOICE SUMMARY
- RECORD PAYMENT:
- PAYMENT LINK:
- PAYMENT STATUS:
- PAYFLOW:
- SUBSCRIPTION:

Purpose:
Serena Accounting is the money-control operator for business finance, invoices, payments, PayFast intake, Xero readiness, expenses, receipts, reconciliation, payroll preparation, VAT/tax preparation, financial reporting, audit, and safety blocks.

Accounting source-of-truth target:
- Xero is the future accounting ledger/source of truth.
- PayFast is a payment-event source.
- Serena local accounting records are the current v1 local ledger/evidence layer.
- OCR, Drive, Docs, Reporting, Analytics, and Compliance are supporting systems.

Foundation commands:
- status
- env-check
- plan
- source-list
- source-info

Xero readiness commands:
- xero-env-check
- xero-connect-check
- xero-tenant-list
- xero-plan
- xero-chart-plan

PayFast intake commands:
- payfast-env-check
- payfast-plan
- payfast-verify-itn
- payfast-payment-record
- payfast-reconcile-plan

Invoice and payment commands:
- invoice-plan
- create-invoice
- record-payment
- payment-match
- unpaid-invoices
- payment-summary

Expense and receipt commands:
- expense-record
- receipt-capture
- supplier-bill-plan
- document-to-expense
- ocr-receipt-handoff

Books and reconciliation commands:
- bank-reconcile-plan
- transaction-classify
- exceptions
- month-end-checklist
- books-summary

Payroll commands:
- payroll-plan
- payroll-summary
- payroll-checklist
- blocked-payroll-submit

VAT/tax commands:
- vat-plan
- vat-summary
- tax-checklist
- blocked-tax-submit

Financial reporting commands:
- daily-money-report
- weekly-finance-report
- monthly-management-report
- cashflow-summary
- debtor-creditor-summary
- profitability-summary

Audit and final safety commands:
- audit
- blocked-bank-change
- blocked-tax-filing
- blocked-payroll-submit
- blocked-delete-ledger
- blocked-secret-exposure

Current v1 behavior:
- External APIs are not called.
- Live Xero writes are not performed.
- PayFast live payment actions are not performed.
- Local records are created as JSON evidence.
- Financial reports can be created locally as JSON and Markdown.
- Payroll, VAT, and tax workflows are preparation-only.
- Dangerous accounting actions are blocked.

Required future live credentials:
Xero:
- XERO_CLIENT_ID
- XERO_CLIENT_SECRET
- XERO_REFRESH_TOKEN
- XERO_TENANT_ID

PayFast:
- PAYFAST_MERCHANT_ID
- PAYFAST_MERCHANT_KEY
- PAYFAST_PASSPHRASE
- PAYFAST_SANDBOX

Google evidence systems:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_REFRESH_TOKEN
- GDRIVE_ROOT_FOLDER_ID

Allowed:
- inspect finance/payment/accounting environment
- create local accounting plans
- create local invoice/payment/expense/receipt records
- create local accounting snapshots
- create finance reports
- prepare Xero/PayFast handoff plans
- reconcile and match using local evidence
- prepare VAT/tax/payroll checklists
- report exactly what changed

Guarded:
- creating live Xero objects
- recording live payments
- invoice changes
- bank reconciliation changes
- payroll calculations
- VAT/tax summaries
- revenue and patient/client-linked reports
- external exports
- integrations involving PayFast/Xero credentials

Blocked:
- exposing Xero/PayFast/API secrets
- changing bank account details
- submitting tax/VAT/SARS/eFiling returns
- submitting payroll
- deleting ledger records
- voiding invoices
- refunding payments
- modifying chart of accounts
- creating manual journals
- destructive or bulk accounting changes
- final accounting/tax/legal advice

Operator standard:
Serena should act like an accounting controller:
- collect evidence
- classify money movement
- match payments to invoices/clients/orders
- identify exceptions
- preserve audit trails
- prepare Xero/PayFast actions safely
- create reports
- block dangerous actions
- require owner/accountant approval for high-risk steps

Hub Adapter Layer:
Accounting is future Serena Hub compatible.

Future widgets:
- accounting_overview_widget
- payments_widget
- invoices_widget
- expenses_widget
- receipts_widget
- reconciliation_widget
- payroll_widget
- tax_widget
- cashflow_widget
- exceptions_widget
- accounting_approval_widget

Future events:
- accounting_snapshot_created
- payment_recorded
- invoice_created
- payment_matched
- expense_recorded
- receipt_captured
- reconciliation_exception_created
- accounting_report_created
- accounting_action_blocked

Future operator state:
- current_business_id
- current_accounting_source
- current_xero_tenant_id
- current_payment_provider
- current_invoice_id
- current_payment_id
- current_contact_id
- current_report_path
- current_required_approval

Completion notes:
Accounting Full Operator v1 is complete and safety-tested. Xero and PayFast live credentials remain future configuration items. Hub Adapter remains pending until Serena Hub dashboard/event bus exists.
