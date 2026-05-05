
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


__all__ = ["accounting"]
