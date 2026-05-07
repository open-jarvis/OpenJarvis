"""Serena Hub / Command Center local-first operator.

Hub v1 is a read-only local aggregator and local web-state generator.
It indexes local operator outputs, creates local rollups, creates local
Hub state files, and generates a static local command-center web shell.

Hub v1 does not mutate upstream operators or external systems.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from typing import Any


HUB_VERSION = "0.1.0"
DEFAULT_ROOT = Path("outputs")
HUB_ROOT = Path("outputs/hub")

KNOWN_SOURCES = {
    "ecommerce": "outputs/ecommerce",
    "wordpress": "outputs/wordpress",
    "reporting": "outputs/reporting",
    "analytics": "outputs/analytics",
    "bookings": "outputs/bookings",
    "documents": "outputs/documents",
    "files": "outputs/files",
    "gdrive": "outputs/gdrive",
    "google-docs": "outputs/google-docs",
    "google-calendar": "outputs/google-calendar",
    "accounting": "outputs/accounting",
    "membership": "outputs/membership",
    "crm": "outputs/crm",
    "compliance": "outputs/compliance",
    "ocr": "outputs/ocr",
    "github": "outputs/github",
    "vscode": "outputs/vscode",
    "health-monitor": "outputs/health-monitor",
}

SAFETY_BOUNDARY = {
    "local_only": True,
    "read_only_external_systems": True,
    "external_writes": False,
    "live_crm_mutation": False,
    "wordpress_publish_or_update": False,
    "calendar_event_create": False,
    "gdrive_upload_or_share": False,
    "google_docs_live_edit": False,
    "payment_or_accounting_write": False,
    "message_or_campaign_send": False,
    "sensitive_export": False,
    "dashboard_external_create": False,
}


ORB_STATES = {
    "idle": {
        "label": "Idle",
        "safety_state": "green",
        "description": "Serena is online and waiting.",
    },
    "wake": {
        "label": "Wake",
        "safety_state": "green",
        "description": "The Hub is waking and Serena is becoming active.",
    },
    "listening": {
        "label": "Listening",
        "safety_state": "green",
        "description": "Serena is listening for a command.",
    },
    "thinking": {
        "label": "Thinking",
        "safety_state": "green",
        "description": "Serena is planning or reasoning.",
    },
    "speaking": {
        "label": "Speaking",
        "safety_state": "green",
        "description": "Serena is responding.",
    },
    "working": {
        "label": "Working",
        "safety_state": "green",
        "description": "Serena is working and widgets are active.",
    },
    "approval": {
        "label": "Awaiting Approval",
        "safety_state": "amber",
        "description": "Serena is waiting for explicit approval.",
    },
    "blocked": {
        "label": "Blocked",
        "safety_state": "red",
        "description": "A risky or unapproved action was blocked.",
    },
    "completed": {
        "label": "Completed",
        "safety_state": "green",
        "description": "The current action completed successfully.",
    },
}

DASHBOARD_SECTIONS = [
    {
        "id": "overview",
        "title": "Command Center",
        "operator": "hub",
        "widget_types": ["voice_orb_widget", "operator_status_widget", "activity_timeline_widget"],
    },
    {
        "id": "crm",
        "title": "CRM Dashboard",
        "operator": "crm",
        "widget_types": ["crm_contact_widget", "crm_lead_widget", "crm_lifecycle_widget", "membership_widget"],
    },
    {
        "id": "operators",
        "title": "Operators Dashboard",
        "operator": "hub",
        "widget_types": ["operator_status_widget", "hub_router_widget", "reporting_widget", "analytics_widget"],
    },
    {
        "id": "finance",
        "title": "Finance Dashboard",
        "operator": "accounting",
        "widget_types": ["accounting_summary_widget", "reporting_widget"],
    },
    {
        "id": "schedule",
        "title": "Schedule / Bookings",
        "operator": "bookings",
        "widget_types": ["calendar_schedule_widget", "bookings_widget"],
    },
    {
        "id": "documents",
        "title": "Documents / Files",
        "operator": "documents",
        "widget_types": ["document_editor_widget", "google_docs_widget", "drive_file_widget"],
    },
    {
        "id": "safety",
        "title": "Safety / Approvals",
        "operator": "hub",
        "widget_types": ["safety_block_widget", "approval_request_widget"],
    },
    {
        "id": "settings",
        "title": "Settings / Connectors",
        "operator": "hub",
        "widget_types": ["hub_router_widget"],
    },
]


@dataclass
class HubArtifact:
    path: str
    operator: str
    suffix: str
    size_bytes: int
    modified_at: str
    artifact_type: str
    handoff_signal: bool
    dashboard_signal: bool
    safety_signal: bool
    blocked_signal: bool
    sensitive_signal: bool
    finance_signal: bool
    schedule_signal: bool
    document_signal: bool
    customer_contact_signal: bool
    membership_signal: bool
    ecommerce_signal: bool
    wordpress_signal: bool
    reporting_analytics_signal: bool
    local_only_signal: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mirror_web_data(path: Path, payload: dict[str, Any]) -> None:
    """Mirror Hub state/rollup JSON into web/data for live browser polling."""
    try:
        normalized = str(path).replace("\\", "/")
        if "/web/data/" in normalized or normalized.endswith("/web/data"):
            return

        rel_name = None
        state_root = HUB_ROOT / "state"
        rollup_root = HUB_ROOT / "rollups"

        try:
            rel_name = path.relative_to(state_root).name
        except ValueError:
            try:
                rel_name = path.relative_to(rollup_root).name
            except ValueError:
                rel_name = None

        if not rel_name or not rel_name.endswith(".json"):
            return

        web_data = HUB_ROOT / "web" / "data"
        web_data.mkdir(parents=True, exist_ok=True)
        mirror_path = web_data / rel_name
        mirror_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Mirroring must never break the primary local write.
        return


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _mirror_web_data(path, payload)
    return path


def _safe_read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _guess_operator(path: Path) -> str:
    normalized = str(path).replace("\\", "/").lower()
    for operator, root in KNOWN_SOURCES.items():
        if normalized.startswith(root.lower()):
            return operator
    parts = normalized.split("/")
    if "outputs" in parts:
        index = parts.index("outputs")
        if len(parts) > index + 1:
            return parts[index + 1]
    return "unknown"


def _artifact_type(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if "handoff" in name:
        return "handoff"
    if "dashboard" in name:
        return "dashboard"
    if "blocked" in name or "safety" in name:
        return "safety"
    if "approval" in name:
        return "approval"
    if "rollup" in name or "summary" in name:
        return "summary"
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".txt"}:
        return "text"
    if suffix in {".html", ".css", ".js"}:
        return "web"
    return suffix.replace(".", "") or "artifact"


def _scan_artifacts(root: str | Path = DEFAULT_ROOT, limit: int = 300) -> list[HubArtifact]:
    root_path = Path(root)
    if not root_path.exists():
        return []

    artifacts: list[HubArtifact] = []
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if "outputs/hub/web" in str(path).replace("\\", "/"):
            continue

        lower = str(path).replace("\\", "/").lower()
        name = path.name.lower()
        stat = path.stat()
        operator = _guess_operator(path)

        artifacts.append(
            HubArtifact(
                path=str(path).replace("\\", "/"),
                operator=operator,
                suffix=path.suffix.lower(),
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat(),
                artifact_type=_artifact_type(path),
                handoff_signal="handoff" in lower,
                dashboard_signal="dashboard" in lower or "widget" in lower,
                safety_signal="safety" in lower or "approval" in lower,
                blocked_signal="blocked" in lower or "unapproved" in lower,
                sensitive_signal="sensitive" in lower or "patient" in lower,
                finance_signal=any(term in lower for term in ["finance", "accounting", "invoice", "payment", "revenue", "billing"]),
                schedule_signal=any(term in lower for term in ["calendar", "schedule", "booking", "appointment"]),
                document_signal=any(term in lower for term in ["document", "docs", "docx", "pdf", "file", "drive"]),
                customer_contact_signal=any(term in lower for term in ["crm", "contact", "customer", "lead"]),
                membership_signal="membership" in lower or "member" in lower,
                ecommerce_signal="ecommerce" in lower or "order" in lower or "product" in lower,
                wordpress_signal="wordpress" in lower or "wp" in name,
                reporting_analytics_signal="reporting" in lower or "analytics" in lower,
                local_only_signal="local" in lower or path.is_relative_to(root_path),
            )
        )

        if len(artifacts) >= limit:
            break

    return artifacts


def hub_status() -> dict[str, Any]:
    return {
        "hub": "serena",
        "operator": "hub",
        "version": HUB_VERSION,
        "status": "ready",
        "mode": "local_read_only",
        "description": "Serena Hub / Command Center v1 local-first operator",
        "safety_boundary": SAFETY_BOUNDARY,
        "output_root": str(HUB_ROOT).replace("\\", "/"),
        "known_sources": KNOWN_SOURCES,
        "timestamp": _utc_now(),
    }


def hub_env_check() -> dict[str, Any]:
    return {
        "status": "ready",
        "mode": "local_read_only",
        "python_ok": True,
        "cwd": str(Path.cwd()),
        "outputs_exists": Path("outputs").exists(),
        "hub_output_root": str(HUB_ROOT).replace("\\", "/"),
        "external_write_keys_required": False,
        "external_write_keys_checked": False,
        "notes": [
            "Hub v1 does not require external API credentials.",
            "Hub v1 reads local outputs and writes local Hub state/web artifacts only.",
        ],
        "safety_boundary": SAFETY_BOUNDARY,
        "timestamp": _utc_now(),
    }


def hub_source_list() -> dict[str, Any]:
    sources = []
    for operator, root in KNOWN_SOURCES.items():
        path = Path(root)
        file_count = len([p for p in path.rglob("*") if p.is_file()]) if path.exists() else 0
        sources.append(
            {
                "operator": operator,
                "root": root,
                "exists": path.exists(),
                "file_count": file_count,
            }
        )
    return {
        "sources": sources,
        "source_count": len(sources),
        "timestamp": _utc_now(),
    }


def hub_artifact_index(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    artifacts = _scan_artifacts(root=root, limit=limit)
    payload = {
        "artifact_count": len(artifacts),
        "root": root,
        "limit": limit,
        "artifacts": [asdict(a) for a in artifacts],
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "indexes" / "artifact_index.json", payload)
    return payload


def _rollup_by_operator(artifacts: list[HubArtifact]) -> list[dict[str, Any]]:
    by_operator: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        item = by_operator.setdefault(
            artifact.operator,
            {
                "operator": artifact.operator,
                "artifact_count": 0,
                "handoff_count": 0,
                "dashboard_count": 0,
                "safety_count": 0,
                "blocked_count": 0,
                "sensitive_count": 0,
                "finance_count": 0,
                "schedule_count": 0,
                "document_count": 0,
                "customer_contact_count": 0,
                "last_artifact_timestamp": None,
                "recommended_next_action": "Refresh outputs or inspect newest local artifact.",
            },
        )
        item["artifact_count"] += 1
        item["handoff_count"] += int(artifact.handoff_signal)
        item["dashboard_count"] += int(artifact.dashboard_signal)
        item["safety_count"] += int(artifact.safety_signal)
        item["blocked_count"] += int(artifact.blocked_signal)
        item["sensitive_count"] += int(artifact.sensitive_signal)
        item["finance_count"] += int(artifact.finance_signal)
        item["schedule_count"] += int(artifact.schedule_signal)
        item["document_count"] += int(artifact.document_signal)
        item["customer_contact_count"] += int(artifact.customer_contact_signal)
        if not item["last_artifact_timestamp"] or artifact.modified_at > item["last_artifact_timestamp"]:
            item["last_artifact_timestamp"] = artifact.modified_at

    return sorted(by_operator.values(), key=lambda x: x["operator"])


def hub_operator_rollup(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    artifacts = _scan_artifacts(root=root, limit=limit)
    payload = {
        "rollup_type": "operator_rollup",
        "operator_count": len(set(a.operator for a in artifacts)),
        "operators": _rollup_by_operator(artifacts),
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "rollups" / "operator_rollup.json", payload)
    return payload


def _signal_rollup(name: str, root: str, limit: int, predicate_name: str) -> dict[str, Any]:
    artifacts = _scan_artifacts(root=root, limit=limit)
    selected = [a for a in artifacts if getattr(a, predicate_name)]
    payload = {
        "rollup_type": name,
        "artifact_count": len(selected),
        "operators": _rollup_by_operator(selected),
        "artifacts": [asdict(a) for a in selected[:100]],
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "rollups" / f"{name}.json", payload)
    return payload


def hub_crm_rollup(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    return _signal_rollup("crm_rollup", root, limit, "customer_contact_signal")


def hub_finance_rollup(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    return _signal_rollup("finance_rollup", root, limit, "finance_signal")


def hub_schedule_rollup(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    return _signal_rollup("schedule_rollup", root, limit, "schedule_signal")


def hub_document_rollup(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    return _signal_rollup("document_rollup", root, limit, "document_signal")


def hub_safety_rollup(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    artifacts = _scan_artifacts(root=root, limit=limit)
    selected = [a for a in artifacts if a.safety_signal or a.blocked_signal or a.sensitive_signal]
    payload = {
        "rollup_type": "safety_rollup",
        "artifact_count": len(selected),
        "blocked_count": sum(1 for a in selected if a.blocked_signal),
        "sensitive_count": sum(1 for a in selected if a.sensitive_signal),
        "approval_or_safety_count": sum(1 for a in selected if a.safety_signal),
        "operators": _rollup_by_operator(selected),
        "artifacts": [asdict(a) for a in selected[:100]],
        "safety_boundary": SAFETY_BOUNDARY,
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "rollups" / "safety_rollup.json", payload)
    return payload


def hub_widget_registry() -> dict[str, Any]:
    widget_specs = [
        ("voice_orb_widget", "Voice Orb", "hub", "overview", 1),
        ("chat_widget", "Chat Command Bar", "hub", "overview", 2),
        ("activity_timeline_widget", "Activity Timeline", "hub", "overview", 3),
        ("operator_status_widget", "Operator Status", "hub", "operators", 1),
        ("crm_contact_widget", "CRM Contact", "crm", "crm", 1),
        ("crm_lead_widget", "CRM Lead", "crm", "crm", 2),
        ("crm_lifecycle_widget", "CRM Lifecycle", "crm", "crm", 3),
        ("membership_widget", "Membership", "membership", "crm", 4),
        ("calendar_schedule_widget", "Calendar Schedule", "google-calendar", "schedule", 1),
        ("bookings_widget", "Bookings", "bookings", "schedule", 2),
        ("document_editor_widget", "Document Editor", "documents", "documents", 1),
        ("google_docs_widget", "Google Docs", "google-docs", "documents", 2),
        ("drive_file_widget", "Drive File", "gdrive", "documents", 3),
        ("browser_search_widget", "Browser Search", "browser", "operators", 4),
        ("image_generation_widget", "Image Generation", "media", "operators", 5),
        ("video_generation_widget", "Video Generation", "media", "operators", 6),
        ("wordpress_page_widget", "WordPress Page", "wordpress", "operators", 7),
        ("accounting_summary_widget", "Accounting Summary", "accounting", "finance", 1),
        ("reporting_widget", "Reporting", "reporting", "operators", 8),
        ("analytics_widget", "Analytics", "analytics", "operators", 9),
        ("safety_block_widget", "Safety Block", "hub", "safety", 1),
        ("approval_request_widget", "Approval Request", "hub", "safety", 2),
        ("hub_router_widget", "Hub Router", "hub", "settings", 1),
    ]

    widgets = []
    for widget_id, title, operator, section, priority in widget_specs:
        widgets.append(
            {
                "id": widget_id,
                "type": widget_id,
                "title": title,
                "enabled": True,
                "state": "available",
                "operator": operator,
                "section": section,
                "priority": priority,
                "artifact_path": None,
                "supports_states": ["available", "open", "working", "approval", "blocked", "completed"],
            }
        )

    payload = {
        "widgets": sorted(widgets, key=lambda item: (item["section"], item["priority"], item["id"])),
        "sections": DASHBOARD_SECTIONS,
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "state" / "widgets.json", payload)
    return payload


def _default_hub_state() -> dict[str, Any]:
    return {
        "hub_status": "active",
        "orb_state": "idle",
        "orb_state_label": ORB_STATES["idle"]["label"],
        "orb_state_description": ORB_STATES["idle"]["description"],
        "available_orb_states": list(ORB_STATES.keys()),
        "active_operator": "hub",
        "active_task": None,
        "active_section": "overview",
        "safety_state": "green",
        "last_updated": _utc_now(),
        "safety_boundary": SAFETY_BOUNDARY,
    }


def _ensure_base_state() -> None:
    state_path = HUB_ROOT / "state" / "hub_state.json"
    existing = _safe_read_json(state_path)

    if isinstance(existing, dict):
        state = _default_hub_state()
        state.update(existing)
        state["available_orb_states"] = list(ORB_STATES.keys())
        state["safety_boundary"] = SAFETY_BOUNDARY
        state["last_updated"] = existing.get("last_updated") or _utc_now()
    else:
        state = _default_hub_state()

    _write_json(state_path, state)

    for name in ["activity_events", "approvals"]:
        path = HUB_ROOT / "state" / f"{name}.json"
        if not path.exists():
            _write_json(path, {"events" if name == "activity_events" else "approvals": []})

    command_queue_path = HUB_ROOT / "state" / "command_queue.json"
    if not command_queue_path.exists():
        _write_json(command_queue_path, {"commands": [], "last_command": None, "timestamp": _utc_now()})


def hub_activity_event(
    operator: str,
    event_type: str,
    message: str,
    status: str = "created",
    artifact_path: str | None = None,
) -> dict[str, Any]:
    _ensure_base_state()
    path = HUB_ROOT / "state" / "activity_events.json"
    payload = _safe_read_json(path)
    if not isinstance(payload, dict):
        payload = {"events": []}
    events = payload.setdefault("events", [])
    event = {
        "timestamp": _utc_now(),
        "operator": operator,
        "event_type": event_type,
        "status": status,
        "message": message,
        "artifact_path": artifact_path,
    }
    events.append(event)
    _write_json(path, payload)
    return event


def hub_chat_request(message: str, operator: str = "hub") -> dict[str, Any]:
    _ensure_base_state()
    safe_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "id": f"chat-request-{safe_id}",
        "operator": operator,
        "message": message,
        "status": "local_record_created",
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }
    path = HUB_ROOT / "requests" / f"{payload['id']}.json"
    _write_json(path, payload)
    hub_activity_event(operator=operator, event_type="chat_request", message="Local Hub chat request recorded.", status="created", artifact_path=str(path).replace("\\", "/"))
    return payload


def hub_action_routing_plan(scope: str, include_sensitive: bool = False) -> dict[str, Any]:
    _ensure_base_state()
    blocked = bool(include_sensitive)
    payload = {
        "scope": scope,
        "status": "blocked" if blocked else "planned",
        "routing_enabled": False,
        "external_action_taken": False,
        "include_sensitive": include_sensitive,
        "blockers": ["Sensitive routing/export is blocked in Hub v1."] if blocked else [],
        "safety_boundary": SAFETY_BOUNDARY,
        "timestamp": _utc_now(),
    }
    path = HUB_ROOT / "action-routing-plans" / f"action_routing_plan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(path, payload)
    hub_activity_event(operator="hub", event_type="action_routing_plan", message=f"Hub action routing plan created for scope: {scope}", status=payload["status"], artifact_path=str(path).replace("\\", "/"))
    return payload


def hub_blocked_unapproved_action(action: str, operator: str = "hub", reason: str = "Unapproved live action blocked by Hub v1.") -> dict[str, Any]:
    _ensure_base_state()
    payload = {
        "action": action,
        "operator": operator,
        "status": "blocked",
        "reason": reason,
        "external_action_taken": False,
        "safety_boundary": SAFETY_BOUNDARY,
        "timestamp": _utc_now(),
    }
    path = HUB_ROOT / "blocked-actions" / f"blocked_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json(path, payload)
    hub_activity_event(operator=operator, event_type="blocked_action", message=reason, status="blocked", artifact_path=str(path).replace("\\", "/"))
    return payload


def hub_artifact_summary(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    artifacts = _scan_artifacts(root=root, limit=limit)
    total_size = sum(a.size_bytes for a in artifacts)
    by_type: dict[str, int] = {}
    newest = sorted(artifacts, key=lambda a: a.modified_at, reverse=True)[:12]

    for artifact in artifacts:
        by_type[artifact.artifact_type] = by_type.get(artifact.artifact_type, 0) + 1

    payload = {
        "summary_type": "artifact_summary",
        "root": root,
        "artifact_count": len(artifacts),
        "total_size_bytes": total_size,
        "artifact_types": dict(sorted(by_type.items())),
        "newest_artifacts": [asdict(a) for a in newest],
        "signal_counts": {
            "handoff": sum(1 for a in artifacts if a.handoff_signal),
            "dashboard": sum(1 for a in artifacts if a.dashboard_signal),
            "safety": sum(1 for a in artifacts if a.safety_signal),
            "blocked": sum(1 for a in artifacts if a.blocked_signal),
            "sensitive": sum(1 for a in artifacts if a.sensitive_signal),
            "finance": sum(1 for a in artifacts if a.finance_signal),
            "schedule": sum(1 for a in artifacts if a.schedule_signal),
            "documents": sum(1 for a in artifacts if a.document_signal),
            "crm": sum(1 for a in artifacts if a.customer_contact_signal),
        },
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "rollups" / "artifact_summary.json", payload)
    return payload


def hub_dashboard_sections() -> dict[str, Any]:
    payload = {
        "sections": DASHBOARD_SECTIONS,
        "section_count": len(DASHBOARD_SECTIONS),
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "state" / "dashboard_sections.json", payload)
    return payload


def hub_orb_state(
    orb_state: str,
    active_operator: str = "hub",
    active_task: str | None = None,
    active_section: str = "overview",
) -> dict[str, Any]:
    key = str(orb_state or "idle").strip().lower()
    if key not in ORB_STATES:
        key = "idle"

    spec = ORB_STATES[key]
    payload = {
        "hub_status": "active",
        "orb_state": key,
        "orb_state_label": spec["label"],
        "orb_state_description": spec["description"],
        "available_orb_states": list(ORB_STATES.keys()),
        "active_operator": active_operator,
        "active_task": active_task,
        "active_section": active_section,
        "safety_state": spec["safety_state"],
        "last_updated": _utc_now(),
        "safety_boundary": SAFETY_BOUNDARY,
    }
    _write_json(HUB_ROOT / "state" / "hub_state.json", payload)
    hub_activity_event(
        operator=active_operator,
        event_type="orb_state",
        message=f"Orb state set to {key}.",
        status="completed",
    )
    return payload


def hub_open_web() -> dict[str, Any]:
    web_path = HUB_ROOT / "web" / "index.html"
    if not web_path.exists():
        hub_web_build()

    absolute = web_path.resolve()
    try:
        if os.name == "nt":
            os.startfile(str(absolute))  # type: ignore[attr-defined]
        else:
            import webbrowser

            webbrowser.open(absolute.as_uri())
        opened = True
        error = None
    except Exception as exc:
        opened = False
        error = str(exc)

    payload = {
        "status": "opened" if opened else "failed",
        "web_path": str(web_path).replace("\\", "/"),
        "absolute_path": str(absolute),
        "external_action_taken": False,
        "error": error,
        "timestamp": _utc_now(),
    }
    hub_activity_event(
        operator="hub",
        event_type="open_web",
        message="Serena Hub local web shell opened." if opened else "Serena Hub local web shell open failed.",
        status="completed" if opened else "failed",
        artifact_path=str(web_path).replace("\\", "/"),
    )
    return payload


def hub_command_intake(
    command: str,
    operator: str = "hub",
    target_section: str = "overview",
    priority: str = "normal",
) -> dict[str, Any]:
    """Record a local Hub command intake item and update live state."""
    _ensure_base_state()

    safe_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "id": f"command-{safe_id}",
        "command": command,
        "operator": operator,
        "target_section": target_section,
        "priority": priority,
        "status": "received",
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }

    queue_path = HUB_ROOT / "state" / "command_queue.json"
    existing = _safe_read_json(queue_path)
    if not isinstance(existing, dict):
        existing = {"commands": []}
    commands = existing.setdefault("commands", [])
    commands.append(payload)
    existing["commands"] = commands[-100:]
    existing["last_command"] = payload
    existing["timestamp"] = _utc_now()
    _write_json(queue_path, existing)

    hub_orb_state(
        orb_state="thinking",
        active_operator=operator,
        active_task=command,
        active_section=target_section,
    )

    hub_activity_event(
        operator=operator,
        event_type="command_intake",
        message=f"Command received: {command}",
        status="received",
        artifact_path=str(queue_path).replace("\\", "/"),
    )

    return payload


def hub_live_tick(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
    """Refresh rollups/state mirrors for a live served Hub dashboard."""
    _ensure_base_state()
    artifact_summary = hub_artifact_summary(root=root, limit=limit)
    operator_rollup = hub_operator_rollup(root=root, limit=limit)
    crm_rollup = hub_crm_rollup(root=root, limit=limit)
    finance_rollup = hub_finance_rollup(root=root, limit=limit)
    schedule_rollup = hub_schedule_rollup(root=root, limit=limit)
    document_rollup = hub_document_rollup(root=root, limit=limit)
    safety_rollup = hub_safety_rollup(root=root, limit=limit)
    widgets = hub_widget_registry()
    sections = hub_dashboard_sections()

    payload = {
        "status": "live_tick_complete",
        "root": root,
        "limit": limit,
        "artifact_count": artifact_summary.get("artifact_count"),
        "operator_count": operator_rollup.get("operator_count"),
        "crm_count": crm_rollup.get("artifact_count"),
        "finance_count": finance_rollup.get("artifact_count"),
        "schedule_count": schedule_rollup.get("artifact_count"),
        "document_count": document_rollup.get("artifact_count"),
        "safety_count": safety_rollup.get("artifact_count"),
        "widget_count": len(widgets.get("widgets", [])),
        "section_count": len(sections.get("sections", [])),
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }

    _write_json(HUB_ROOT / "state" / "live_tick.json", payload)
    sync = hub_web_sync_data()
    payload["data_sync"] = sync
    _write_json(HUB_ROOT / "state" / "live_tick.json", payload)
    hub_activity_event(
        operator="hub",
        event_type="live_tick",
        message="Hub live dashboard data refreshed.",
        status="completed",
        artifact_path=str(HUB_ROOT / "state" / "live_tick.json").replace("\\", "/"),
    )
    return payload


def hub_web_sync_data() -> dict[str, Any]:
    """Copy Hub state and rollup JSON into web/data for browser fetch."""
    _ensure_base_state()
    hub_widget_registry()
    hub_dashboard_sections()
    hub_artifact_summary()
    hub_operator_rollup()
    hub_crm_rollup()
    hub_finance_rollup()
    hub_schedule_rollup()
    hub_document_rollup()
    hub_safety_rollup()

    web_data = HUB_ROOT / "web" / "data"
    web_data.mkdir(parents=True, exist_ok=True)

    sources = {
        "hub_state.json": HUB_ROOT / "state" / "hub_state.json",
        "widgets.json": HUB_ROOT / "state" / "widgets.json",
        "activity_events.json": HUB_ROOT / "state" / "activity_events.json",
        "approvals.json": HUB_ROOT / "state" / "approvals.json",
        "dashboard_sections.json": HUB_ROOT / "state" / "dashboard_sections.json",
        "command_queue.json": HUB_ROOT / "state" / "command_queue.json",
        "live_tick.json": HUB_ROOT / "state" / "live_tick.json",
        "artifact_summary.json": HUB_ROOT / "rollups" / "artifact_summary.json",
        "operator_rollup.json": HUB_ROOT / "rollups" / "operator_rollup.json",
        "crm_rollup.json": HUB_ROOT / "rollups" / "crm_rollup.json",
        "finance_rollup.json": HUB_ROOT / "rollups" / "finance_rollup.json",
        "schedule_rollup.json": HUB_ROOT / "rollups" / "schedule_rollup.json",
        "document_rollup.json": HUB_ROOT / "rollups" / "document_rollup.json",
        "safety_rollup.json": HUB_ROOT / "rollups" / "safety_rollup.json",
    }

    copied = []
    missing = []

    for name, source in sources.items():
        target = web_data / name
        if source.exists():
            shutil.copyfile(source, target)
            copied.append(str(target).replace("\\", "/"))
        else:
            missing.append(str(source).replace("\\", "/"))

    payload = {
        "status": "synced",
        "web_data_root": str(web_data).replace("\\", "/"),
        "copied_count": len(copied),
        "copied": copied,
        "missing": missing,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }
    _write_json(web_data / "sync_status.json", payload)
    return payload


def hub_serve_web(host: str = "127.0.0.1", port: int = 8765, build: bool = True) -> dict[str, Any]:
    """Serve the local Hub web directory over HTTP for dynamic JSON fetch."""
    if build:
        hub_web_build()
    else:
        hub_web_sync_data()

    web_root = (HUB_ROOT / "web").resolve()
    if not web_root.exists():
        return {
            "status": "failed",
            "reason": "Hub web root does not exist.",
            "web_root": str(web_root),
            "external_action_taken": False,
            "timestamp": _utc_now(),
        }

    class HubHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(web_root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    server = ThreadingHTTPServer((host, int(port)), HubHandler)
    url = f"http://{host}:{int(port)}/index.html"

    print(f"Serena Hub serving at {url}")
    print(f"Web root: {web_root}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return {
        "status": "stopped",
        "url": url,
        "web_root": str(web_root),
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }


def hub_web_build() -> dict[str, Any]:
    _ensure_base_state()
    widget_registry = hub_widget_registry()
    dashboard_sections = hub_dashboard_sections()
    artifact_summary = hub_artifact_summary()
    operator_rollup = hub_operator_rollup()
    safety_rollup = hub_safety_rollup()
    crm_rollup = hub_crm_rollup()
    finance_rollup = hub_finance_rollup()
    schedule_rollup = hub_schedule_rollup()
    document_rollup = hub_document_rollup()

    web_root = HUB_ROOT / "web"
    assets_root = web_root / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    css = """\
