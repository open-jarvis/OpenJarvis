"""Personal Jarvis cockpit routes backed by jarvis-personal runtime files."""

from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

router = APIRouter(prefix="/v1/personal-cockpit", tags=["personal-cockpit"])

PERSONAL_ROOT = Path.home() / ".openjarvis" / "jarvis-personal"
VOICE_DIR = PERSONAL_ROOT / "runtime" / "voice"
WORKING_DIR = PERSONAL_ROOT / "memory" / "working"
INTEGRATIONS_DIR = PERSONAL_ROOT / "integrations"

STATE_PATH = VOICE_DIR / "v4_state.json"
SESSIONS_PATH = VOICE_DIR / "v4_sessions.jsonl"
ACTIONS_PATH = VOICE_DIR / "v4_action_queue.jsonl"
LIVE_BRIEF_PATH = VOICE_DIR / "voice_live_brief_latest.json"
TARGETED_MOVE_PATH = VOICE_DIR / "yahoo_voice_targeted_move_latest.json"
DYNAMIC_CANDIDATE_PATH = VOICE_DIR / "yahoo_voice_dynamic_move_candidate_latest.json"
DYNAMIC_RESULT_PATH = VOICE_DIR / "yahoo_voice_dynamic_move_latest.json"
HANDOFFS_PATH = WORKING_DIR / "session_handoffs.md"
VOICE_CONFIG_PATH = INTEGRATIONS_DIR / "voice.toml"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return list(rows)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists() or tomllib is None:
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except Exception:
        return {}


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _relative_seconds(raw: str | None) -> int | None:
    dt = _parse_iso(raw)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((_utcnow() - dt.astimezone(timezone.utc)).total_seconds()))


def _tail_handoffs(limit: int = 4) -> list[dict[str, str]]:
    if not HANDOFFS_PATH.exists():
        return []
    try:
        text = HANDOFFS_PATH.read_text(encoding="utf-8")
    except Exception:
        return []
    chunks = re.split(r"^##\s+", text, flags=re.M)
    items: list[dict[str, str]] = []
    for chunk in chunks[1:]:
        lines = [line.rstrip() for line in chunk.strip().splitlines() if line.strip()]
        if not lines:
            continue
        heading = lines[0]
        bullets = [line for line in lines[1:] if line.startswith("- ")]
        items.append(
            {
                "heading": heading,
                "summary": " ".join(bullets[:3]).replace("- ", "").strip(),
            }
        )
    return items[-limit:]


