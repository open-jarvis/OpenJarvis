from pathlib import Path

path = Path("src/openjarvis/tools/serena_hub.py")
text = path.read_text(encoding="utf-8")

start = text.index("def _ensure_base_state()")
end = text.index("def hub_activity_event(")

replacement = r'''def _default_hub_state() -> dict[str, Any]:
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


'''

text = text[:start] + replacement + text[end:]

path.write_text(text, encoding="utf-8")
print("[OK] Patched Hub state preservation")