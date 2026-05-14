from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

# -----------------------------
# 1. Add Hub Batch 2 constants
# -----------------------------
constants_marker = '''SAFETY_BOUNDARY = {
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
'''

constants_add = constants_marker + '''

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
'''

if "ORB_STATES =" not in tool:
    tool = tool.replace(constants_marker, constants_add)

# -----------------------------
# 2. Replace widget registry
# -----------------------------
start = tool.index("def hub_widget_registry()")
end = tool.index("def _ensure_base_state()")

new_widget_registry = r'''def hub_widget_registry() -> dict[str, Any]:
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


'''

tool = tool[:start] + new_widget_registry + tool[end:]

# -----------------------------
# 3. Replace base state
# -----------------------------
start = tool.index("def _ensure_base_state()")
end = tool.index("def hub_activity_event(")

new_base_state = r'''def _ensure_base_state() -> None:
    state = {
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
    _write_json(HUB_ROOT / "state" / "hub_state.json", state)

    for name in ["activity_events", "approvals"]:
        path = HUB_ROOT / "state" / f"{name}.json"
        if not path.exists():
            _write_json(path, {"events" if name == "activity_events" else "approvals": []})


'''

tool = tool[:start] + new_base_state + tool[end:]

# -----------------------------
# 4. Add Batch 2 functions before hub_web_build
# -----------------------------
insert_before = tool.index("def hub_web_build()")

batch2_functions = r'''def hub_artifact_summary(root: str = "outputs", limit: int = 300) -> dict[str, Any]:
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


'''

tool = tool[:insert_before] + batch2_functions + tool[insert_before:]

# -----------------------------
# 5. Replace web build
# -----------------------------
start = tool.index("def hub_web_build()")
end = tool.index("\n\n__all__ = [")

new_web_build = r'''def hub_web_build() -> dict[str, Any]:
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

    newest = artifact_summary.get("newest_artifacts", [])[:5]
    newest_html = "\n".join(
        f'<div class="event"><b>{item.get("operator", "unknown")}</b><br><span>{item.get("artifact_type", "artifact")} | {item.get("path", "")}</span></div>'
        for item in newest
    ) or '<div class="event">No local artifacts found yet.</div>'

    section_html = "\n".join(
        f'<div class="operator" data-section="{section["id"]}">{section["title"]}</div>'
        for section in dashboard_sections.get("sections", [])
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Serena Hub Command Center</title>
  <style>
    :root {{
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
    }}
    * {{ box-sizing: border-box; }}
    body {{
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
    }}
    body:before {{
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(0,240,255,.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,240,255,.05) 1px, transparent 1px);
      background-size: 44px 44px;
      mask-image: radial-gradient(circle at center, black, transparent 78%);
      pointer-events: none;
    }}
    .shell {{
      height: 100vh;
      display: grid;
      grid-template-rows: 58px 1fr 92px;
      grid-template-columns: 235px 1fr 350px;
      gap: 12px;
      padding: 12px;
    }}
    .top, .rail, .stage, .timeline, .chat {{
      border: 1px solid rgba(0, 240, 255, .25);
      background: var(--panel);
      backdrop-filter: blur(18px);
      box-shadow: 0 0 30px rgba(0, 240, 255, .08), inset 0 0 32px rgba(255,255,255,.025);
      border-radius: 22px;
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
      grid-template-columns: 72px 1fr 210px;
      align-items: center;
      gap: 14px;
      padding: 14px;
    }}
    .brand {{ color: var(--cyan); text-shadow: 0 0 18px var(--cyan); font-weight: 900; }}
    .pill {{
      padding: 7px 10px;
      border: 1px solid rgba(0, 240, 255, .25);
      border-radius: 999px;
      color: var(--muted);
      background: rgba(0,0,0,.2);
    }}
    .operator {{
      padding: 10px 12px;
      margin-bottom: 8px;
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 14px;
      color: var(--muted);
      background: rgba(255,255,255,.035);
    }}
    .operator:first-child, .operator:hover {{
      color: var(--cyan);
      border-color: rgba(0, 240, 255, .48);
      box-shadow: inset 0 0 18px rgba(0,240,255,.08);
    }}
    .orb {{
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
      0%, 100% {{ filter: brightness(.9); transform: scale(.98); }}
      50% {{ filter: brightness(1.25); transform: scale(1.05); }}
    }}
    @keyframes spin {{ to {{ rotate: 360deg; }} }}
    .hero {{
      max-width: 720px;
      padding: 22px;
      border-radius: 24px;
      border: 1px solid rgba(0,240,255,.17);
      background: linear-gradient(135deg, rgba(0,240,255,.08), rgba(160,32,240,.06));
    }}
    .hero h1 {{ margin: 0; font-size: 38px; letter-spacing: -.03em; }}
    .hero p {{ color: var(--muted); line-height: 1.6; }}
    .state-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .state {{
      font-size: 11px;
      color: var(--muted);
      border: 1px solid rgba(255,255,255,.1);
      padding: 6px 8px;
      border-radius: 999px;
      background: rgba(0,0,0,.22);
    }}
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
      min-height: 132px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(0,240,255,.18);
      background: var(--panel2);
      box-shadow: 0 16px 60px rgba(0,0,0,.22);
    }}
    .widget h3 {{ margin: 0 0 8px; color: var(--cyan); }}
    .metric {{ font-size: 34px; font-weight: 900; }}
    .muted {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .event {{
      border-left: 2px solid var(--cyan);
      padding: 8px 0 8px 12px;
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      word-break: break-word;
    }}
    .event b {{ color: var(--text); }}
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
      box-shadow: 0 0 22px rgba(0,240,255,.22);
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
      {section_html}
    </aside>

    <section class="stage">
      <div class="orb" aria-label="Serena Orb"></div>
      <div class="hero">
        <h1>Serena Command Center</h1>
        <p>Local-first operating cockpit. The orb remains Serena's visible presence while widgets show CRM, finance, schedule, document, operator, and safety work.</p>
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
      <div class="event"><b>Web shell</b><br><span>Generated locally under outputs/hub/web/index.html</span></div>
      <div class="event"><b>Widget registry</b><br><span>{len(widget_registry.get("widgets", []))} widgets across {len(dashboard_sections.get("sections", []))} sections.</span></div>
      <div class="event"><b>Safety</b><br><span>External writes disabled in Hub v1.</span></div>
      {newest_html}
    </aside>

    <section class="chat">
      <div class="mic">ORB</div>
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
    hub_activity_event(operator="hub", event_type="web_build", message="Local Serena Hub Batch 2 web shell generated.", status="completed", artifact_path=str(web_path).replace("\\", "/"))
    return {
        "status": "built",
        "web_path": str(web_path).replace("\\", "/"),
        "external_action_taken": False,
        "artifact_summary_path": str(HUB_ROOT / "rollups" / "artifact_summary.json").replace("\\", "/"),
        "dashboard_sections_path": str(HUB_ROOT / "state" / "dashboard_sections.json").replace("\\", "/"),
        "timestamp": _utc_now(),
    }
'''

