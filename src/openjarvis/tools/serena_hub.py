"""Serena Hub / Command Center local-first operator.

Hub v1 is a read-only local aggregator and local web-state generator.
It indexes local operator outputs, creates local rollups, creates local
Hub state files, and generates a static local command-center web shell.

Hub v1 does not mutate upstream operators or external systems.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
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


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
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
    widgets = [
        "voice_orb_widget",
        "chat_widget",
        "activity_timeline_widget",
        "operator_status_widget",
        "crm_contact_widget",
        "crm_lead_widget",
        "crm_lifecycle_widget",
        "membership_widget",
        "calendar_schedule_widget",
        "bookings_widget",
        "document_editor_widget",
        "google_docs_widget",
        "drive_file_widget",
        "browser_search_widget",
        "image_generation_widget",
        "video_generation_widget",
        "wordpress_page_widget",
        "accounting_summary_widget",
        "reporting_widget",
        "analytics_widget",
        "safety_block_widget",
        "approval_request_widget",
        "hub_router_widget",
    ]
    payload = {
        "widgets": [
            {
                "id": widget,
                "type": widget,
                "title": widget.replace("_", " ").title(),
                "enabled": True,
                "state": "available",
            }
            for widget in widgets
        ],
        "timestamp": _utc_now(),
    }
    _write_json(HUB_ROOT / "state" / "widgets.json", payload)
    return payload


def _ensure_base_state() -> None:
    state = {
        "hub_status": "active",
        "orb_state": "idle",
        "active_operator": "hub",
        "active_task": None,
        "safety_state": "green",
        "last_updated": _utc_now(),
        "safety_boundary": SAFETY_BOUNDARY,
    }
    _write_json(HUB_ROOT / "state" / "hub_state.json", state)

    for name in ["activity_events", "approvals"]:
        path = HUB_ROOT / "state" / f"{name}.json"
        if not path.exists():
            _write_json(path, {"events" if name == "activity_events" else "approvals": []})


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


def hub_web_build() -> dict[str, Any]:
    _ensure_base_state()
    widget_registry = hub_widget_registry()
    operator_rollup = hub_operator_rollup()
    safety_rollup = hub_safety_rollup()
    crm_rollup = hub_crm_rollup()
    finance_rollup = hub_finance_rollup()
    schedule_rollup = hub_schedule_rollup()
    document_rollup = hub_document_rollup()

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Serena Hub Command Center</title>
  <style>
    :root {{
      --bg: #05060a;
      --panel: rgba(10, 18, 32, 0.58);
      --cyan: #00f0ff;
      --blue: #2f7bff;
      --purple: #a020f0;
      --green: #33ff99;
      --amber: #ffcc66;
      --red: #ff4d6d;
      --text: #e8fbff;
      --muted: #89a7b5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      height: 100vh;
      overflow: hidden;
      font-family: Inter, Segoe UI, system-ui, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 50% 45%, rgba(0, 240, 255, .15), transparent 24%),
        radial-gradient(circle at 80% 20%, rgba(160, 32, 240, .12), transparent 26%),
        linear-gradient(135deg, #05060a 0%, #0a0a0f 50%, #10111a 100%);
    }}
    .shell {{
      height: 100vh;
      display: grid;
      grid-template-rows: 56px 1fr 88px;
      grid-template-columns: 220px 1fr 320px;
      gap: 12px;
      padding: 12px;
    }}
    .top, .rail, .stage, .timeline, .chat {{
      border: 1px solid rgba(0, 240, 255, .25);
      background: var(--panel);
      backdrop-filter: blur(18px);
      box-shadow: 0 0 30px rgba(0, 240, 255, .08);
      border-radius: 20px;
    }}
    .top {{
      grid-column: 1 / 4;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      letter-spacing: .08em;
      text-transform: uppercase;
      font-size: 12px;
    }}
    .rail {{ padding: 16px; overflow: auto; }}
    .stage {{ position: relative; overflow: hidden; padding: 22px; }}
    .timeline {{ padding: 16px; overflow: auto; }}
    .chat {{
      grid-column: 1 / 4;
      display: grid;
      grid-template-columns: 72px 1fr 180px;
      align-items: center;
      gap: 14px;
      padding: 14px;
    }}
    .brand {{ color: var(--cyan); text-shadow: 0 0 18px var(--cyan); font-weight: 800; }}
    .pill {{
      padding: 7px 10px;
      border: 1px solid rgba(0, 240, 255, .25);
      border-radius: 999px;
      color: var(--muted);
    }}
    .operator {{
      padding: 10px 12px;
      margin-bottom: 8px;
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 14px;
      color: var(--muted);
      background: rgba(255,255,255,.03);
    }}
    .operator.active {{
      color: var(--cyan);
      border-color: rgba(0, 240, 255, .45);
      box-shadow: inset 0 0 18px rgba(0,240,255,.08);
    }}
    .orb {{
      position: absolute;
      left: 50%;
      top: 45%;
      width: min(22vw, 250px);
      height: min(22vw, 250px);
      transform: translate(-50%, -50%);
      border-radius: 50%;
      background:
        radial-gradient(circle at 38% 36%, #ffffff, var(--cyan) 11%, var(--blue) 32%, rgba(160,32,240,.8) 56%, transparent 72%);
      box-shadow:
        0 0 40px rgba(0,240,255,.95),
        0 0 110px rgba(47,123,255,.48),
        0 0 160px rgba(160,32,240,.32);
      animation: breathe 3.6s ease-in-out infinite;
    }}
    .orb:before, .orb:after {{
      content: "";
      position: absolute;
      inset: -22px;
      border-radius: 50%;
      border: 1px solid rgba(0,240,255,.32);
      animation: spin 8s linear infinite;
    }}
    .orb:after {{
      inset: -42px;
      border-color: rgba(160,32,240,.22);
      animation-duration: 13s;
      animation-direction: reverse;
    }}
    @keyframes breathe {{
      0%, 100% {{ filter: brightness(.9); transform: translate(-50%, -50%) scale(.98); }}
      50% {{ filter: brightness(1.25); transform: translate(-50%, -50%) scale(1.04); }}
    }}
    @keyframes spin {{ to {{ rotate: 360deg; }} }}
    .widget-grid {{
      position: absolute;
      left: 24px;
      right: 24px;
      bottom: 24px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .widget {{
      min-height: 128px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(0,240,255,.18);
      background: rgba(5, 8, 18, .62);
    }}
    .widget h3 {{ margin: 0 0 8px; color: var(--cyan); }}
    .metric {{ font-size: 34px; font-weight: 800; }}
    .muted {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .event {{
      border-left: 2px solid var(--cyan);
      padding: 8px 0 8px 12px;
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .input {{
      height: 46px;
      border-radius: 999px;
      border: 1px solid rgba(0,240,255,.25);
      background: rgba(0,0,0,.28);
      display: flex;
      align-items: center;
      padding: 0 18px;
      color: var(--muted);
    }}
    .mic {{
      width: 48px;
      height: 48px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: rgba(0,240,255,.12);
      color: var(--cyan);
      border: 1px solid rgba(0,240,255,.35);
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="top">
      <div><span class="brand">SERENA HUB</span> | Command Center Online</div>
      <div class="pill">Voice: idle</div>
      <div class="pill">Safety: green / local-only</div>
      <div class="pill">Active Operator: hub</div>
    </section>

    <aside class="rail">
      <div class="operator active">Command Center</div>
      <div class="operator">CRM</div>
      <div class="operator">Calendar / Bookings</div>
      <div class="operator">Documents / Files</div>
      <div class="operator">WordPress</div>
      <div class="operator">Finance</div>
      <div class="operator">Reports</div>
      <div class="operator">Safety / Approvals</div>
    </aside>

    <section class="stage">
      <div class="orb" aria-label="Serena Orb"></div>
      <div class="widget-grid">
        <div class="widget"><h3>Operators</h3><div class="metric">{operator_rollup.get("operator_count", 0)}</div><div class="muted">Local operator sources discovered.</div></div>
        <div class="widget"><h3>CRM Signals</h3><div class="metric">{crm_rollup.get("artifact_count", 0)}</div><div class="muted">Contact, customer, lead, and lifecycle artifacts.</div></div>
        <div class="widget"><h3>Safety</h3><div class="metric">{safety_rollup.get("artifact_count", 0)}</div><div class="muted">Blocked, approval, and sensitive-signal artifacts.</div></div>
        <div class="widget"><h3>Finance</h3><div class="metric">{finance_rollup.get("artifact_count", 0)}</div><div class="muted">Accounting, revenue, billing, invoice signals.</div></div>
        <div class="widget"><h3>Schedule</h3><div class="metric">{schedule_rollup.get("artifact_count", 0)}</div><div class="muted">Calendar, booking, and appointment signals.</div></div>
        <div class="widget"><h3>Documents</h3><div class="metric">{document_rollup.get("artifact_count", 0)}</div><div class="muted">Docs, files, PDF, and Drive signals.</div></div>
      </div>
    </section>

    <aside class="timeline">
      <h3>Activity Timeline</h3>
      <div class="event">Hub web shell generated locally.</div>
      <div class="event">Widget registry initialized: {len(widget_registry.get("widgets", []))} widgets.</div>
      <div class="event">External writes disabled in Hub v1.</div>
    </aside>

    <section class="chat">
      <div class="mic">●</div>
      <div class="input">Speak or type a Serena command. v1 records local chat request artifacts only.</div>
      <div class="pill">Orb state: idle</div>
    </section>
  </main>
</body>
</html>
"""
    web_path = HUB_ROOT / "web" / "index.html"
    web_path.parent.mkdir(parents=True, exist_ok=True)
    web_path.write_text(html, encoding="utf-8")
    hub_activity_event(operator="hub", event_type="web_build", message="Local Serena Hub web shell generated.", status="completed", artifact_path=str(web_path).replace("\\", "/"))
    return {
        "status": "built",
        "web_path": str(web_path).replace("\\", "/"),
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
    "hub_web_build",
    "hub_chat_request",
    "hub_activity_event",
    "hub_action_routing_plan",
    "hub_blocked_unapproved_action",
]
