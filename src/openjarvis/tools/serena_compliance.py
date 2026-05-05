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


SENSITIVE_PATTERNS = {
    "personal_information": [
        "name", "email", "phone", "address", "id number", "identity number", "passport",
        "date of birth", "dob", "patient", "client", "@", "+27"
    ],
    "health_information": [
        "diagnosis", "diagnosed", "treatment", "medication", "prescription", "symptoms",
        "blood pressure", "glucose", "cholesterol", "insulin", "lab result", "medical",
        "clinical", "consultation", "patient history", "health", "doctor", "dr "
    ],
    "special_personal_information": [
        "biometric", "face recognition", "voiceprint", "fingerprint", "photo", "video",
        "health information", "medical history", "religion", "race"
    ],
    "marketing_claims": [
        "guaranteed", "cure", "cures", "heal", "heals", "miracle", "risk-free",
        "no side effects", "best doctor", "proven results", "before and after",
        "testimonial", "limited time", "only treatment"
    ],
    "clinical_decision": [
        "diagnose", "diagnosis is", "prescribe", "take this medication", "stop medication",
        "increase dose", "decrease dose", "you have", "medical advice"
    ],
    "external_sharing": [
        "upload", "share", "send", "publish", "post", "email", "drive", "google docs",
        "public", "export", "download", "newsletter", "wordpress", "social media"
    ],
    "hidden_capture": [
        "secretly record", "hidden camera", "background watch", "always on camera",
        "silent screen", "without telling", "watch them", "record audio"
    ],
    "bulk_operation": [
        "export all", "bulk export", "delete all", "mass delete", "all patients",
        "all clients", "dump database", "full database"
    ],
    "secrets": [
        "api key", "secret", "password", "refresh token", "client secret", "private key",
        "bearer token"
    ],
}


def _contains_any(text: str, patterns: list[str]) -> list[str]:
    lower = text.lower()
    return sorted({pattern for pattern in patterns if pattern.lower() in lower})


def _classify_text(text: str, context: str = "", check_type: str = "general") -> dict[str, Any]:
    combined = f"{context}\n{text}".strip()
    hits: dict[str, list[str]] = {}

    for category, patterns in SENSITIVE_PATTERNS.items():
        found = _contains_any(combined, patterns)
        if found:
            hits[category] = found

    blockers = []
    warnings = []
    approvals = []
    policy_refs = []

    if hits.get("secrets"):
        blockers.append("Possible secret/credential exposure detected.")
        policy_refs.append("data-sharing")

    if hits.get("hidden_capture"):
        blockers.append("Hidden camera/audio/screen capture or always-on watching detected.")
        policy_refs.append("vision-capture")

    if hits.get("clinical_decision"):
        blockers.append("Possible autonomous clinical decision, diagnosis, prescription, or treatment instruction detected.")
        policy_refs.append("clinical-boundaries")

    if hits.get("bulk_operation"):
        blockers.append("Possible destructive/bulk sensitive-data operation detected.")
        policy_refs.append("data-sharing")

    if hits.get("health_information"):
        warnings.append("Health or clinical information detected.")
        approvals.append("Human review required for clinical/health handling.")
        policy_refs.extend(["national-health-confidentiality", "hpcsa-patient-records", "clinical-boundaries"])

    if hits.get("personal_information"):
        warnings.append("Personal information detected.")
        policy_refs.append("popia")

    if hits.get("special_personal_information"):
        warnings.append("Special personal information or biometric/visual data detected.")
        approvals.append("Explicit approval required for external sharing or processing.")
        policy_refs.extend(["popia", "vision-capture"])

    if hits.get("marketing_claims"):
        warnings.append("Marketing or clinical claim language detected.")
        approvals.append("HPCSA/marketing review required before publication.")
        policy_refs.append("hpcsa-social-media-marketing")

    if hits.get("external_sharing") and (hits.get("personal_information") or hits.get("health_information") or hits.get("special_personal_information")):
        warnings.append("External sharing/upload/publishing context detected with sensitive data.")
        approvals.append("Approval required before external sharing.")
        policy_refs.append("data-sharing")

    if blockers:
        risk = "BLOCKED"
    elif hits.get("health_information") or hits.get("special_personal_information"):
        risk = "HIGH"
    elif hits.get("personal_information") or hits.get("marketing_claims") or hits.get("external_sharing"):
        risk = "MEDIUM"
    else:
        risk = "LOW"

    allowed_to_continue = risk not in {"BLOCKED"}

    return {
        "check_type": check_type,
        "risk_level": risk,
        "allowed_to_continue": allowed_to_continue,
        "sensitive_data_types": sorted(hits.keys()),
        "matched_terms": hits,
        "warnings": sorted(set(warnings)),
        "blockers": sorted(set(blockers)),
        "approval_required": bool(approvals or risk in {"HIGH", "BLOCKED"}),
        "approval_reasons": sorted(set(approvals)),
        "policy_refs": sorted(set(policy_refs)),
        "content_length": len(text),
        "context": context,
        "secret_values_exposed": False,
    }