:root {
  --bg: #05060a;
  --panel: rgba(10, 18, 32, 0.62);
  --panel2: rgba(1, 7, 18, 0.78);
  --cyan: #00f0ff;
  --blue: #2f7bff;
  --purple: #a020f0;
  --green: #33ff99;
  --amber: #ffcc66;
  --red: #ff4d6d;
  --text: #e8fbff;
  --muted: #89a7b5;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  height: 100vh;
  overflow: hidden;
  font-family: Inter, Segoe UI, system-ui, sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at 50% 42%, rgba(0, 240, 255, .17), transparent 20%),
    radial-gradient(circle at 82% 18%, rgba(160, 32, 240, .15), transparent 25%),
    radial-gradient(circle at 20% 82%, rgba(47, 123, 255, .12), transparent 22%),
    linear-gradient(135deg, #05060a 0%, #0a0a0f 50%, #10111a 100%);
}
body:before {
  content: "";
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,240,255,.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,240,255,.05) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(circle at center, black, transparent 78%);
  pointer-events: none;
}
.shell {
  height: 100vh;
  display: grid;
  grid-template-rows: 58px 1fr 92px;
  grid-template-columns: 235px 1fr 350px;
  gap: 12px;
  padding: 12px;
}
.top, .rail, .stage, .timeline, .chat {
  border: 1px solid rgba(0, 240, 255, .25);
  background: var(--panel);
  backdrop-filter: blur(18px);
  box-shadow: 0 0 30px rgba(0, 240, 255, .08), inset 0 0 32px rgba(255,255,255,.025);
  border-radius: 22px;
}
.top {
  grid-column: 1 / 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  letter-spacing: .08em;
  text-transform: uppercase;
  font-size: 12px;
}
.rail { padding: 16px; overflow: auto; }
.stage { position: relative; overflow: auto; padding: 22px; }
.timeline { padding: 16px; overflow: auto; }
.chat {
  grid-column: 1 / 4;
  display: grid;
  grid-template-columns: 72px 1fr 210px;
  align-items: center;
  gap: 14px;
  padding: 14px;
}
.brand { color: var(--cyan); text-shadow: 0 0 18px var(--cyan); font-weight: 900; }
.pill {
  padding: 7px 10px;
  border: 1px solid rgba(0, 240, 255, .25);
  border-radius: 999px;
  color: var(--muted);
  background: rgba(0,0,0,.2);
}
.operator {
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 14px;
  color: var(--muted);
  background: rgba(255,255,255,.035);
}
.operator.active, .operator:hover {
  color: var(--cyan);
  border-color: rgba(0, 240, 255, .48);
  box-shadow: inset 0 0 18px rgba(0,240,255,.08);
}
.orb {
  position: absolute;
  right: 5%;
  top: 9%;
  width: 118px;
  height: 118px;
  border-radius: 50%;
  background:
    radial-gradient(circle at 38% 36%, #ffffff, var(--cyan) 11%, var(--blue) 32%, rgba(160,32,240,.8) 56%, transparent 72%);
  box-shadow:
    0 0 40px rgba(0,240,255,.95),
    0 0 110px rgba(47,123,255,.48),
    0 0 160px rgba(160,32,240,.32);
  animation: breathe 3.6s ease-in-out infinite;
}
.orb.approval {
  box-shadow: 0 0 42px rgba(255,204,102,.95), 0 0 120px rgba(255,204,102,.35);
}
.orb.blocked {
  box-shadow: 0 0 42px rgba(255,77,109,.95), 0 0 120px rgba(255,77,109,.35);
}
.orb.completed {
  box-shadow: 0 0 42px rgba(51,255,153,.95), 0 0 120px rgba(51,255,153,.35);
}
.orb:before, .orb:after {
  content: "";
  position: absolute;
  inset: -22px;
  border-radius: 50%;
  border: 1px solid rgba(0,240,255,.32);
  animation: spin 8s linear infinite;
}
.orb:after {
  inset: -42px;
  border-color: rgba(160,32,240,.22);
  animation-duration: 13s;
  animation-direction: reverse;
}
@keyframes breathe {
  0%, 100% { filter: brightness(.9); transform: scale(.98); }
  50% { filter: brightness(1.25); transform: scale(1.05); }
}
@keyframes spin { to { rotate: 360deg; } }
.hero {
  max-width: 720px;
  padding: 22px;
  border-radius: 24px;
  border: 1px solid rgba(0,240,255,.17);
  background: linear-gradient(135deg, rgba(0,240,255,.08), rgba(160,32,240,.06));
}
.hero h1 { margin: 0; font-size: 38px; letter-spacing: -.03em; }
.hero p { color: var(--muted); line-height: 1.6; }
.state-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.state {
  font-size: 11px;
  color: var(--muted);
  border: 1px solid rgba(255,255,255,.1);
  padding: 6px 8px;
  border-radius: 999px;
  background: rgba(0,0,0,.22);
}
.state.active { color: var(--cyan); border-color: rgba(0,240,255,.5); }
.widget-grid {
  position: relative;
  margin-top: 18px;
  padding-right: 150px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.widget {
  min-height: 132px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(0,240,255,.18);
  background: var(--panel2);
  box-shadow: 0 16px 60px rgba(0,0,0,.22);
}
.widget h3 { margin: 0 0 8px; color: var(--cyan); }
.metric { font-size: 34px; font-weight: 900; }
.muted { color: var(--muted); font-size: 13px; line-height: 1.5; }
.event {
  border-left: 2px solid var(--cyan);
  padding: 8px 0 8px 12px;
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 13px;
  word-break: break-word;
}
.event b { color: var(--text); }
.input {
  height: 46px;
  border-radius: 999px;
  border: 1px solid rgba(0,240,255,.25);
  background: rgba(0,0,0,.28);
  display: flex;
  align-items: center;
  padding: 0 18px;
  color: var(--muted);
}
.mic {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(0,240,255,.12);
  color: var(--cyan);
  border: 1px solid rgba(0,240,255,.35);
  box-shadow: 0 0 22px rgba(0,240,255,.22);
}
@media (max-width: 1100px) {
  .shell { grid-template-columns: 190px 1fr; }
  .timeline { display: none; }
  .top, .chat { grid-column: 1 / 3; }
  .widget-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
"""

    js = """\
const dataFiles = {
  hubState: "data/hub_state.json",
  widgets: "data/widgets.json",
  activity: "data/activity_events.json",
  sections: "data/dashboard_sections.json",
  commandQueue: "data/command_queue.json",
  liveTick: "data/live_tick.json",
  artifactSummary: "data/artifact_summary.json",
  operatorRollup: "data/operator_rollup.json",
  crmRollup: "data/crm_rollup.json",
  financeRollup: "data/finance_rollup.json",
  scheduleRollup: "data/schedule_rollup.json",
  documentRollup: "data/document_rollup.json",
  safetyRollup: "data/safety_rollup.json"
};

async function loadJson(path) {
  const response = await fetch(path + "?t=" + Date.now(), { cache: "no-store" });
  if (!response.ok) throw new Error(path + " failed: " + response.status);
  return response.json();
}

async function loadAll() {
  const entries = await Promise.all(
    Object.entries(dataFiles).map(async ([key, path]) => {
      try { return [key, await loadJson(path)]; }
      catch (error) { return [key, { error: String(error) }]; }
    })
  );
  return Object.fromEntries(entries);
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderSections(sections, activeSection) {
  const rail = document.getElementById("operatorRail");
  if (!rail) return;
  const list = sections?.sections || [];
  rail.innerHTML = list.map(section => `
    <div class="operator ${section.id === activeSection ? "active" : ""}">
      ${section.title}
      <div class="muted">${section.operator}</div>
    </div>
  `).join("");
}

function renderOrb(state) {
  const orb = document.getElementById("serenaOrb");
  if (!orb) return;
  const key = state?.orb_state || "idle";
  orb.className = "orb " + key;
  setText("voiceState", "Voice: " + key);
  setText("activeOperator", "Active Operator: " + (state?.active_operator || "hub"));
  setText("safetyState", "Safety: " + (state?.safety_state || "green") + " / local-only");
  setText("orbPill", "Orb state: " + key);
  setText("heroTitle", "Serena Command Center");
  setText("heroText", state?.active_task || state?.orb_state_description || "Local-first operating cockpit.");
  document.querySelectorAll(".state").forEach(el => {
    el.classList.toggle("active", el.textContent === key);
  });
}

function metricCard(title, metric, description) {
  return `
    <div class="widget">
      <h3>${title}</h3>
      <div class="metric">${metric ?? 0}</div>
      <div class="muted">${description}</div>
    </div>
  `;
}

function renderMetrics(data) {
  const grid = document.getElementById("widgetGrid");
  if (!grid) return;
  grid.innerHTML = [
    metricCard("Operators", data.operatorRollup?.operator_count, "Local operator sources discovered."),
    metricCard("CRM Signals", data.crmRollup?.artifact_count, "Contact, customer, lead, lifecycle artifacts."),
    metricCard("Safety", data.safetyRollup?.artifact_count, "Blocked, approval, sensitive-signal artifacts."),
    metricCard("Finance", data.financeRollup?.artifact_count, "Accounting, revenue, billing, invoice signals."),
    metricCard("Schedule", data.scheduleRollup?.artifact_count, "Calendar, booking, appointment signals."),
    metricCard("Documents", data.documentRollup?.artifact_count, "Docs, files, PDF, and Drive signals."),
  ].join("");
}

function renderTimeline(data) {
  const timeline = document.getElementById("timeline");
  if (!timeline) return;

  const events = (data.activity?.events || []).slice(-8).reverse();
  const newest = data.artifactSummary?.newest_artifacts || [];

  const eventHtml = events.map(event => `
    <div class="event">
      <b>${event.operator || "hub"} | ${event.status || "event"}</b><br>
      <span>${event.event_type || "event"}: ${event.message || ""}</span>
    </div>
  `).join("");

  const newestHtml = newest.slice(0, 5).map(item => `
    <div class="event">
      <b>${item.operator || "unknown"} | ${item.artifact_type || "artifact"}</b><br>
      <span>${item.path || ""}</span>
    </div>
  `).join("");

  const lastCommand = data.commandQueue?.last_command;
  const liveTick = data.liveTick;

  timeline.innerHTML = `
    <h3>Activity Timeline</h3>
    <div class="event"><b>Dynamic State</b><br><span>Reading local JSON over HTTP every 3 seconds.</span></div>
    ${lastCommand ? `<div class="event"><b>Latest Command</b><br><span>${lastCommand.command}</span></div>` : ""}
    ${liveTick?.timestamp ? `<div class="event"><b>Live Tick</b><br><span>${liveTick.status} at ${liveTick.timestamp}</span></div>` : ""}
    ${eventHtml || '<div class="event">No activity events yet.</div>'}
    <h3>Newest Artifacts</h3>
    ${newestHtml || '<div class="event">No artifacts found.</div>'}
  `;
}

async function refresh() {
  const data = await loadAll();
  renderOrb(data.hubState);
  renderSections(data.sections, data.hubState?.active_section || "overview");
  renderMetrics(data);
  renderTimeline(data);
  setText("syncStatus", "Last refresh: " + new Date().toLocaleTimeString());
}

refresh();
setInterval(refresh, 3000);
"""

    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Serena Hub Command Center</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="assets/hub.css">
</head>
<body>
  <main class="shell">
    <section class="top">
      <div><span class="brand">SERENA HUB</span> | Dynamic Command Center</div>
      <div class="pill" id="voiceState">Voice: loading</div>
      <div class="pill" id="safetyState">Safety: loading</div>
      <div class="pill" id="activeOperator">Active Operator: loading</div>
    </section>

    <aside class="rail" id="operatorRail">
      <div class="operator active">Loading sections...</div>
    </aside>

    <section class="stage">
      <div class="orb" id="serenaOrb" aria-label="Serena Orb"></div>
      <div class="hero">
        <h1 id="heroTitle">Serena Command Center</h1>
        <p id="heroText">Loading local Hub state...</p>
        <div class="state-row">
          <span class="state">idle</span>
          <span class="state">wake</span>
          <span class="state">listening</span>
          <span class="state">thinking</span>
          <span class="state">speaking</span>
          <span class="state">working</span>
          <span class="state">approval</span>
          <span class="state">blocked</span>
          <span class="state">completed</span>
        </div>
      </div>

      <div class="widget-grid" id="widgetGrid">
        <div class="widget"><h3>Loading</h3><div class="metric">...</div><div class="muted">Reading local JSON.</div></div>
      </div>
    </section>

    <aside class="timeline" id="timeline">
      <h3>Activity Timeline</h3>
      <div class="event">Loading activity events...</div>
    </aside>

    <section class="chat">
      <div class="mic">ORB</div>
      <div class="input">Dynamic local Hub. Use serena hub serve so browser JSON fetch works.</div>
      <div class="pill" id="orbPill">Orb state: loading</div>
    </section>
  </main>
  <script src="assets/hub.js"></script>
</body>
</html>
"""

    (assets_root / "hub.css").write_text(css, encoding="utf-8")
    (assets_root / "hub.js").write_text(js, encoding="utf-8")
    (web_root / "index.html").write_text(html, encoding="utf-8")

    sync_payload = hub_web_sync_data()

    hub_activity_event(
        operator="hub",
        event_type="web_build",
        message="Local Serena Hub Batch 3 dynamic web shell generated.",
        status="completed",
        artifact_path=str(web_root / "index.html").replace("\\", "/"),
    )

    return {
        "status": "built",
        "web_path": str(web_root / "index.html").replace("\\", "/"),
        "css_path": str(assets_root / "hub.css").replace("\\", "/"),
        "js_path": str(assets_root / "hub.js").replace("\\", "/"),
        "data_sync": sync_payload,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }


__all__ = [
    "hub_status",
    "hub_env_check",
    "hub_source_list",
    "hub_artifact_index",
    "hub_operator_rollup",
    "hub_crm_rollup",
    "hub_finance_rollup",
    "hub_schedule_rollup",
    "hub_document_rollup",
    "hub_safety_rollup",
    "hub_widget_registry",
    "hub_artifact_summary",
    "hub_dashboard_sections",
    "hub_orb_state",
    "hub_open_web",
    "hub_command_intake",
    "hub_live_tick",
    "hub_web_sync_data",
    "hub_serve_web",
    "hub_web_build",
    "hub_chat_request",
    "hub_activity_event",
    "hub_action_routing_plan",
    "hub_blocked_unapproved_action",
]
