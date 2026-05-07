from pathlib import Path

path = Path("src/openjarvis/tools/serena_hub.py")
text = path.read_text(encoding="utf-8")

old = '''    sync = hub_web_sync_data()

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
'''

new = '''    payload = {
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
'''

if old not in text:
    raise SystemExit("[ERROR] Could not find live_tick sync block.")

text = text.replace(old, new)
path.write_text(text, encoding="utf-8")

print("[OK] Patched live_tick sync order")