def _check_response(title: str, classification: dict[str, Any], report_path: Path) -> str:
    lines = [
        title,
        "",
        f"- Risk level: {classification['risk_level']}",
        f"- Allowed to continue: {'yes' if classification['allowed_to_continue'] else 'no'}",
        f"- Approval required: {'yes' if classification['approval_required'] else 'no'}",
        f"- Sensitive data types: {', '.join(classification['sensitive_data_types']) if classification['sensitive_data_types'] else 'none detected'}",
        f"- Policy refs: {', '.join(classification['policy_refs']) if classification['policy_refs'] else 'none'}",
        f"- Report: {report_path}",
        "- Changes made: no",
        "- Policy rules changed: no",
        "- Secret values exposed: no",
        "- Hub adapter: pending future dashboard",
        "",
        "Warnings:",
    ]

    lines.extend(f"- {item}" for item in classification["warnings"]) if classification["warnings"] else lines.append("- none")

    lines.extend(["", "Blockers:"])
    lines.extend(f"- {item}" for item in classification["blockers"]) if classification["blockers"] else lines.append("- none")

    lines.extend(["", "Approval reasons:"])
    lines.extend(f"- {item}" for item in classification["approval_reasons"]) if classification["approval_reasons"] else lines.append("- none")

    lines.extend(["", "Matched terms:"])
    if classification["matched_terms"]:
        for category, terms in classification["matched_terms"].items():
            lines.append(f"- {category}: {', '.join(terms)}")
    else:
        lines.append("- none")

    return "\n".join(lines)


def _run_check(title: str, text: str, context: str, check_type: str, report_name: str) -> ToolResult:
    classification = _classify_text(text=text, context=context, check_type=check_type)
    payload = {
        "report_type": f"serena_compliance_{check_type}",
        "created_at": _timestamp(),
        "text_preview": text[:500],
        "context": context,
        "classification": classification,
        "hub_adapter": _hub_adapter_contract(),
        "changes_made": False,
        "policy_rules_changed": False,
        "secret_values_exposed": False,
    }
    report_path = _save_json("checks", report_name, payload)
    return ToolResult(
        tool_name=f"serena_compliance_{check_type}",
        success=True,
        content=_check_response(title, classification, report_path),
        metadata={**payload, "report_path": str(report_path)},
    )


@ToolRegistry.register("serena_compliance_quick_check")
class SerenaComplianceQuickCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_quick_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run a quick Serena compliance risk check.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _run_check(
            "Serena Compliance quick check",
            str(params.get("text") or ""),
            str(params.get("context") or ""),
            "quick_check",
            "quick-check",
        )


@ToolRegistry.register("serena_compliance_full_check")
class SerenaComplianceFullCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_full_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run a full Serena compliance check across privacy, health, marketing, and workflow risk.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        return _run_check(
            "Serena Compliance full check",
            str(params.get("text") or ""),
            str(params.get("context") or ""),
            "full_check",
            "full-check",
        )


@ToolRegistry.register("serena_compliance_popia_check")
class SerenaCompliancePopiaCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_popia_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run a POPIA/privacy-focused compliance check.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "POPIA/privacy check")
        return _run_check("Serena POPIA compliance check", text, context, "popia_check", "popia-check")


@ToolRegistry.register("serena_compliance_hpcsa_check")
class SerenaComplianceHpcsaCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_hpcsa_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run an HPCSA/health marketing/clinical-boundary compliance check.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "HPCSA/clinical/marketing check")
        return _run_check("Serena HPCSA compliance check", text, context, "hpcsa_check", "hpcsa-check")


@ToolRegistry.register("serena_compliance_patient_data_check")
class SerenaCompliancePatientDataCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_patient_data_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check whether content contains patient/client/health data and classify risk.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "patient/client data check")
        return _run_check("Serena patient-data compliance check", text, context, "patient_data_check", "patient-data-check")