def _connector_entry(name: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    services = payload.get("services", {})
    primary = next((str(v) for v in services.values() if v), payload.get("status", "unknown"))
    return {
        "name": name,
        "status": primary,
        "services": services,
        "updated_at": payload.get("updated_at", ""),
        "details": payload,
    }


def _state_summary(state: dict[str, Any] | None, voice_cfg: dict[str, Any]) -> dict[str, Any]:
    state = state or {}
    turns = state.get("turns", [])
    last_turn = turns[-1] if turns else {}
    updated_at = state.get("updated_at", "")
    age_seconds = _relative_seconds(updated_at)
    active_until = state.get("active_until", "")
    active_dt = _parse_iso(active_until)
    active_now = bool(active_dt and (active_dt > datetime.now(active_dt.tzinfo)))
    paused = bool(state.get("paused", False))
    live_status = "paused" if paused else "active_window" if active_now else "idle"
    if age_seconds is not None and age_seconds <= 90 and not paused:
        live_status = "recently_active"
    return {
        "status": voice_cfg.get("voice_v4", {}).get("status", ""),
        "live_status": live_status,
        "paused": paused,
        "active_until": active_until,
        "updated_at": updated_at,
        "age_seconds": age_seconds,
        "turn_count": len(turns),
        "last_transcription": last_turn.get("user", ""),
        "last_response": state.get("last_answer", "") or last_turn.get("assistant", ""),
        "pending_validation": state.get("pending_validation"),
        "last_validated_action": state.get("last_validated_action"),
    }


def _recent_alerts(
    state: dict[str, Any] | None,
    actions: list[dict[str, Any]],
    required_files: dict[str, Path],
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    state = state or {}
    pending = state.get("pending_validation")
    if pending:
        alerts.append(
            {
                "level": "warning",
                "title": "Validation en attente",
                "detail": pending.get("action", "Une action réelle attend une validation vocale."),
            }
        )
    for label, path in required_files.items():
        if not path.exists():
            alerts.append(
                {
                    "level": "error",
                    "title": f"Fichier manquant : {label}",
                    "detail": str(path),
                }
            )
    for action in reversed(actions[-8:]):
        kind = action.get("kind", "")
        if kind in {"cancelled_action", "cancelled_dynamic_batch"}:
            alerts.append(
                {
                    "level": "info",
                    "title": "Action annulée",
                    "detail": action.get("action", kind),
                }
            )
        if kind == "validated_action" and action.get("execution_status") == "validated_but_not_executed_in_generic_voice_layer":
            alerts.append(
                {
                    "level": "warning",
                    "title": "Validation sans exécution générique",
                    "detail": action.get("action", ""),
                }
            )
    return alerts[:8]


@router.get("")
async def personal_cockpit_snapshot():
    """Return a local cockpit snapshot sourced from jarvis-personal runtime."""
    voice_cfg = _load_toml(VOICE_CONFIG_PATH)
    state = _load_json(STATE_PATH)
    sessions = _load_jsonl_tail(SESSIONS_PATH, 12)
    actions = _load_jsonl_tail(ACTIONS_PATH, 12)
    live_brief = _load_json(LIVE_BRIEF_PATH)
    targeted_move = _load_json(TARGETED_MOVE_PATH)
    dynamic_candidate = _load_json(DYNAMIC_CANDIDATE_PATH)
    dynamic_result = _load_json(DYNAMIC_RESULT_PATH)
    handoffs = _tail_handoffs(limit=5)

    connectors = [
        _connector_entry("Yahoo", _load_json(INTEGRATIONS_DIR / "yahoo" / "status.json")),
        _connector_entry("Google", _load_json(INTEGRATIONS_DIR / "google" / "status.json")),
        _connector_entry("Graphify", _load_json(INTEGRATIONS_DIR / "graphify" / "status.json")),
    ]

    required_files = {
        "v4_state": STATE_PATH,
        "v4_sessions": SESSIONS_PATH,
        "v4_actions": ACTIONS_PATH,
    }

    history = [
        {
            "timestamp": item.get("timestamp", ""),
            "intent": item.get("intent", ""),
            "user": item.get("user", ""),
            "assistant": item.get("assistant", ""),
        }
        for item in sessions[-8:]
    ]

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "personal_root": str(PERSONAL_ROOT),
            "voice_runtime": str(VOICE_DIR),
        },
        "general_state": _state_summary(state, voice_cfg),
        "voice_live": {
            "config_status": voice_cfg.get("voice_v4", {}).get("status", ""),
            "wake_word": voice_cfg.get("voice_v4", {}).get("wake_word", ""),
            "vad": voice_cfg.get("voice_v4", {}).get("vad", ""),
            "stt": voice_cfg.get("voice_v4", {}).get("stt", ""),
            "tts": voice_cfg.get("voice_v4", {}).get("tts", ""),
            "commands": voice_cfg.get("voice_v4", {}).get("commands", []),
            "last_updated_at": (state or {}).get("updated_at", ""),
        },
        "latest_transcription": (state or {}).get("turns", [{}])[-1].get("user", "") if (state or {}).get("turns") else "",
        "latest_response": (state or {}).get("last_answer", ""),
        "pending_validation": (state or {}).get("pending_validation"),
        "last_live_brief": live_brief,
        "yahoo_targeted_move": targeted_move,
        "yahoo_dynamic_candidate": dynamic_candidate,
        "yahoo_dynamic_result": dynamic_result,
        "session_history": history,
        "recent_actions": actions[-8:],
        "connectors": connectors,
        "alerts": _recent_alerts(state, actions, required_files),
        "continuity": handoffs,
        "file_health": {
            label: {
                "exists": path.exists(),
                "path": str(path),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else "",
            }
            for label, path in {
                "v4_state": STATE_PATH,
                "v4_sessions": SESSIONS_PATH,
                "v4_action_queue": ACTIONS_PATH,
                "voice_live_brief": LIVE_BRIEF_PATH,
                "yahoo_targeted_move": TARGETED_MOVE_PATH,
                "yahoo_dynamic_candidate": DYNAMIC_CANDIDATE_PATH,
                "yahoo_dynamic_result": DYNAMIC_RESULT_PATH,
                "session_handoffs": HANDOFFS_PATH,
            }.items()
        },
    }
