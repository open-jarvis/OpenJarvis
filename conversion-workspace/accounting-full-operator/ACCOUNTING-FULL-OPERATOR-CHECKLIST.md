# Serena Accounting / Payments / Payroll / Tax Full Operator v1

Legacy sources:

- `legacy/serena-skills/09-finance.js`
- `legacy/serena-skills/10-payfast.js`
- `legacy/serena-skills/45-payflow.js`

Related skills to inspect:

- `legacy/serena-skills/20-bookings.js`
- `legacy/serena-skills/58-appointment-reminders.js`
- `legacy/serena-skills/21-membership.js`
- `legacy/serena-skills/29-ecommerce.js`
- `legacy/serena-skills/77-ecommerce-ops.js`
- `legacy/serena-skills/02-reporting.js`
- `legacy/serena-skills/12-analytics.js`
- `legacy/serena-skills/25-compliance.js`
- `legacy/serena-skills/03-gdrive.js`
- `legacy/serena-skills/08-google-docs.js`
- `legacy/serena-skills/37-ocr.js`

Goal:

Turn Serena Finance, PayFast, and Payflow into one complete accounting controller.

Primary role:

Serena should operate as a professional accounting, payments, bookkeeping, payroll-prep, VAT/tax-prep, reconciliation, and financial reporting operator.

Accounting source of truth target:

- Xero should become the accounting ledger/source of truth.
- PayFast should become a payment-event source.
- OCR/Docs/Drive should provide receipt/evidence intake and storage.
- Reporting should produce finance reports.
- Compliance should guard sensitive, tax, payroll, patient/client, and financial workflows.
- Future Serena Hub should expose accounting widgets.

Target capability:

inspect -> plan -> capture payment -> match invoice -> record payment -> capture receipt -> classify transaction -> reconcile -> report -> audit -> approval-gated handoff

Required v1 commands:

Layer 1 — Foundation:
- accounting status
- accounting env-check
- accounting plan
- accounting source-list
- accounting source-info

Layer 2 — Xero readiness:
- accounting xero-env-check
- accounting xero-connect-check
- accounting xero-tenant-list
- accounting xero-plan
- accounting xero-chart-plan

Layer 3 — PayFast intake:
- accounting payfast-env-check
- accounting payfast-plan
- accounting payfast-verify-itn
- accounting payfast-payment-record
- accounting payfast-reconcile-plan

Layer 4 — Invoices and payments:
- accounting invoice-plan
- accounting create-invoice
- accounting record-payment
- accounting payment-match
- accounting unpaid-invoices
- accounting payment-summary

Layer 5 — Expenses and receipts:
- accounting expense-record
- accounting receipt-capture
- accounting supplier-bill-plan
- accounting document-to-expense
- accounting ocr-receipt-handoff

Layer 6 — Books and reconciliation:
- accounting bank-reconcile-plan
- accounting transaction-classify
- accounting exceptions
- accounting month-end-checklist
- accounting books-summary

Layer 7 — Payroll:
- accounting payroll-plan
- accounting payroll-summary
- accounting payroll-checklist
- accounting blocked-payroll-submit

Layer 8 — VAT/tax:
- accounting vat-plan
- accounting vat-summary
- accounting tax-checklist
- accounting blocked-tax-submit

Layer 9 — Reports:
- accounting daily-money-report
- accounting weekly-finance-report
- accounting monthly-management-report
- accounting cashflow-summary
- accounting debtor-creditor-summary
- accounting profitability-summary

Layer 10 — Audit and safety:
- accounting audit
- accounting blocked-bank-change
- accounting blocked-tax-filing
- accounting blocked-payroll-submit
- accounting blocked-delete-ledger
- accounting blocked-secret-exposure

Safety model:

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

Blocked in v1 unless future explicit approval layer exists:
- exposing Xero/PayFast/secrets
- changing bank account details
- submitting tax/VAT returns
- submitting payroll
- deleting ledger records
- voiding invoices
- refunding payments
- modifying chart of accounts
- creating manual journals
- destructive/bulk accounting changes
- final accounting/tax/legal advice

Operator standard:

Serena should not merely record payments.

Serena should act like an accounting controller:
- collect evidence
- classify money movement
- match payment to invoice/client/order
- identify exceptions
- preserve audit trails
- prepare Xero/PayFast actions safely
- create reports
- block dangerous actions
- require owner/accountant approval for high-risk steps

Hub Adapter Layer:

Accounting must be future Serena Hub compatible.

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

Status target:

`complete_v1_hub_adapter_pending`