@ToolRegistry.register("serena_compliance_marketing_check")
class SerenaComplianceMarketingCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_marketing_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check health/business marketing content for compliance risks.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "marketing/social/content compliance check")
        return _run_check("Serena marketing compliance check", text, context, "marketing_check", "marketing-check")


@ToolRegistry.register("serena_compliance_document_check")
class SerenaComplianceDocumentCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_document_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check document text before saving, uploading, sharing, or publishing.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "document compliance check")
        return _run_check("Serena document compliance check", text, context, "document_check", "document-check")


def _workflow_context(base: str, workflow: str) -> str:
    return f"{workflow} workflow guard. {base}".strip()


@ToolRegistry.register("serena_compliance_ocr_check")
class SerenaComplianceOcrCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_ocr_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check OCR/camera/screen/video extracted text or capture workflow before handoff.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "")
        target = str(params.get("target") or "local report").strip()
        combined_context = _workflow_context(
            f"{context} Target handoff: {target}. OCR/capture may contain visual, patient, health, or personal data.",
            "OCR/Vision",
        )
        return _run_check("Serena OCR/Vision compliance guard", text, combined_context, "ocr_check", "ocr-check")


@ToolRegistry.register("serena_compliance_drive_sharing_check")
class SerenaComplianceDriveSharingCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_drive_sharing_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Drive upload/link/share workflow before external storage or sharing.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "drive_action": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "")
        drive_action = str(params.get("drive_action") or "upload/link").strip()
        combined_context = _workflow_context(
            f"{context} Drive action: {drive_action}. Check for sensitive data before upload, link return, or sharing.",
            "Google Drive",
        )
        return _run_check("Serena Google Drive sharing compliance guard", text, combined_context, "drive_sharing_check", "drive-sharing-check")


@ToolRegistry.register("serena_compliance_docs_check")
class SerenaComplianceDocsCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_docs_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Docs create/edit/export workflow before document creation or sharing.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "doc_action": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "")
        doc_action = str(params.get("doc_action") or "create/edit/export").strip()
        combined_context = _workflow_context(
            f"{context} Google Docs action: {doc_action}. Check document content before create, edit, export, link, or Drive handoff.",
            "Google Docs",
        )
        return _run_check("Serena Google Docs compliance guard", text, combined_context, "docs_check", "docs-check")


@ToolRegistry.register("serena_compliance_calendar_check")
class SerenaComplianceCalendarCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_calendar_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check Google Calendar appointment/reminder/event workflow for privacy and clinical safety.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "calendar_action": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "")
        calendar_action = str(params.get("calendar_action") or "appointment/reminder/event").strip()
        combined_context = _workflow_context(
            f"{context} Calendar action: {calendar_action}. Check title, description, attendees, links, and health/private details before event creation or update.",
            "Google Calendar",
        )
        return _run_check("Serena Google Calendar compliance guard", text, combined_context, "calendar_check", "calendar-check")


@ToolRegistry.register("serena_compliance_crm_check")
class SerenaComplianceCrmCheckTool(_ComplianceBaseTool):
    tool_id = "serena_compliance_crm_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check CRM/business/patient record workflow for sensitive data, bulk actions, and audit requirements.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "crm_action": {"type": "string"},
                },
                "required": ["text"],
            },
            category="serena_compliance",
        )

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        context = str(params.get("context") or "")
        crm_action = str(params.get("crm_action") or "create/update/search/export").strip()
        combined_context = _workflow_context(
            f"{context} CRM action: {crm_action}. CRM may contain client, patient, business, financial, or health data.",
            "CRM/Business OS",
        )
        return _run_check("Serena CRM compliance guard", text, combined_context, "crm_check", "crm-check")


__all__ = [
    "SerenaComplianceStatusTool",
    "SerenaCompliancePolicyListTool",
    "SerenaCompliancePolicyInfoTool",
    "SerenaComplianceSourceListTool",
    "SerenaCompliancePlanTool",
    "SerenaComplianceDocumentCheckTool",
    "SerenaComplianceCrmCheckTool",
    "SerenaComplianceCalendarCheckTool",
    "SerenaComplianceDocsCheckTool",
    "SerenaComplianceDriveSharingCheckTool",
    "SerenaComplianceOcrCheckTool",
    "SerenaComplianceMarketingCheckTool",
    "SerenaCompliancePatientDataCheckTool",
    "SerenaComplianceHpcsaCheckTool",
    "SerenaCompliancePopiaCheckTool",
    "SerenaComplianceFullCheckTool",
    "SerenaComplianceQuickCheckTool",
]
