"""Native Serena Compliance / Policy Guard operator tools.

Serena Compliance Full Operator v1 foundation:
- status
- policy-list
- policy-info
- source-list
- plan
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


COMPLIANCE_OUTPUT_ROOT = Path("outputs/compliance")
COMPLIANCE_POLICY_DIR = Path("src/openjarvis/policies/compliance")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "compliance"


def _compliance_root() -> Path:
    COMPLIANCE_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "checks", "policies", "audits"]:
        (COMPLIANCE_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    COMPLIANCE_POLICY_DIR.mkdir(parents=True, exist_ok=True)
    return COMPLIANCE_OUTPUT_ROOT


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _compliance_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _policy_files() -> list[Path]:
    COMPLIANCE_POLICY_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(path for path in COMPLIANCE_POLICY_DIR.glob("*.md") if path.is_file())


def _load_policy(policy_id: str) -> tuple[Path, str]:
    requested = _safe_slug(policy_id)
    for path in _policy_files():
        stem_slug = _safe_slug(path.stem)
        name_slug = _safe_slug(path.name)
        if requested in {stem_slug, name_slug}:
            return path, path.read_text(encoding="utf-8", errors="ignore")
    raise RuntimeError(f"Policy not found: {policy_id}")


def _load_source_registry() -> dict[str, Any]:
    path = COMPLIANCE_POLICY_DIR / "source-registry.json"
    if not path.exists():
        return {"sources": [], "status": "missing"}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _hub_adapter_contract() -> dict[str, Any]:
    return {
        "hub_adapter_status": "pending_future_dashboard",
        "future_widgets": [
            "compliance_risk_widget",
            "policy_library_widget",
            "active_warning_widget",
            "blocked_action_widget",
            "approval_requirement_widget",
            "policy_update_monitor_widget",
            "audit_report_widget",
        ],
        "future_events": [
            "compliance_checked",
            "compliance_warning_created",
            "compliance_action_blocked",
            "compliance_policy_update_available",
            "compliance_approval_required",
            "compliance_audit_completed",
        ],
        "operator_state": [
            "current_business_id",
            "current_policy_context",
            "current_risk_level",
            "current_sensitive_data_types",
            "current_blocked_reason",
            "current_compliance_report",
            "current_required_approval",
        ],
    }


def _risk_model() -> dict[str, Any]:
    return {
        "LOW": [
            "general business content",
            "no personal data",
            "no health data",
            "no clinical claims",
        ],
        "MEDIUM": [
            "health education content",
            "personal information without health detail",
            "marketing claims needing review",
            "business-sensitive documents",
        ],
        "HIGH": [
            "patient/client/health data",
            "lab results",
            "medical records",
            "identifiable stories or images",
            "external sharing",
            "Drive/Docs uploads containing sensitive info",
            "bulk exports",
            "autonomous actions involving sensitive data",
        ],
        "BLOCKED": [
            "silent disclosure of patient/client data",
            "publishing identifiable patient info without authorization",
            "autonomous clinical decision",
            "diagnosis or prescription automation",
            "destructive bulk patient/client data operations",
            "hidden camera/audio/screen watching",
            "secret credential exposure",
            "silent policy updates",
        ],
    }


def _safety_policy() -> dict[str, Any]:
    return {
        "allowed": [
            "Classify compliance risk.",
            "Check content/documents/workflow actions.",
            "Create local compliance reports.",
            "Maintain local policy library.",
            "Check policy source registry.",
            "Propose policy refresh plans.",
        ],
        "blocked": [
            "Final legal advice.",
            "Autonomous clinical decisions.",
            "Silent disclosure of sensitive data.",
            "Hidden capture.",
            "Silent policy rewriting.",
            "Destructive or bulk exports.",
            "Secret exposure.",
            "Committing credentials.",
        ],
        "requires_human_review": [
            "Policy updates.",
            "High-risk patient/health disclosures.",
            "Marketing with clinical claims.",
            "Public use of patient stories/images.",
            "Clinical interpretations.",
        ],
    }


class _ComplianceBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_compliance_status")
class SerenaComplianceStatusTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena Compliance / Policy Guard operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        root = _compliance_root()
        policies = _policy_files()
        sources = _load_source_registry().get("sources", [])

        return self._result(
            "Serena Compliance / Policy Guard status\n\n"
            "- Status: active\n"
            "- Role: central compliance, privacy, clinical-safety, marketing-safety, and workflow guard operator\n"
            f"- Local policies: {len(policies)}\n"
            f"- Source registry entries: {len(sources)}\n"
            "- POPIA/privacy awareness: yes\n"
            "- Health confidentiality awareness: yes\n"
            "- HPCSA/patient-record/social-media awareness: yes\n"
            "- Hidden capture: blocked\n"
            "- Silent disclosure: blocked\n"
            "- Silent policy rewriting: blocked\n"
            "- Autonomous clinical decisions: blocked\n"
            "- Secret values exposed: no\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Checks: {root / 'checks'}\n"
            f"- Policies: {root / 'policies'}\n"
            f"- Audits: {root / 'audits'}\n"
            "- Hub adapter: pending future dashboard",
            metadata={
                "policy_count": len(policies),
                "source_count": len(sources),
                "hub_adapter": _hub_adapter_contract(),
                "secret_values_exposed": False,
            },
        )


@ToolRegistry.register("serena_compliance_policy_list")
class SerenaCompliancePolicyListTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_policy_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List local Serena compliance policies.",
            parameters={"type": "object", "properties": {}},
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        policies = _policy_files()
        payload = {
            "report_type": "serena_compliance_policy_list",
            "created_at": _timestamp(),
            "policies": [str(path) for path in policies],
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("policies", "policy-list", payload)

        lines = [
            "Serena Compliance policy list",
            "",
            f"- Policies found: {len(policies)}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Policies:",
        ]

        if policies:
            for path in policies:
                lines.append(f"- {path.stem} | {path}")
        else:
            lines.append("- none")

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_compliance_policy_info")
class SerenaCompliancePolicyInfoTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_policy_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Read a local Serena compliance policy summary.",
            parameters={
                "type": "object",
                "properties": {
                    "policy": {"type": "string"},
                    "preview_chars": {"type": "integer"},
                },
                "required": ["policy"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        policy = str(params.get("policy") or "").strip()
        preview_chars = int(params.get("preview_chars") or 3000)

        try:
            path, text = _load_policy(policy)
            preview = text[:preview_chars]
            payload = {
                "report_type": "serena_compliance_policy_info",
                "created_at": _timestamp(),
                "policy": policy,
                "path": str(path),
                "character_count": len(text),
                "preview_chars": preview_chars,
                "changes_made": False,
                "secret_values_exposed": False,
            }
            report_path = _save_json("policies", f"policy-info-{path.stem}", payload)

            return self._result(
                "Serena Compliance policy info\n\n"
                f"- Policy: {path.stem}\n"
                f"- Path: {path}\n"
                f"- Characters: {len(text)}\n"
                f"- Report: {report_path}\n"
                "- Changes made: no\n"
                "- Secret values exposed: no\n\n"
                "Preview:\n"
                f"{preview}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(
                "Serena Compliance policy-info failed\n\n"
                f"- Policy: {policy}\n"
                f"- Error: {exc}\n"
                "- Changes made: no",
                success=False,
            )


@ToolRegistry.register("serena_compliance_source_list")
class SerenaComplianceSourceListTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_source_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List compliance policy source registry entries.",
            parameters={"type": "object", "properties": {}},
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        registry = _load_source_registry()
        sources = registry.get("sources", [])

        payload = {
            "report_type": "serena_compliance_source_list",
            "created_at": _timestamp(),
            "registry": registry,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        report_path = _save_json("policies", "source-list", payload)

        lines = [
            "Serena Compliance source list",
            "",
            f"- Sources found: {len(sources)}",
            f"- Report: {report_path}",
            "- Changes made: no",
            "- Secret values exposed: no",
            "",
            "Sources:",
        ]

        if sources:
            for item in sources:
                lines.append(
                    f"- {item.get('id')} | {item.get('name')} | area={item.get('policy_area')} | review_required={item.get('review_required')}"
                )
        else:
            lines.append("- none")

        lines.extend([
            "",
            "Policy update rule:",
            "- Serena may check and propose policy updates, but may not silently activate new rules.",
        ])

        return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})


@ToolRegistry.register("serena_compliance_plan")
class SerenaCompliancePlanTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a compliance operation plan without changing policy rules.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "operation": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["goal"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        goal = str(params.get("goal") or "").strip()
        operation = str(params.get("operation") or "compliance-check").strip()
        context = str(params.get("context") or "").strip()

        plan = {
            "report_type": "serena_compliance_plan",
            "created_at": _timestamp(),
            "goal": goal,
            "operation": operation,
            "context": context,
            "risk_model": _risk_model(),
            "safety_policy": _safety_policy(),
            "hub_adapter": _hub_adapter_contract(),
            "steps": [
                "Identify the action/content/workflow being checked.",
                "Classify sensitive data types.",
                "Classify risk level.",
                "Check relevant local policies.",
                "Identify warnings, blockers, and approval requirements.",
                "Write a compliance report.",
                "Do not silently disclose sensitive data.",
                "Do not silently update policy rules.",
            ],
            "policy_rules_changed": False,
            "changes_made": False,
            "secret_values_exposed": False,
        }
        plan_path = _save_json("reports", goal or operation or "compliance-plan", plan)

        return self._result(
            "Serena Compliance operation plan\n\n"
            f"- Goal: {goal}\n"
            f"- Operation: {operation}\n"
            f"- Context: {context or 'not specified'}\n"
            f"- Plan: {plan_path}\n"
            "- Policy rules changed: no\n"
            "- Changes made: no\n"
            "- Secret values exposed: no\n"
            "- Hub adapter: pending future dashboard\n\n"
            "Steps:\n"
            + "\n".join(f"- {step}" for step in plan["steps"]),
            metadata={**plan, "plan_path": str(plan_path)},
        )


__all__ = [
    "SerenaComplianceStatusTool",
    "SerenaCompliancePolicyListTool",
    "SerenaCompliancePolicyInfoTool",
    "SerenaComplianceSourceListTool",
    "SerenaCompliancePlanTool",
]
