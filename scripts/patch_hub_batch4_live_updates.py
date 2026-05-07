from pathlib import Path

ROOT = Path.cwd()
tool_path = ROOT / "src" / "openjarvis" / "tools" / "serena_hub.py"
cli_path = ROOT / "src" / "openjarvis" / "cli" / "hub_cmd.py"

tool = tool_path.read_text(encoding="utf-8")
cli = cli_path.read_text(encoding="utf-8")

# -----------------------------
# 1. Patch _write_json to mirror state/rollups into web/data
# -----------------------------
old_write = '''def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
'''

new_write = r'''def _mirror_web_data(path: Path, payload: dict[str, Any]) -> None:
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
'''

if old_write not in tool:
    raise SystemExit("[ERROR] Could not find _write_json block to patch.")
tool = tool.replace(old_write, new_write)

# -----------------------------
# 2. Add command intake + live tick before hub_web_sync_data
# -----------------------------
insert_before = tool.index("def hub_web_sync_data()")

batch4_functions = r'''def hub_command_intake(
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

    sync = hub_web_sync_data()

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
        "data_sync": sync,
        "external_action_taken": False,
        "timestamp": _utc_now(),
    }

    _write_json(HUB_ROOT / "state" / "live_tick.json", payload)
    hub_activity_event(
        operator="hub",
        event_type="live_tick",
        message="Hub live dashboard data refreshed.",
        status="completed",
        artifact_path=str(HUB_ROOT / "state" / "live_tick.json").replace("\\", "/"),
    )
    return payload


'''

if "def hub_command_intake(" not in tool:
    tool = tool[:insert_before] + batch4_functions + tool[insert_before:]

# -----------------------------
# 3. Update web sync sources to include command_queue/live_tick
# -----------------------------
sync_marker = '''        "dashboard_sections.json": HUB_ROOT / "state" / "dashboard_sections.json",
        "artifact_summary.json": HUB_ROOT / "rollups" / "artifact_summary.json",
'''

sync_replacement = '''        "dashboard_sections.json": HUB_ROOT / "state" / "dashboard_sections.json",
        "command_queue.json": HUB_ROOT / "state" / "command_queue.json",
        "live_tick.json": HUB_ROOT / "state" / "live_tick.json",
        "artifact_summary.json": HUB_ROOT / "rollups" / "artifact_summary.json",
'''

if sync_marker in tool and '"command_queue.json": HUB_ROOT / "state" / "command_queue.json",' not in tool:
    tool = tool.replace(sync_marker, sync_replacement)

# -----------------------------
# 4. Ensure command_queue exists in base state initializer
# -----------------------------
base_marker = '''    for name in ["activity_events", "approvals"]:
        path = HUB_ROOT / "state" / f"{name}.json"
        if not path.exists():
            _write_json(path, {"events" if name == "activity_events" else "approvals": []})
'''

base_replacement = '''    for name in ["activity_events", "approvals"]:
        path = HUB_ROOT / "state" / f"{name}.json"
        if not path.exists():
            _write_json(path, {"events" if name == "activity_events" else "approvals": []})

    command_queue_path = HUB_ROOT / "state" / "command_queue.json"
    if not command_queue_path.exists():
        _write_json(command_queue_path, {"commands": [], "last_command": None, "timestamp": _utc_now()})
'''

if base_marker in tool and "command_queue_path = HUB_ROOT" not in tool:
    tool = tool.replace(base_marker, base_replacement)

# -----------------------------
# 5. Patch JS data files and render timeline for command queue/live tick
# -----------------------------
if 'commandQueue: "data/command_queue.json",' not in tool:
    tool = tool.replace(
        '  sections: "data/dashboard_sections.json",\n',
        '  sections: "data/dashboard_sections.json",\n  commandQueue: "data/command_queue.json",\n  liveTick: "data/live_tick.json",\n',
    )

old_timeline_header = '''  timeline.innerHTML = `
    <h3>Activity Timeline</h3>
    <div class="event"><b>Dynamic State</b><br><span>Reading local JSON over HTTP every 3 seconds.</span></div>
    ${eventHtml || '<div class="event">No activity events yet.</div>'}
    <h3>Newest Artifacts</h3>
    ${newestHtml || '<div class="event">No artifacts found.</div>'}
  `;'''

new_timeline_header = '''  const lastCommand = data.commandQueue?.last_command;
  const liveTick = data.liveTick;

  timeline.innerHTML = `
    <h3>Activity Timeline</h3>
    <div class="event"><b>Dynamic State</b><br><span>Reading local JSON over HTTP every 3 seconds.</span></div>
    ${lastCommand ? `<div class="event"><b>Latest Command</b><br><span>${lastCommand.command}</span></div>` : ""}
    ${liveTick?.timestamp ? `<div class="event"><b>Live Tick</b><br><span>${liveTick.status} at ${liveTick.timestamp}</span></div>` : ""}
    ${eventHtml || '<div class="event">No activity events yet.</div>'}
    <h3>Newest Artifacts</h3>
    ${newestHtml || '<div class="event">No artifacts found.</div>'}
  `;'''

if old_timeline_header in tool:
    tool = tool.replace(old_timeline_header, new_timeline_header)

# -----------------------------
# 6. Update __all__
# -----------------------------
for name in ["hub_command_intake", "hub_live_tick"]:
    if f'"{name}",' not in tool:
        tool = tool.replace('    "hub_web_sync_data",\n', f'    "{name}",\n    "hub_web_sync_data",\n')

tool_path.write_text(tool, encoding="utf-8")

# -----------------------------
# 7. Patch CLI imports
# -----------------------------
for name in [
    "    hub_command_intake,\n",
    "    hub_live_tick,\n",
]:
    if name not in cli:
        cli = cli.replace("    hub_chat_request,\n", "    hub_chat_request,\n" + name)

# -----------------------------
# 8. Add CLI commands before chat-request
# -----------------------------
chat_marker = '@hub.command("chat-request")\n@click.argument("message")\n'
commands = r'''@hub.command("command-intake")
@click.argument("command")
@click.option("--operator", default="hub")
@click.option("--target-section", default="overview")
@click.option("--priority", default="normal")
def command_intake(command, operator, target_section, priority):
    """Record a local Hub command intake item and update live dashboard state."""
    _print(
        hub_command_intake(
            command=command,
            operator=operator,
            target_section=target_section,
            priority=priority,
        )
    )


@hub.command("live-tick")
@click.option("--root", default="outputs")
@click.option("--limit", default=300, type=int)
def live_tick(root, limit):
    """Refresh live Hub dashboard JSON mirrors."""
    _print(hub_live_tick(root=root, limit=limit))


'''

if '@hub.command("command-intake")' not in cli:
    cli = cli.replace(chat_marker, commands + chat_marker)

cli_path.write_text(cli, encoding="utf-8")

print("[OK] Patched Serena Hub Batch 4 live updates")
print("[OK] Added command-intake and live-tick CLI commands")