tool = tool[:start] + new_web_build + tool[end:]

# -----------------------------
# 6. Update __all__
# -----------------------------
for name in [
    "hub_artifact_summary",
    "hub_dashboard_sections",
    "hub_orb_state",
    "hub_open_web",
]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_web_build",\n', f'    "{name}",\n    "hub_web_build",\n')

tool_path.write_text(tool, encoding="utf-8")

# -----------------------------
# 7. Patch CLI imports
# -----------------------------
import_marker = "    hub_artifact_index,\n"
for name in [
    "    hub_artifact_summary,\n",
    "    hub_dashboard_sections,\n",
    "    hub_open_web,\n",
    "    hub_orb_state,\n",
]:
    if name not in cli:
        cli = cli.replace(import_marker, import_marker + name)

# -----------------------------
# 8. Add CLI commands before web-build
# -----------------------------
web_marker = '@hub.command("web-build")\ndef web_build():\n'
commands = r'''@hub.command("artifact-summary")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def artifact_summary(root, limit):
    """Create safer compact local artifact summary."""
    _print(hub_artifact_summary(root=root, limit=limit))


@hub.command("dashboard-sections")
def dashboard_sections():
    """Create local Hub dashboard section registry."""
    _print(hub_dashboard_sections())


@hub.command("orb-state")
@click.option("--state", "orb_state", required=True)
@click.option("--active-operator", default="hub")
@click.option("--active-task", default=None)
@click.option("--active-section", default="overview")
def orb_state(orb_state, active_operator, active_task, active_section):
    """Set local Hub orb state for visual/demo testing."""
    _print(
        hub_orb_state(
            orb_state=orb_state,
            active_operator=active_operator,
            active_task=active_task,
            active_section=active_section,
        )
    )


@hub.command("open")
def open_web():
    """Open local Serena Hub web shell."""
    _print(hub_open_web())


'''

if '@hub.command("artifact-summary")' not in cli:
    cli = cli.replace(web_marker, commands + web_marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 2 state/web functions")
print("[OK] Added artifact-summary, dashboard-sections, orb-state, and open CLI commands")