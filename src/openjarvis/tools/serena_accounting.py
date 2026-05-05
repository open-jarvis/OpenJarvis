"""Native Serena Accounting / Payments / Payroll / Tax Full Operator tools.

Layer 1 foundation:
- status
- env-check
- plan
- source-list
- source-info
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


ACCOUNTING_OUTPUT_ROOT = Path("outputs/accounting")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "accounting"


def _accounting_root() -> Path:
    ACCOUNTING_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in [
        "reports",
        "snapshots",
        "exports",
        "payments",
        "invoices",
        "expenses",
        "receipts",
        "payroll",
        "tax",
        "handoff",
    ]:
        (ACCOUNTING_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return ACCOUNTING_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _accounting_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _save_text(kind: str, name: str, content: str, suffix: str = ".md") -> Path:
    root = _accounting_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path


def _hub_adapter_contract() -> dict[str, Any]:
    return {
        "hub_adapter_status": "pending_future_dashboard",
        "future_widgets": [
            "accounting_overview_widget",
            "payments_widget",
            "invoices_widget",
            "expenses_widget",
            "receipts_widget",
            "reconciliation_widget",
            "payroll_widget",
            "tax_widget",
            "cashflow_widget",
            "exceptions_widget",
            "accounting_approval_widget",
        ],
        "future_events": [
            "accounting_snapshot_created",
            "payment_recorded",
            "invoice_created",
            "payment_matched",
            "expense_recorded",
            "receipt_captured",
            "reconciliation_exception_created",
            "accounting_report_created",
            "accounting_action_blocked",
        ],
        "operator_state": [
            "current_business_id",
            "current_accounting_source",
            "current_xero_tenant_id",
            "current_payment_provider",
            "current_invoice_id",
            "current_payment_id",
            "current_contact_id",
            "current_report_path",
            "current_required_approval",
        ],
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Inspect finance/payment/accounting environment.",
            "Create local accounting plans.",
            "Create local invoice/payment/expense/receipt records.",
            "Create local accounting snapshots.",
            "Create finance reports.",
            "Prepare Xero/PayFast handoff plans.",
            "Reconcile and match using local evidence.",
            "Prepare VAT/tax/payroll checklists.",
            "Report exactly what changed.",
        ],
        "guarded": [
            "Creating live Xero objects.",
            "Recording live payments.",
            "Invoice changes.",
            "Bank reconciliation changes.",
            "Payroll calculations.",
            "VAT/tax summaries.",
            "Revenue and patient/client-linked reports.",
            "External exports.",
            "Integrations involving PayFast/Xero credentials.",
        ],
        "blocked": [
            "Exposing Xero/PayFast/API secrets.",
            "Changing bank account details.",
            "Submitting tax/VAT returns.",
            "Submitting payroll.",
            "Deleting ledger records.",
            "Voiding invoices.",
            "Refunding payments.",
            "Modifying chart of accounts.",
            "Creating manual journals.",
            "Destructive or bulk accounting changes.",
            "Final accounting/tax/legal advice.",
        ],
    }


def _accounting_sources() -> dict[str, dict[str, Any]]:
    return {
        "xero": {
            "name": "Xero Accounting",
            "status": "planned",
            "role": "Accounting ledger/source of truth for contacts, invoices, payments, bills, bank transactions, reports, VAT/tax prep, and evidence attachments.",
            "required_env": [
                "XERO_CLIENT_ID",
                "XERO_CLIENT_SECRET",
                "XERO_REFRESH_TOKEN",
                "XERO_TENANT_ID",
            ],
            "metrics_or_objects": [
                "contacts",
                "invoices",
                "payments",
                "bills",
                "expenses",
                "bank_transactions",
                "accounts",
                "items",
                "reports",
                "attachments",
                "tax_rates",
            ],
            "notes": [
                "Live Xero write actions must stay approval-gated.",
                "Tax/payroll submissions are blocked unless a future explicit approval workflow exists.",
            ],
        },
        "payfast": {
            "name": "PayFast",
            "status": "planned",
            "role": "Payment-event source for payment links, ITN verification, payment records, matching, and reconciliation handoff.",
            "required_env": [
                "PAYFAST_MERCHANT_ID",
                "PAYFAST_MERCHANT_KEY",
                "PAYFAST_PASSPHRASE",
                "PAYFAST_SANDBOX",
            ],
            "metrics_or_objects": [
                "payment_link",
                "payment_status",
                "itn_payload",
                "merchant_reference",
                "amount_gross",
                "payment_status",
                "signature",
                "reconcile_plan",
            ],
            "notes": [
                "Do not trust browser return_url as proof of payment.",
                "Use ITN/server confirmation or manual approval before recording payment as paid.",
            ],
        },
        "local-ledger": {
            "name": "Local Serena Accounting Records",
            "status": "active_local",
            "role": "Local JSON records, snapshots, reports, payments, invoices, expenses, receipts, payroll/tax prep, and audit evidence.",
            "required_env": [],
            "metrics_or_objects": [
                "local_invoices",
                "local_payments",
                "local_expenses",
                "local_receipts",
                "local_reports",
                "exceptions",
                "audit_records",
            ],
            "notes": [
                "Available without external credentials.",
                "Should later sync or hand off to Xero when approved.",
            ],
        },
        "ocr-drive-docs": {
            "name": "OCR / Google Drive / Google Docs Evidence",
            "status": "active_local_and_google_ready",
            "role": "Receipt capture, evidence intake, invoice/expense document storage, reporting handoff, and document audit trails.",
            "required_env": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
                "GDRIVE_ROOT_FOLDER_ID",
            ],
            "metrics_or_objects": [
                "receipts",
                "invoices",
                "documents",
                "drive_files",
                "google_docs_reports",
                "ocr_text",
            ],
            "notes": [
                "Google token is shared with Drive, Docs, Calendar, Analytics.",
                "Sensitive finance exports require Compliance review.",
            ],
        },
        "reporting-analytics": {
            "name": "Reporting / Analytics",
            "status": "active_local",
            "role": "Finance reports, business summaries, analytics insight, cashflow and revenue reports.",
            "required_env": [],
            "metrics_or_objects": [
                "daily_money_report",
                "weekly_finance_report",
                "monthly_management_report",
                "cashflow_summary",
                "profitability_summary",
                "analytics_snapshot",
            ],
            "notes": [
                "Use Reporting for shareable reports.",
                "Use Analytics for trend/funnel/profitability insight.",
            ],
        },
    }


def _env_status() -> dict[str, Any]:
    sources = _accounting_sources()
    env = {}
    for source_id, source in sources.items():
        required = source.get("required_env", [])
        env[source_id] = {
            "required": [
                {
                    "name": name,
                    "present": bool(os.getenv(name)),
                    "length": len(os.getenv(name, "")),
                }
                for name in required
            ],
            "configured": all(bool(os.getenv(name)) for name in required) if required else True,
        }
    return env


class _AccountingBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_accounting_status")
class SerenaAccountingStatusTool(_AccountingBaseTool):
    tool_id = "serena_accounting_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Accounting / Payments / Payroll / Tax operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _accounting_root()
        sources = _accounting_sources()
        env = _env_status()
        configured_external = [
            sid for sid, item in env.items()
            if item["configured"] and sources[sid].get("required_env")
        ]

        return self._result(
            "Serena Accounting status\n\n"
            "- Status: active\n"
            "- Role: accounting, payments, bookkeeping, payroll-prep, VAT/tax-prep, reconciliation, and finance reporting operator\n"
            f"- Sources registered: {len(sources)}\n"
            f"- Configured external sources: {len(configured_external)}\n"
            "- Xero ledger: planned\n"
            "- PayFast payment intake: planned\n"
            "- Local accounting records: active\n"
            "- OCR/Drive/Docs evidence support: active/ready\n"
            "- Payroll/tax submissions: blocked without future explicit approval layer\n"
            "- Bank changes / ledger deletion / secret exposure: blocked\n"
            "- Secret values exposed: no\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Payments: {root / 'payments'}\n"
            f"- Invoices: {root / 'invoices'}\n"
            f"- Expenses: {root / 'expenses'}\n"
            f"- Receipts: {root / 'receipts'}\n"
            f"- Payroll: {root / 'payroll'}\n"
            f"- Tax: {root / 'tax'}\n"
            "- Hub adapter: pending future dashboard",
            metadata={
                "sources": sources,
                "env_status": env,
                "safety_policy": _safety_policy(),
                "hub_adapter": _hub_adapter_contract(),
                "secret_values_exposed": False,
            },
        )


@ToolRegistry.register("serena_accounting_env_check")
class SerenaAccountingEnvCheckTool(_AccountingBaseTool):
    tool_id = "serena_accounting_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check accounting/payment environment configuration without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status()
        payload = {
            "report_type": "serena_accounting_env_check",
            "created_at": _timestamp(),
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", "env-check", payload)

        lines = [
            "Serena Accounting env check",
            "",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Sources:",
        ]

        for source_id, item in env.items():
            lines.append(f"- {source_id} | configured={'yes' if item['configured'] else 'no'}")
            for var in item["required"]:
                lines.append(f"  - {var['name']} | present={'yes' if var['present'] else 'no'} | length={var['length']}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_source_list")
class SerenaAccountingSourceListTool(_AccountingBaseTool):
    tool_id = "serena_accounting_source_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List registered accounting/payment sources.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        sources = _accounting_sources()
        payload = {
            "report_type": "serena_accounting_source_list",
            "created_at": _timestamp(),
            "sources": sources,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("snapshots", "source-list", payload)

        lines = [
            "Serena Accounting source list",
            "",
            f"- Sources registered: {len(sources)}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Sources:",
        ]

        for source_id, source in sources.items():
            lines.append(f"- {source_id} | {source['name']} | status={source['status']} | objects={len(source['metrics_or_objects'])}")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_source_info")
class SerenaAccountingSourceInfoTool(_AccountingBaseTool):
    tool_id = "serena_accounting_source_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show details for one accounting/payment source.",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                },
                "required": ["source"],
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        source_id = str(params.get("source") or "").strip()
        sources = _accounting_sources()

        if source_id not in sources:
            return self._result(
                "Serena Accounting source-info failed\n\n"
                f"- Source: {source_id}\n"
                "- Error: source not found\n"
                "- Changes made: no",
                success=False,
            )

        source = sources[source_id]
        env = _env_status().get(source_id, {})
        payload = {
            "report_type": "serena_accounting_source_info",
            "created_at": _timestamp(),
            "source_id": source_id,
            "source": source,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("snapshots", f"source-info-{source_id}", payload)

        lines = [
            "Serena Accounting source info",
            "",
            f"- Source: {source_id}",
            f"- Name: {source['name']}",
            f"- Status: {source['status']}",
            f"- Role: {source['role']}",
            f"- Objects/metrics: {len(source['metrics_or_objects'])}",
            f"- Required env vars: {len(source['required_env'])}",
            f"- Snapshot: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Objects / metrics:",
        ]

        lines.extend(f"- {item}" for item in source["metrics_or_objects"])

        lines.extend(["", "Required env:"])
        if source["required_env"]:
            for item in env.get("required", []):
                lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")
        else:
            lines.append("- none")

        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in source["notes"])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_plan")
class SerenaAccountingPlanTool(_AccountingBaseTool):
    tool_id = "serena_accounting_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an accounting/payment operation plan without external writes.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "source": {"type": "string"},
                    "business": {"type": "string"},
                    "period": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        source = str(params.get("source") or "local-ledger").strip()
        business = str(params.get("business") or "General Business").strip()
        period = str(params.get("period") or "current period").strip()

        sources = _accounting_sources()
        source_known = source in sources

        plan = {
            "report_type": "serena_accounting_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "business": business,
            "period": period,
            "source": source,
            "source_known": source_known,
            "safety_policy": _safety_policy(),
            "hub_adapter": _hub_adapter_contract(),
            "steps": [
                "Identify business and accounting source.",
                "Verify required credentials without exposing secrets.",
                "Identify whether this is invoice, payment, expense, receipt, payroll, tax, or report work.",
                "Collect supporting evidence and source documents.",
                "Create local accounting record or plan first.",
                "Match payments/invoices/contacts/orders where possible.",
                "Flag exceptions and approval requirements.",
                "Prepare Xero/PayFast actions only when credentials and approval are ready.",
                "Write report of exactly what changed.",
                "Block dangerous actions such as tax filing, payroll submission, ledger deletion, bank changes, or secret exposure.",
            ],
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("reports", goal or "accounting-plan", plan)

        return self._result(
            "Serena Accounting operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Business: {business}\n"
            f"- Period: {period}\n"
            f"- Source: {source}\n"
            f"- Source known: {'yes' if source_known else 'no'}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Live accounting write: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_accounting_xero_env_check")
class SerenaAccountingXeroEnvCheckTool(_AccountingBaseTool):
    tool_id = "serena_accounting_xero_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Xero accounting environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status().get("xero", {})
        configured = bool(env.get("configured"))
        payload = {
            "report_type": "serena_accounting_xero_env_check",
            "created_at": _timestamp(),
            "source": "xero",
            "configured": configured,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "xero-env-check", payload)

        lines = [
            "Serena Xero env check",
            "",
            f"- Configured: {'yes' if configured else 'no'}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Required environment:",
        ]

        for item in env.get("required", []):
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend([
            "",
            "Notes:",
            "- Xero live accounting actions remain approval-gated.",
            "- Tax/VAT submission, payroll submission, bank changes, manual journals, and ledger deletion remain blocked.",
            "- Xero tenant selection is required before live Xero operations.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_xero_connect_check")
class SerenaAccountingXeroConnectCheckTool(_AccountingBaseTool):
    tool_id = "serena_accounting_xero_connect_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Xero connection readiness. Does not perform live accounting writes.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status().get("xero", {})
        configured = bool(env.get("configured"))

        issues = []
        if not configured:
            issues.append("Xero environment is not fully configured.")

        required_missing = [
            item["name"] for item in env.get("required", [])
            if not item.get("present")
        ]

        if required_missing:
            issues.append("Missing required Xero environment variables: " + ", ".join(required_missing))

        payload = {
            "report_type": "serena_accounting_xero_connect_check",
            "created_at": _timestamp(),
            "connected": False,
            "configured": configured,
            "missing_required": required_missing,
            "issues": issues,
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "xero-connect-check", payload)

        lines = [
            "Serena Xero connection readiness check",
            "",
            f"- Configured: {'yes' if configured else 'no'}",
            "- Connected: no live API call in v1 readiness check",
            f"- Report: {report_path}",
            "- External API called: no",
            "- Live accounting write: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Issues:",
        ]

        lines.extend(f"- {item}" for item in issues) if issues else lines.append("- none")

        lines.extend([
            "",
            "Next setup:",
            "- Create/configure a Xero app.",
            "- Generate XERO_CLIENT_ID, XERO_CLIENT_SECRET, XERO_REFRESH_TOKEN.",
            "- Identify and set XERO_TENANT_ID.",
            "- Run xero-tenant-list after credentials are available.",
        ])

        return self._result("\n".join(lines), success=configured, metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_xero_tenant_list")
class SerenaAccountingXeroTenantListTool(_AccountingBaseTool):
    tool_id = "serena_accounting_xero_tenant_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show configured Xero tenant readiness without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        tenant_id = os.getenv("XERO_TENANT_ID", "").strip()
        configured = bool(tenant_id)
        payload = {
            "report_type": "serena_accounting_xero_tenant_list",
            "created_at": _timestamp(),
            "configured": configured,
            "tenant_id_present": bool(tenant_id),
            "tenant_id_length": len(tenant_id),
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("snapshots", "xero-tenant-list", payload)

        lines = [
            "Serena Xero tenant readiness",
            "",
            f"- XERO_TENANT_ID present: {'yes' if tenant_id else 'no'}",
            f"- XERO_TENANT_ID length: {len(tenant_id)}",
            f"- Snapshot: {report_path}",
            "- External API called: no",
            "- Live accounting write: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Tenants:",
        ]

        if tenant_id:
            lines.append(f"- configured tenant | id length={len(tenant_id)}")
        else:
            lines.append("- none configured")

        lines.extend([
            "",
            "Note:",
            "- Future live Xero tenant discovery can call Xero connections endpoint after OAuth is configured.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_xero_plan")
class SerenaAccountingXeroPlanTool(_AccountingBaseTool):
    tool_id = "serena_accounting_xero_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Xero accounting operation plan without live writes.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "business": {"type": "string"},
                    "period": {"type": "string"},
                    "operation": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "Prepare Xero accounting workflow.").strip()
        business = str(params.get("business") or "General Business").strip()
        period = str(params.get("period") or "current period").strip()
        operation = str(params.get("operation") or "readiness").strip()
        env = _env_status().get("xero", {})

        steps = [
            "Confirm the correct business and Xero organisation.",
            "Confirm Xero credentials and tenant ID without exposing secrets.",
            "Identify operation type: contacts, invoices, payments, bills, bank transactions, reports, VAT/tax prep, or attachments.",
            "Create local plan and evidence record first.",
            "Check Compliance if patient/client/financial data is involved.",
            "Require explicit approval before live Xero write actions.",
            "Write exact report of any proposed or completed accounting change.",
        ]

        payload = {
            "report_type": "serena_accounting_xero_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "business": business,
            "period": period,
            "operation": operation,
            "env_status": env,
            "steps": steps,
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"xero-plan-{business}-{operation}", payload)

        return self._result(
            "Serena Xero operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Business: {business}\n"
            f"- Period: {period}\n"
            f"- Operation: {operation}\n"
            f"- Xero configured: {'yes' if env.get('configured') else 'no'}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Live accounting write: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_accounting_xero_chart_plan")
class SerenaAccountingXeroChartPlanTool(_AccountingBaseTool):
    tool_id = "serena_accounting_xero_chart_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a Xero chart of accounts planning report without modifying accounts.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "industry": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        industry = str(params.get("industry") or "health practice").strip()
        notes = str(params.get("notes") or "").strip()

        suggested_groups = [
            "Revenue / consultation income",
            "Revenue / product or programme income",
            "Cost of sales / direct service costs",
            "Operating expenses",
            "Marketing expenses",
            "Professional fees",
            "Payroll and contractor costs",
            "VAT control accounts",
            "Bank and payment clearing accounts",
            "PayFast clearing account",
            "Accounts receivable",
            "Accounts payable",
        ]

        payload = {
            "report_type": "serena_accounting_xero_chart_plan",
            "created_at": _timestamp(),
            "business": business,
            "industry": industry,
            "notes": notes,
            "suggested_account_groups": suggested_groups,
            "external_api_called": False,
            "chart_modified": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"xero-chart-plan-{business}", payload)

        lines = [
            "Serena Xero chart of accounts plan",
            "",
            f"- Business: {business}",
            f"- Industry: {industry}",
            f"- Plan: {report_path}",
            "- External API called: no",
            "- Chart modified: no",
            "- Live accounting write: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Suggested account groups:",
        ]

        lines.extend(f"- {item}" for item in suggested_groups)

        lines.extend([
            "",
            "Blocked:",
            "- Serena may not modify the chart of accounts without future explicit approval and accountant review.",
            "- Serena may not create manual journals or restructure the ledger silently.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})



def _parse_jsonish(text: str) -> Any:
    """Parse strict JSON first, then tolerate common PowerShell/pasted object forms."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty JSON text")

    try:
        return json.loads(raw)
    except Exception:
        pass

    import re
    fixed = raw

    # Quote unquoted object keys:
    # {payment_status:COMPLETE,m_payment_id:INV-1001}
    fixed = re.sub(
        r'([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)',
        r'\1"\2"\3',
        fixed,
    )

    # Convert single-quoted strings to JSON strings.
    fixed = fixed.replace("'", '"')

    # Quote unquoted string values after colon.
    # Leaves numbers, booleans, null, arrays, objects, and already quoted strings alone.
    fixed = re.sub(
        r':\s*(?!["{\[\-0-9])([A-Za-z_][A-Za-z0-9_\-./ ]*?)(\s*[,}])',
        lambda m: ': "' + m.group(1).strip() + '"' + m.group(2),
        fixed,
    )

    try:
        return json.loads(fixed)
    except Exception as exc:
        raise ValueError(f"could not parse JSON or relaxed JSON-like text: {exc}") from exc


