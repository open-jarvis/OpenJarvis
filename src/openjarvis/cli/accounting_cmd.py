
"""Serena Accounting / Payments / Payroll / Tax Full Operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_accounting import (
    SerenaAccountingEnvCheckTool,
    SerenaAccountingPlanTool,
    SerenaAccountingSourceInfoTool,
    SerenaAccountingSourceListTool,
    SerenaAccountingStatusTool,
    SerenaAccountingBlockedPayrollSubmitTool,
    SerenaAccountingPayrollChecklistTool,
    SerenaAccountingPayrollSummaryTool,
    SerenaAccountingPayrollPlanTool,
    SerenaAccountingBooksSummaryTool,
    SerenaAccountingMonthEndChecklistTool,
    SerenaAccountingExceptionsTool,
    SerenaAccountingTransactionClassifyTool,
    SerenaAccountingBankReconcilePlanTool,
    SerenaAccountingOCRReceiptHandoffTool,
    SerenaAccountingDocumentToExpenseTool,
    SerenaAccountingSupplierBillPlanTool,
    SerenaAccountingReceiptCaptureTool,
    SerenaAccountingExpenseRecordTool,
    SerenaAccountingPaymentSummaryTool,
    SerenaAccountingUnpaidInvoicesTool,
    SerenaAccountingPaymentMatchTool,
    SerenaAccountingRecordPaymentTool,
    SerenaAccountingCreateInvoiceTool,
    SerenaAccountingInvoicePlanTool,
    SerenaAccountingPayFastReconcilePlanTool,
    SerenaAccountingPayFastPaymentRecordTool,
    SerenaAccountingPayFastVerifyITNTool,
    SerenaAccountingPayFastPlanTool,
    SerenaAccountingPayFastEnvCheckTool,
    SerenaAccountingXeroChartPlanTool,
    SerenaAccountingXeroPlanTool,
    SerenaAccountingXeroTenantListTool,
    SerenaAccountingXeroConnectCheckTool,
    SerenaAccountingXeroEnvCheckTool,
)


@click.group()
def accounting() -> None:
    """Native Serena Accounting / Payments / Payroll / Tax operator tools."""


@accounting.command("status")
def status() -> None:
    """Show Accounting operator status."""
    console = Console()
    result = SerenaAccountingStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("env-check")
def env_check() -> None:
    """Check accounting/payment environment without exposing secrets."""
    console = Console()
    result = SerenaAccountingEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("source-list")
def source_list() -> None:
    """List registered accounting/payment sources."""
    console = Console()
    result = SerenaAccountingSourceListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("source-info")
@click.option("--source", required=True, help="Source ID, e.g. xero, payfast, local-ledger.")
def source_info(source: str) -> None:
    """Show details for one accounting/payment source."""
    console = Console()
    result = SerenaAccountingSourceInfoTool().execute(source=source)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("plan")
@click.option("--goal", required=True, help="Accounting/payment goal.")
@click.option("--source", default="local-ledger", help="Accounting/payment source.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current period", help="Accounting period.")
def plan(goal: str, source: str, business: str, period: str) -> None:
    """Create an accounting/payment operation plan."""
    console = Console()
    result = SerenaAccountingPlanTool().execute(goal=goal, source=source, business=business, period=period)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("xero-env-check")
def xero_env_check() -> None:
    """Check Xero accounting env without exposing secrets."""
    console = Console()
    result = SerenaAccountingXeroEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("xero-connect-check")
def xero_connect_check() -> None:
    """Check Xero connection readiness."""
    console = Console()
    result = SerenaAccountingXeroConnectCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("xero-tenant-list")
def xero_tenant_list() -> None:
    """Show configured Xero tenant readiness."""
    console = Console()
    result = SerenaAccountingXeroTenantListTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("xero-plan")
@click.option("--goal", default="Prepare Xero accounting workflow.", help="Xero operation goal.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current period", help="Accounting period.")
@click.option("--operation", default="readiness", help="Xero operation type.")
def xero_plan(goal: str, business: str, period: str, operation: str) -> None:
    """Create a Xero operation plan."""
    console = Console()
    result = SerenaAccountingXeroPlanTool().execute(goal=goal, business=business, period=period, operation=operation)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("xero-chart-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--industry", default="health practice", help="Business industry.")
@click.option("--notes", default="", help="Optional notes.")
def xero_chart_plan(business: str, industry: str, notes: str) -> None:
    """Create a Xero chart of accounts plan without modifying accounts."""
    console = Console()
    result = SerenaAccountingXeroChartPlanTool().execute(business=business, industry=industry, notes=notes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payfast-env-check")
def payfast_env_check() -> None:
    """Check PayFast env without exposing secrets."""
    console = Console()
    result = SerenaAccountingPayFastEnvCheckTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payfast-plan")
@click.option("--goal", default="Prepare PayFast payment intake workflow.", help="PayFast goal.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current period", help="Accounting period.")
@click.option("--mode", default="sandbox/readiness", help="PayFast mode.")
def payfast_plan(goal: str, business: str, period: str, mode: str) -> None:
    """Create a PayFast payment intake plan."""
    console = Console()
    result = SerenaAccountingPayFastPlanTool().execute(goal=goal, business=business, period=period, mode=mode)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payfast-verify-itn")
@click.option("--payload", required=True, help="PayFast ITN-like payload as JSON or JSON-like text.")
@click.option("--expected-amount", default=None, type=float, help="Expected payment amount.")
@click.option("--expected-reference", default="", help="Expected merchant/reference ID.")
def payfast_verify_itn(payload: str, expected_amount: float | None, expected_reference: str) -> None:
    """Verify a PayFast ITN-like payload locally."""
    console = Console()
    result = SerenaAccountingPayFastVerifyITNTool().execute(
        payload=payload,
        expected_amount=expected_amount,
        expected_reference=expected_reference,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payfast-payment-record")
@click.option("--reference", required=True, help="Payment/reference ID.")
@click.option("--payer", default="", help="Payer name/email.")
@click.option("--amount", required=True, type=float, help="Payment amount.")
@click.option("--status", default="pending", help="Payment status.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--invoice-id", default="", help="Linked invoice ID.")
@click.option("--notes", default="", help="Notes.")
@click.option("--approved", is_flag=True, help="Required when marking paid/complete.")
def payfast_payment_record(
    reference: str,
    payer: str,
    amount: float,
    status: str,
    business: str,
    invoice_id: str,
    notes: str,
    approved: bool,
) -> None:
    """Create a local PayFast payment record."""
    console = Console()
    result = SerenaAccountingPayFastPaymentRecordTool().execute(
        reference=reference,
        payer=payer,
        amount=amount,
        status=status,
        business=business,
        invoice_id=invoice_id,
        notes=notes,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payfast-reconcile-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current period", help="Accounting period.")
@click.option("--notes", default="", help="Optional notes.")
def payfast_reconcile_plan(business: str, period: str, notes: str) -> None:
    """Create a PayFast reconciliation plan."""
    console = Console()
    result = SerenaAccountingPayFastReconcilePlanTool().execute(business=business, period=period, notes=notes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("invoice-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--client", default="Client", help="Client name.")
@click.option("--description", default="Invoice item", help="Invoice description.")
@click.option("--amount", default=0.0, type=float, help="Invoice subtotal amount.")
@click.option("--vat-rate", default=0.0, type=float, help="VAT rate percentage.")
@click.option("--due-date", default="not specified", help="Invoice due date.")
def invoice_plan(business: str, client: str, description: str, amount: float, vat_rate: float, due_date: str) -> None:
    """Create an invoice workflow plan."""
    console = Console()
    result = SerenaAccountingInvoicePlanTool().execute(
        business=business,
        client=client,
        description=description,
        amount=amount,
        vat_rate=vat_rate,
        due_date=due_date,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("create-invoice")
@click.option("--invoice-id", default="", help="Invoice ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--client", required=True, help="Client name.")
@click.option("--description", default="Invoice item", help="Invoice description.")
@click.option("--amount", required=True, type=float, help="Invoice subtotal amount.")
@click.option("--vat-rate", default=0.0, type=float, help="VAT rate percentage.")
@click.option("--due-date", default="not specified", help="Invoice due date.")
@click.option("--status", default="unpaid", help="Invoice status.")
@click.option("--notes", default="", help="Notes.")
def create_invoice(invoice_id: str, business: str, client: str, description: str, amount: float, vat_rate: float, due_date: str, status: str, notes: str) -> None:
    """Create a local invoice record."""
    console = Console()
    result = SerenaAccountingCreateInvoiceTool().execute(
        invoice_id=invoice_id,
        business=business,
        client=client,
        description=description,
        amount=amount,
        vat_rate=vat_rate,
        due_date=due_date,
        status=status,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("record-payment")
@click.option("--payment-id", default="", help="Payment ID.")
@click.option("--invoice-id", default="", help="Linked invoice ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--payer", default="", help="Payer.")
@click.option("--amount", required=True, type=float, help="Payment amount.")
@click.option("--method", default="manual/local", help="Payment method.")
@click.option("--status", default="pending", help="Payment status.")
@click.option("--reference", default="", help="Payment reference.")
@click.option("--approved", is_flag=True, help="Required when status is paid/complete.")
@click.option("--notes", default="", help="Notes.")
def record_payment(payment_id: str, invoice_id: str, business: str, payer: str, amount: float, method: str, status: str, reference: str, approved: bool, notes: str) -> None:
    """Create a local payment record."""
    console = Console()
    result = SerenaAccountingRecordPaymentTool().execute(
        payment_id=payment_id,
        invoice_id=invoice_id,
        business=business,
        payer=payer,
        amount=amount,
        method=method,
        status=status,
        reference=reference,
        approved=approved,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payment-match")
@click.option("--invoice-id", default="", help="Invoice ID to match.")
@click.option("--payment-reference", default="", help="Payment reference to match.")
def payment_match(invoice_id: str, payment_reference: str) -> None:
    """Match local payment records to local invoices."""
    console = Console()
    result = SerenaAccountingPaymentMatchTool().execute(invoice_id=invoice_id, payment_reference=payment_reference)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("unpaid-invoices")
@click.option("--business", default="", help="Optional business filter.")
def unpaid_invoices(business: str) -> None:
    """List local unpaid invoices."""
    console = Console()
    result = SerenaAccountingUnpaidInvoicesTool().execute(business=business)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payment-summary")
@click.option("--business", default="", help="Optional business filter.")
def payment_summary(business: str) -> None:
    """Summarize local payment records."""
    console = Console()
    result = SerenaAccountingPaymentSummaryTool().execute(business=business)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("expense-record")
@click.option("--expense-id", default="", help="Expense ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--supplier", required=True, help="Supplier name.")
@click.option("--category", default="uncategorized", help="Expense category.")
@click.option("--description", default="Expense", help="Expense description.")
@click.option("--amount", required=True, type=float, help="Expense subtotal amount.")
@click.option("--vat-rate", default=0.0, type=float, help="VAT rate percentage.")
@click.option("--date", default="not specified", help="Expense date.")
@click.option("--receipt-path", default="", help="Linked receipt path.")
@click.option("--notes", default="", help="Notes.")
def expense_record(expense_id: str, business: str, supplier: str, category: str, description: str, amount: float, vat_rate: float, date: str, receipt_path: str, notes: str) -> None:
    """Create a local expense record."""
    console = Console()
    result = SerenaAccountingExpenseRecordTool().execute(
        expense_id=expense_id,
        business=business,
        supplier=supplier,
        category=category,
        description=description,
        amount=amount,
        vat_rate=vat_rate,
        date=date,
        receipt_path=receipt_path,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("receipt-capture")
@click.option("--receipt-id", default="", help="Receipt ID.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--path", required=True, help="Receipt/image/document path.")
@click.option("--supplier", default="", help="Supplier name.")
@click.option("--amount", default=0.0, type=float, help="Receipt amount.")
@click.option("--date", default="not specified", help="Receipt date.")
@click.option("--notes", default="", help="Notes.")
def receipt_capture(receipt_id: str, business: str, path: str, supplier: str, amount: float, date: str, notes: str) -> None:
    """Create a local receipt capture record."""
    console = Console()
    result = SerenaAccountingReceiptCaptureTool().execute(
        receipt_id=receipt_id,
        business=business,
        path=path,
        supplier=supplier,
        amount=amount,
        date=date,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("supplier-bill-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--supplier", default="Supplier", help="Supplier name.")
@click.option("--description", default="Supplier bill", help="Bill description.")
@click.option("--amount", default=0.0, type=float, help="Bill subtotal.")
@click.option("--vat-rate", default=0.0, type=float, help="VAT rate percentage.")
@click.option("--due-date", default="not specified", help="Bill due date.")
def supplier_bill_plan(business: str, supplier: str, description: str, amount: float, vat_rate: float, due_date: str) -> None:
    """Create a supplier bill workflow plan."""
    console = Console()
    result = SerenaAccountingSupplierBillPlanTool().execute(
        business=business,
        supplier=supplier,
        description=description,
        amount=amount,
        vat_rate=vat_rate,
        due_date=due_date,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("document-to-expense")
@click.option("--text", required=True, help="Document/OCR text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--source-path", default="", help="Source document path.")
@click.option("--supplier", default="unknown supplier", help="Supplier name.")
@click.option("--category", default="document-derived", help="Expense category.")
@click.option("--amount", default=0.0, type=float, help="Amount if known.")
@click.option("--date", default="not specified", help="Date if known.")
def document_to_expense(text: str, business: str, source_path: str, supplier: str, category: str, amount: float, date: str) -> None:
    """Create an expense draft from document/OCR text."""
    console = Console()
    result = SerenaAccountingDocumentToExpenseTool().execute(
        text=text,
        business=business,
        source_path=source_path,
        supplier=supplier,
        category=category,
        amount=amount,
        date=date,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("ocr-receipt-handoff")
@click.option("--path", required=True, help="Receipt image/PDF path.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--notes", default="", help="Notes.")
def ocr_receipt_handoff(path: str, business: str, notes: str) -> None:
    """Plan OCR receipt handoff into Accounting."""
    console = Console()
    result = SerenaAccountingOCRReceiptHandoffTool().execute(path=path, business=business, notes=notes)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("bank-reconcile-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current period", help="Accounting period.")
@click.option("--bank-account", default="not specified", help="Bank account label.")
@click.option("--notes", default="", help="Notes.")
def bank_reconcile_plan(business: str, period: str, bank_account: str, notes: str) -> None:
    """Create a bank reconciliation workflow plan."""
    console = Console()
    result = SerenaAccountingBankReconcilePlanTool().execute(
        business=business,
        period=period,
        bank_account=bank_account,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("transaction-classify")
@click.option("--description", required=True, help="Transaction description.")
@click.option("--amount", required=True, type=float, help="Transaction amount.")
@click.option("--direction", default="unknown", help="inflow/outflow/unknown.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--date", default="not specified", help="Transaction date.")
@click.option("--notes", default="", help="Notes.")
def transaction_classify(description: str, amount: float, direction: str, business: str, date: str, notes: str) -> None:
    """Classify a transaction locally."""
    console = Console()
    result = SerenaAccountingTransactionClassifyTool().execute(
        description=description,
        amount=amount,
        direction=direction,
        business=business,
        date=date,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("exceptions")
@click.option("--business", default="", help="Optional business filter.")
def exceptions(business: str) -> None:
    """Create accounting exceptions report."""
    console = Console()
    result = SerenaAccountingExceptionsTool().execute(business=business)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("month-end-checklist")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current month", help="Accounting period.")
def month_end_checklist(business: str, period: str) -> None:
    """Create month-end accounting checklist."""
    console = Console()
    result = SerenaAccountingMonthEndChecklistTool().execute(business=business, period=period)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("books-summary")
@click.option("--business", default="", help="Optional business filter.")
@click.option("--period", default="current records", help="Accounting period.")
def books_summary(business: str, period: str) -> None:
    """Create local books summary."""
    console = Console()
    result = SerenaAccountingBooksSummaryTool().execute(business=business, period=period)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payroll-plan")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current payroll period", help="Payroll period.")
@click.option("--staff-count", default=0, type=int, help="Expected staff count.")
@click.option("--notes", default="", help="Notes.")
def payroll_plan(business: str, period: str, staff_count: int, notes: str) -> None:
    """Create payroll preparation plan."""
    console = Console()
    result = SerenaAccountingPayrollPlanTool().execute(
        business=business,
        period=period,
        staff_count=staff_count,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payroll-summary")
@click.option("--payroll-data", required=True, help="Payroll data as JSON or JSON-like text.")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current payroll period", help="Payroll period.")
@click.option("--notes", default="", help="Notes.")
def payroll_summary(payroll_data: str, business: str, period: str, notes: str) -> None:
    """Create local payroll summary."""
    console = Console()
    result = SerenaAccountingPayrollSummaryTool().execute(
        payroll_data=payroll_data,
        business=business,
        period=period,
        notes=notes,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("payroll-checklist")
@click.option("--business", default="General Business", help="Business/context.")
@click.option("--period", default="current payroll period", help="Payroll period.")
def payroll_checklist(business: str, period: str) -> None:
    """Create payroll checklist."""
    console = Console()
    result = SerenaAccountingPayrollChecklistTool().execute(business=business, period=period)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@accounting.command("blocked-payroll-submit")
@click.option("--action", default="submit payroll", help="Requested action.")
@click.option("--reason", default="Payroll submission requested.", help="Reason.")
def blocked_payroll_submit(action: str, reason: str) -> None:
    """Deliberately blocked payroll submission/payment command."""
    console = Console()
    result = SerenaAccountingBlockedPayrollSubmitTool().execute(action=action, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["accounting"]