def _money(value: Any) -> float:
    try:
        return round(float(str(value).replace(",", "").strip()), 2)
    except Exception:
        return 0.0


@ToolRegistry.register("serena_accounting_payfast_env_check")
class SerenaAccountingPayFastEnvCheckTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payfast_env_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check PayFast environment without exposing secrets.",
            parameters={"type": "object", "properties": {}},
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        env = _env_status().get("payfast", {})
        configured = bool(env.get("configured"))
        payload = {
            "report_type": "serena_accounting_payfast_env_check",
            "created_at": _timestamp(),
            "source": "payfast",
            "configured": configured,
            "env_status": env,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", "payfast-env-check", payload)

        lines = [
            "Serena PayFast env check",
            "",
            f"- Configured: {'yes' if configured else 'no'}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Required environment:",
        ]

        for item in env.get("required", []):
            lines.append(f"- {item['name']} | present={'yes' if item['present'] else 'no'} | length={item['length']}")

        lines.extend([
            "",
            "Notes:",
            "- PayFast is a payment-event source, not the accounting ledger.",
            "- Browser return_url must not be trusted as payment proof.",
            "- ITN/server confirmation or manual approval is required before marking paid.",
            "- Merchant key/passphrase must never be exposed.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_payfast_plan")
class SerenaAccountingPayFastPlanTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payfast_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a PayFast payment intake plan without external writes.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "business": {"type": "string"},
                    "period": {"type": "string"},
                    "mode": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "Prepare PayFast payment intake workflow.").strip()
        business = str(params.get("business") or "General Business").strip()
        period = str(params.get("period") or "current period").strip()
        mode = str(params.get("mode") or "sandbox/readiness").strip()
        env = _env_status().get("payfast", {})

        steps = [
            "Confirm PayFast merchant credentials without exposing secrets.",
            "Confirm sandbox/live mode.",
            "Define payment reference format for invoice/order/client matching.",
            "Require ITN/server confirmation or manual approval before marking payment paid.",
            "Record local payment evidence first.",
            "Match payment to invoice/order/contact.",
            "Prepare Xero payment record only after approval and Xero readiness.",
            "Write report of exact payment status and reconciliation outcome.",
            "Block refunds, secret exposure, and destructive payment evidence changes.",
        ]

        payload = {
            "report_type": "serena_accounting_payfast_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "business": business,
            "period": period,
            "mode": mode,
            "env_status": env,
            "steps": steps,
            "external_api_called": False,
            "live_payment_action": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"payfast-plan-{business}", payload)

        return self._result(
            "Serena PayFast payment intake plan\n\n"
            f"- Goal: {goal}\n"
            f"- Business: {business}\n"
            f"- Period: {period}\n"
            f"- Mode: {mode}\n"
            f"- PayFast configured: {'yes' if env.get('configured') else 'no'}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Live payment action: no\n"
            "- Live accounting write: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_accounting_payfast_verify_itn")
class SerenaAccountingPayFastVerifyITNTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payfast_verify_itn"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Validate a PayFast ITN-like payload locally and create a verification report. Does not call PayFast.",
            parameters={
                "type": "object",
                "properties": {
                    "payload": {"type": "string"},
                    "expected_amount": {"type": "number"},
                    "expected_reference": {"type": "string"},
                },
                "required": ["payload"],
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        payload_text = str(params.get("payload") or "")
        expected_amount = params.get("expected_amount")
        expected_reference = str(params.get("expected_reference") or "").strip()

        try:
            data = _parse_jsonish(payload_text)
            status = str(data.get("payment_status") or data.get("status") or "").strip().upper()
            reference = str(data.get("m_payment_id") or data.get("merchant_reference") or data.get("reference") or "").strip()
            amount = _money(data.get("amount_gross") or data.get("amount") or data.get("gross") or 0)

            checks = []
            checks.append({"check": "payload_parse", "passed": True})
            checks.append({"check": "payment_status_complete", "passed": status in {"COMPLETE", "PAID", "SUCCESS"}})

            if expected_reference:
                checks.append({"check": "reference_match", "passed": reference == expected_reference})

            if expected_amount is not None:
                checks.append({"check": "amount_match", "passed": amount == _money(expected_amount)})

            signature_present = bool(str(data.get("signature") or "").strip())
            checks.append({"check": "signature_present", "passed": signature_present})

            verified = all(item["passed"] for item in checks)

            payload_out = {
                "report_type": "serena_accounting_payfast_verify_itn",
                "created_at": _timestamp(),
                "payment_status": status,
                "reference": reference,
                "amount": amount,
                "expected_reference": expected_reference,
                "expected_amount": _money(expected_amount) if expected_amount is not None else None,
                "checks": checks,
                "verified_local": verified,
                "server_confirmation_performed": False,
                "external_api_called": False,
                "live_payment_action": False,
                "live_accounting_write": False,
                "changes_made": False,
                "secret_values_exposed": False,
                "hub_adapter": _hub_adapter_contract(),
            }
            report_path = _save_json("payments", f"payfast-itn-verify-{reference or 'unknown'}", payload_out)

            lines = [
                "Serena PayFast ITN local verification",
                "",
                f"- Reference: {reference or 'unknown'}",
                f"- Payment status: {status or 'unknown'}",
                f"- Amount: {amount}",
                f"- Verified locally: {'yes' if verified else 'no'}",
                f"- Report: {report_path}",
                "- Server confirmation performed: no",
                "- External API called: no",
                "- Live payment action: no",
                "- Live accounting write: no",
                "- Changes made: no",
                "- Secret values exposed: no",
                "- Hub adapter: pending future dashboard",
                "",
                "Checks:",
            ]

            for check in checks:
                lines.append(f"- {check['check']} | passed={'yes' if check['passed'] else 'no'}")

            lines.extend([
                "",
                "Important:",
                "- Local payload checks are not final proof of payment.",
                "- Use PayFast server validation/ITN confirmation or manual approval before recording payment as paid.",
            ])

            return self._result("\n".join(lines), success=verified, metadata={**payload_out, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(
                "Serena PayFast ITN verification failed\n\n"
                f"- Error: {exc}\n"
                "- Verified locally: no\n"
                "- External API called: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )


@ToolRegistry.register("serena_accounting_payfast_payment_record")
class SerenaAccountingPayFastPaymentRecordTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payfast_payment_record"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local PayFast payment evidence record. Does not write to Xero.",
            parameters={
                "type": "object",
                "properties": {
                    "reference": {"type": "string"},
                    "payer": {"type": "string"},
                    "amount": {"type": "number"},
                    "status": {"type": "string"},
                    "business": {"type": "string"},
                    "invoice_id": {"type": "string"},
                    "notes": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["reference", "amount"],
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        reference = str(params.get("reference") or "").strip()
        payer = str(params.get("payer") or "").strip()
        amount = _money(params.get("amount") or 0)
        status = str(params.get("status") or "pending").strip()
        business = str(params.get("business") or "General Business").strip()
        invoice_id = str(params.get("invoice_id") or "").strip()
        notes = str(params.get("notes") or "").strip()
        approved = bool(params.get("approved") or False)

        paid_like = status.lower() in {"paid", "complete", "success", "confirmed"}
        if paid_like and not approved:
            return self._result(
                "Serena PayFast payment record blocked\n\n"
                f"- Reference: {reference}\n"
                "- Reason: paid/complete status requires explicit approval or verified ITN evidence.\n"
                "- Payment record created: no\n"
                "- Live accounting write: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "payfast_payment_record",
            "created_at": _timestamp(),
            "business": business,
            "reference": reference,
            "payer": payer,
            "amount": amount,
            "status": status,
            "invoice_id": invoice_id,
            "notes": notes,
            "approved": approved,
            "payment_record_created": True,
            "external_api_called": False,
            "live_payment_action": False,
            "live_accounting_write": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("payments", f"payfast-payment-{reference}", record)

        return self._result(
            "Serena PayFast payment record created\n\n"
            f"- Business: {business}\n"
            f"- Reference: {reference}\n"
            f"- Payer: {payer or 'not provided'}\n"
            f"- Amount: {amount}\n"
            f"- Status: {status}\n"
            f"- Invoice ID: {invoice_id or 'not linked'}\n"
            f"- Record: {record_path}\n"
            "- Payment record created: yes\n"
            "- External API called: no\n"
            "- Live payment action: no\n"
            "- Live accounting write: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_accounting_payfast_reconcile_plan")
class SerenaAccountingPayFastReconcilePlanTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payfast_reconcile_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a PayFast to Xero/local ledger reconciliation plan.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "period": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        period = str(params.get("period") or "current period").strip()
        notes = str(params.get("notes") or "").strip()

        steps = [
            "Export or collect PayFast payment records for the period.",
            "Collect local invoice records and Xero invoices when available.",
            "Match using merchant reference, invoice ID, amount, date, and payer details.",
            "Identify unmatched payments and unmatched invoices.",
            "Flag amount mismatches and duplicate references.",
            "Prepare Xero payment records only after approval.",
            "Create reconciliation exception report.",
            "Do not mark payments as paid from return_url alone.",
        ]

        payload = {
            "report_type": "serena_accounting_payfast_reconcile_plan",
            "created_at": _timestamp(),
            "business": business,
            "period": period,
            "notes": notes,
            "steps": steps,
            "external_api_called": False,
            "live_payment_action": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"payfast-reconcile-plan-{business}-{period}", payload)

        return self._result(
            "Serena PayFast reconciliation plan\n\n"
            f"- Business: {business}\n"
            f"- Period: {period}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Live payment action: no\n"
            "- Live accounting write: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


def _load_json_records(folder: str) -> list[dict[str, Any]]:
    root = ACCOUNTING_OUTPUT_ROOT / folder
    if not root.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict):
                data["_path"] = str(path)
                records.append(data)
        except Exception:
            continue
    return records


def _invoice_total(subtotal: float, vat_rate: float) -> tuple[float, float, float]:
    subtotal = _money(subtotal)
    vat_rate = float(vat_rate or 0)
    vat_amount = round(subtotal * (vat_rate / 100), 2)
    total = round(subtotal + vat_amount, 2)
    return subtotal, vat_amount, total


@ToolRegistry.register("serena_accounting_invoice_plan")
class SerenaAccountingInvoicePlanTool(_AccountingBaseTool):
    tool_id = "serena_accounting_invoice_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an invoice workflow plan without live accounting writes.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                    "client": {"type": "string"},
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                    "vat_rate": {"type": "number"},
                    "due_date": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "General Business").strip()
        client = str(params.get("client") or "Client").strip()
        description = str(params.get("description") or "Invoice item").strip()
        amount = _money(params.get("amount") or 0)
        vat_rate = float(params.get("vat_rate") or 0)
        due_date = str(params.get("due_date") or "not specified").strip()
        subtotal, vat_amount, total = _invoice_total(amount, vat_rate)

        steps = [
            "Confirm client/contact details.",
            "Confirm invoice description, amount, VAT treatment, due date, and business context.",
            "Create local invoice record first.",
            "Attach supporting evidence if needed.",
            "Check Compliance when patient/client/health/financial data is included.",
            "Prepare Xero invoice only after credentials and explicit approval exist.",
            "Report exact invoice values and status.",
        ]

        payload = {
            "report_type": "serena_accounting_invoice_plan",
            "created_at": _timestamp(),
            "business": business,
            "client": client,
            "description": description,
            "subtotal": subtotal,
            "vat_rate": vat_rate,
            "vat_amount": vat_amount,
            "total": total,
            "due_date": due_date,
            "steps": steps,
            "external_api_called": False,
            "live_accounting_write": False,
            "invoice_created": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"invoice-plan-{client}", payload)

        return self._result(
            "Serena invoice plan\n\n"
            f"- Business: {business}\n"
            f"- Client: {client}\n"
            f"- Description: {description}\n"
            f"- Subtotal: {subtotal}\n"
            f"- VAT rate: {vat_rate}%\n"
            f"- VAT amount: {vat_amount}\n"
            f"- Total: {total}\n"
            f"- Due date: {due_date}\n"
            f"- Plan: {report_path}\n"
            "- External API called: no\n"
            "- Live accounting write: no\n"
            "- Invoice created: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in steps),
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_accounting_create_invoice")
class SerenaAccountingCreateInvoiceTool(_AccountingBaseTool):
    tool_id = "serena_accounting_create_invoice"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local invoice record. Does not write to Xero unless future approved live workflow exists.",
            parameters={
                "type": "object",
                "properties": {
                    "invoice_id": {"type": "string"},
                    "business": {"type": "string"},
                    "client": {"type": "string"},
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                    "vat_rate": {"type": "number"},
                    "due_date": {"type": "string"},
                    "status": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["client", "amount"],
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        invoice_id = str(params.get("invoice_id") or f"INV-{_timestamp()}").strip()
        business = str(params.get("business") or "General Business").strip()
        client = str(params.get("client") or "").strip()
        description = str(params.get("description") or "Invoice item").strip()
        amount = _money(params.get("amount") or 0)
        vat_rate = float(params.get("vat_rate") or 0)
        due_date = str(params.get("due_date") or "not specified").strip()
        status = str(params.get("status") or "unpaid").strip().lower()
        notes = str(params.get("notes") or "").strip()
        subtotal, vat_amount, total = _invoice_total(amount, vat_rate)

        record = {
            "record_type": "invoice",
            "created_at": _timestamp(),
            "invoice_id": invoice_id,
            "business": business,
            "client": client,
            "description": description,
            "subtotal": subtotal,
            "vat_rate": vat_rate,
            "vat_amount": vat_amount,
            "total": total,
            "amount_due": total if status not in {"paid", "settled"} else 0.0,
            "due_date": due_date,
            "status": status,
            "notes": notes,
            "invoice_created": True,
            "external_api_called": False,
            "live_accounting_write": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("invoices", f"invoice-{invoice_id}", record)

        return self._result(
            "Serena local invoice created\n\n"
            f"- Invoice ID: {invoice_id}\n"
            f"- Business: {business}\n"
            f"- Client: {client}\n"
            f"- Description: {description}\n"
            f"- Subtotal: {subtotal}\n"
            f"- VAT: {vat_amount}\n"
            f"- Total: {total}\n"
            f"- Status: {status}\n"
            f"- Due date: {due_date}\n"
            f"- Record: {record_path}\n"
            "- Invoice created: yes\n"
            "- External API called: no\n"
            "- Live accounting write: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_accounting_record_payment")
class SerenaAccountingRecordPaymentTool(_AccountingBaseTool):
    tool_id = "serena_accounting_record_payment"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local payment record and optionally link it to an invoice. Does not write to Xero.",
            parameters={
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string"},
                    "invoice_id": {"type": "string"},
                    "business": {"type": "string"},
                    "payer": {"type": "string"},
                    "amount": {"type": "number"},
                    "method": {"type": "string"},
                    "status": {"type": "string"},
                    "reference": {"type": "string"},
                    "approved": {"type": "boolean"},
                    "notes": {"type": "string"},
                },
                "required": ["amount"],
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        payment_id = str(params.get("payment_id") or f"PAY-{_timestamp()}").strip()
        invoice_id = str(params.get("invoice_id") or "").strip()
        business = str(params.get("business") or "General Business").strip()
        payer = str(params.get("payer") or "").strip()
        amount = _money(params.get("amount") or 0)
        method = str(params.get("method") or "manual/local").strip()
        status = str(params.get("status") or "pending").strip().lower()
        reference = str(params.get("reference") or payment_id).strip()
        approved = bool(params.get("approved") or False)
        notes = str(params.get("notes") or "").strip()

        paid_like = status in {"paid", "complete", "success", "confirmed", "settled"}
        if paid_like and not approved:
            return self._result(
                "Serena payment record blocked\n\n"
                f"- Payment ID: {payment_id}\n"
                f"- Invoice ID: {invoice_id or 'not linked'}\n"
                "- Reason: paid/complete status requires explicit approval or verified payment evidence.\n"
                "- Payment record created: no\n"
                "- Live accounting write: no\n"
                "- Changes made: no\n"
                "- Secret values exposed: no",
                success=False,
            )

        record = {
            "record_type": "payment",
            "created_at": _timestamp(),
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "business": business,
            "payer": payer,
            "amount": amount,
            "method": method,
            "status": status,
            "reference": reference,
            "approved": approved,
            "notes": notes,
            "payment_record_created": True,
            "external_api_called": False,
            "live_accounting_write": False,
            "delete_performed": False,
            "changes_made": True,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        record_path = _save_json("payments", f"payment-{payment_id}", record)

        return self._result(
            "Serena local payment record created\n\n"
            f"- Payment ID: {payment_id}\n"
            f"- Business: {business}\n"
            f"- Invoice ID: {invoice_id or 'not linked'}\n"
            f"- Payer: {payer or 'not provided'}\n"
            f"- Amount: {amount}\n"
            f"- Method: {method}\n"
            f"- Status: {status}\n"
            f"- Reference: {reference}\n"
            f"- Record: {record_path}\n"
            "- Payment record created: yes\n"
            "- External API called: no\n"
            "- Live accounting write: no\n"
            "- Delete performed: no\n"
            "- Changes made: yes\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**record, "record_path": str(record_path)},
        )


@ToolRegistry.register("serena_accounting_payment_match")
class SerenaAccountingPaymentMatchTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payment_match"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Match local payment records to local invoices using invoice ID/reference/amount.",
            parameters={
                "type": "object",
                "properties": {
                    "invoice_id": {"type": "string"},
                    "payment_reference": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        invoice_id = str(params.get("invoice_id") or "").strip()
        payment_reference = str(params.get("payment_reference") or "").strip()

        invoices = _load_json_records("invoices")
        payments = _load_json_records("payments")

        matched_invoices = []
        matched_payments = []

        for inv in invoices:
            if invoice_id and str(inv.get("invoice_id") or "") == invoice_id:
                matched_invoices.append(inv)

        for pay in payments:
            pay_invoice_id = str(pay.get("invoice_id") or "")
            pay_ref = str(pay.get("reference") or pay.get("payment_id") or pay.get("reference") or "")
            if invoice_id and pay_invoice_id == invoice_id:
                matched_payments.append(pay)
            elif payment_reference and pay_ref == payment_reference:
                matched_payments.append(pay)

        match_amount = sum(_money(pay.get("amount") or 0) for pay in matched_payments)
        invoice_total = sum(_money(inv.get("total") or inv.get("amount_due") or 0) for inv in matched_invoices)
        balanced = bool(matched_invoices and matched_payments and round(match_amount, 2) == round(invoice_total, 2))

        payload = {
            "report_type": "serena_accounting_payment_match",
            "created_at": _timestamp(),
            "invoice_id": invoice_id,
            "payment_reference": payment_reference,
            "matched_invoice_count": len(matched_invoices),
            "matched_payment_count": len(matched_payments),
            "invoice_total": invoice_total,
            "payment_total": match_amount,
            "balanced": balanced,
            "matched_invoice_paths": [item.get("_path") for item in matched_invoices],
            "matched_payment_paths": [item.get("_path") for item in matched_payments],
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"payment-match-{invoice_id or payment_reference or 'all'}", payload)

        return self._result(
            "Serena payment match report\n\n"
            f"- Invoice ID: {invoice_id or 'not specified'}\n"
            f"- Payment reference: {payment_reference or 'not specified'}\n"
            f"- Matched invoices: {len(matched_invoices)}\n"
            f"- Matched payments: {len(matched_payments)}\n"
            f"- Invoice total: {invoice_total}\n"
            f"- Payment total: {match_amount}\n"
            f"- Balanced: {'yes' if balanced else 'no'}\n"
            f"- Report: {report_path}\n"
            "- External API called: no\n"
            "- Live accounting write: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard",
            metadata={**payload, "report_path": str(report_path)},
        )


@ToolRegistry.register("serena_accounting_unpaid_invoices")
class SerenaAccountingUnpaidInvoicesTool(_AccountingBaseTool):
    tool_id = "serena_accounting_unpaid_invoices"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List local unpaid invoices.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "").strip()
        invoices = _load_json_records("invoices")

        unpaid = []
        for inv in invoices:
            if business and str(inv.get("business") or "") != business:
                continue
            status = str(inv.get("status") or "").lower()
            amount_due = _money(inv.get("amount_due") or inv.get("total") or 0)
            if status not in {"paid", "settled"} and amount_due > 0:
                unpaid.append(inv)

        total_due = sum(_money(item.get("amount_due") or item.get("total") or 0) for item in unpaid)

        payload = {
            "report_type": "serena_accounting_unpaid_invoices",
            "created_at": _timestamp(),
            "business": business or "all",
            "unpaid_count": len(unpaid),
            "total_due": total_due,
            "invoice_paths": [item.get("_path") for item in unpaid],
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"unpaid-invoices-{business or 'all'}", payload)

        lines = [
            "Serena unpaid invoices",
            "",
            f"- Business: {business or 'all'}",
            f"- Unpaid invoices: {len(unpaid)}",
            f"- Total due: {total_due}",
            f"- Report: {report_path}",
            "- External API called: no",
            "- Live accounting write: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "Invoices:",
        ]

        if unpaid:
            for inv in unpaid[:20]:
                lines.append(
                    f"- {inv.get('invoice_id')} | client={inv.get('client')} | status={inv.get('status')} | due={_money(inv.get('amount_due') or inv.get('total') or 0)}"
                )
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_accounting_payment_summary")
class SerenaAccountingPaymentSummaryTool(_AccountingBaseTool):
    tool_id = "serena_accounting_payment_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Summarize local payment records.",
            parameters={
                "type": "object",
                "properties": {
                    "business": {"type": "string"},
                },
            },
            category="serena_accounting",
        )

    def execute(self, **params: Any) -> ToolResult:
        business = str(params.get("business") or "").strip()
        payments = _load_json_records("payments")

        selected = []
        for pay in payments:
            if business and str(pay.get("business") or "") != business:
                continue
            selected.append(pay)

        total = sum(_money(item.get("amount") or 0) for item in selected)
        by_status: dict[str, float] = {}
        for pay in selected:
            status = str(pay.get("status") or "unknown").lower()
            by_status[status] = round(by_status.get(status, 0.0) + _money(pay.get("amount") or 0), 2)

        payload = {
            "report_type": "serena_accounting_payment_summary",
            "created_at": _timestamp(),
            "business": business or "all",
            "payment_count": len(selected),
            "total_amount": total,
            "amount_by_status": by_status,
            "payment_paths": [item.get("_path") for item in selected],
            "external_api_called": False,
            "live_accounting_write": False,
            "changes_made": False,
            "secret_values_exposed": False,
            "hub_adapter": _hub_adapter_contract(),
        }
        report_path = _save_json("reports", f"payment-summary-{business or 'all'}", payload)

        lines = [
            "Serena payment summary",
            "",
            f"- Business: {business or 'all'}",
            f"- Payments: {len(selected)}",
            f"- Total amount: {total}",
            f"- Report: {report_path}",
            "- External API called: no",
            "- Live accounting write: no",
            "- Changes made: no",
            "- Secret values exposed: no",
            "- Hub adapter: pending future dashboard",
            "",
            "By status:",
        ]

        if by_status:
            for status, amount in sorted(by_status.items()):
                lines.append(f"- {status}: {amount}")
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


__all__ = [
    "SerenaAccountingStatusTool",
    "SerenaAccountingEnvCheckTool",
    "SerenaAccountingPlanTool",
    "SerenaAccountingSourceListTool",
    "SerenaAccountingSourceInfoTool",
    "SerenaAccountingXeroChartPlanTool",
    "SerenaAccountingPayFastReconcilePlanTool",
    "SerenaAccountingPaymentSummaryTool",
    "SerenaAccountingUnpaidInvoicesTool",
    "SerenaAccountingPaymentMatchTool",
    "SerenaAccountingRecordPaymentTool",
    "SerenaAccountingCreateInvoiceTool",
    "SerenaAccountingInvoicePlanTool",
    "SerenaAccountingPayFastPaymentRecordTool",
    "SerenaAccountingPayFastVerifyITNTool",
    "SerenaAccountingPayFastPlanTool",
    "SerenaAccountingPayFastEnvCheckTool",
    "SerenaAccountingXeroPlanTool",
    "SerenaAccountingXeroTenantListTool",
    "SerenaAccountingXeroConnectCheckTool",
    "SerenaAccountingXeroEnvCheckTool",
]
