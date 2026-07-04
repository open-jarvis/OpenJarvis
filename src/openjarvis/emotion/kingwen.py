"""King Wen emotion provider for OpenJarvis.

Loads the generated King Wen immutable tables and exposes:
- consultation entrypoint for prompt injection
- voice-preset resolution keyed by voiceWeight
- Oracle Console formatter for live response annotation

Data contract:
- data/hexagram-registry.json
- data/emotional-weights.json
- data/temporal-reflections.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class KingWenEmotionProvider:
    """Deterministic 64-hex emotional state and voice-selection provider."""

    def __init__(
        self,
        registry_path: str | Path,
        weights_path: str | Path,
        reflections_path: str | Path,
    ) -> None:
        self._registry: Dict[str, Any] = {}
        self._weights: Dict[str, Any] = {}
        self._reflections: Dict[str, Any] = {}
        self._load(registry_path, weights_path, reflections_path)

    def _load(
        self,
        registry_path: str | Path,
        weights_path: str | Path,
        reflections_path: str | Path,
    ) -> None:
        self._registry = self._read_json(registry_path)
        self._weights = self._read_json(weights_path)
        self._reflections = self._read_json(reflections_path)

    @staticmethod
    def _read_json(path: str | Path) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"King Wen data missing: {p}")
        return json.loads(p.read_text(encoding="utf-8"))

    def consult(
        self,
        text: str = "",
        session_id: str = "openjarvis",
        emotional_input: int = 50,
    ) -> Dict[str, Any]:
        """Return a deterministic emotional-state response for prompt injection."""
        if not text:
            text = "OpenJarvas session context"
        hexagram_id = self._select(text, session_id)
        record = self._registry[str(hexagram_id)]
        weights = self._weights.get(str(hexagram_id), {})
        reflections = self._reflections.get(str(hexagram_id), {})
        return {
            "hexagram_id": hexagram_id,
            "hexagram_name": record.get("name", ""),
            "hexagram_unicode": record.get("unicode", ""),
            "binary": record.get("binary", ""),
            "upper_trigram": record.get("upper_trigram", ""),
            "lower_trigram": record.get("lower_trigram", ""),
            "category": record.get("category", ""),
            "action": record.get("action", ""),
            "emotional_deltas": {
                "chaos": float(weights.get("chaos", 0.0)),
                "whimsy": float(weights.get("whimsy", 0.0)),
                "darkTone": float(weights.get("darkTone", 0.0)),
                "coherence": float(weights.get("coherence", 0.0)),
                "voiceWeight": float(weights.get("voiceWeight", 0.0)),
            },
            "reflections": {
                "past": reflections.get("past", ""),
                "present": reflections.get("present", ""),
                "future": reflections.get("future", ""),
            },
            "trainingNotes": weights.get("trainingNotes", ""),
        }

    # ------------------------------------------------------------------
    # Voice wiring
    # ------------------------------------------------------------------

    VOICE_PRESETS = {
        "openai_tts": [
            {"min_weight": 0.00, "max_weight": 0.50, "voice_id": "nova", "speed": 1.0},
            {"min_weight": 0.50, "max_weight": 0.75, "voice_id": "fable", "speed": 1.05},
            {"min_weight": 0.75, "max_weight": 1.01, "voice_id": "onyx", "speed": 1.1},
        ],
        "cartesia": [
            {"min_weight": 0.00, "max_weight": 0.50, "voice_id": "a0e99841-438c-4a64-b679-ae501e7d6091", "speed": 1.0},
            {"min_weight": 0.50, "max_weight": 0.75, "voice_id": "c8f7835e-28a3-4f0c-80d7-c1302ac62aae", "speed": 1.05},
            {"min_weight": 0.75, "max_weight": 1.01, "voice_id": "c8f7835e-28a3-4f0c-80d7-c1302ac62aae", "speed": 1.12},
        ],
        "kokoro": [
            {"min_weight": 0.00, "max_weight": 0.50, "voice_id": "af_heart", "speed": 1.0},
            {"min_weight": 0.50, "max_weight": 0.75, "voice_id": "am_adam", "speed": 1.05},
            {"min_weight": 0.75, "max_weight": 1.01, "voice_id": "bf_emma", "speed": 1.1},
        ],
    }

    def voice_preset(self, tts_backend: str, voice_weight: float) -> Dict[str, float | str]:
        backend_key = (tts_backend or "cartesia").lower()
        if backend_key == "openai":
            backend_key = "openai_tts"
        presets = self.VOICE_PRESETS.get(backend_key, self.VOICE_PRESETS["cartesia"])
        weight = max(0.0, min(1.0, float(voice_weight or 0.0)))
        for preset in presets:
            if preset["min_weight"] <= weight < preset["max_weight"]:
                return {
                    "voice_id": preset["voice_id"],
                    "speed": float(preset["speed"]),
                    "backend": backend_key,
                }
        fallback = presets[-1]
        return {
            "voice_id": fallback["voice_id"],
            "speed": float(fallback["speed"]),
            "backend": backend_key,
        }

    # ------------------------------------------------------------------
    # Prompt / response formatting
    # ------------------------------------------------------------------

    def format_prompt_section(self, payload: Dict[str, Any]) -> str:
        lines = [
            "## Emotional State",
            "",
            f"- Hexagram: {payload.get('hexagram_id', '')} {payload.get('hexagram_name', '')} {payload.get('hexagram_unicode', '')}",
            f"- Structure: {payload.get('upper_trigram', '')} over {payload.get('lower_trigram', '')}",
            f"- Binary: {payload.get('binary', '')}",
            f"- Category: {payload.get('category', '')} | Action: {payload.get('action', '')}",
            f"- Training notes: {payload.get('trainingNotes', '')}",
            "### Emotional weight",
        ]
        deltas = payload.get("emotional_deltas", {})
        for k in ["chaos", "whimsy", "darkTone", "coherence", "voiceWeight"]:
            lines.append(f"- {k}: {deltas.get(k, 0.0)}")
        lines.extend(
            [
                "",
                "### Reflections",
                f"- Past: {payload.get('reflections', {}).get('past', '')}",
                f"- Present: {payload.get('reflections', {}).get('present', '')}",
                f"- Future: {payload.get('reflections', {}).get('future', '')}",
            ]
        )
        return "\n".join(lines)

    def format_voice_section(self, preset: Dict[str, float | str]) -> str:
        return (
            "## Voice Preset\n"
            "\n"
            f"- backend: {preset.get('backend')}\n"
            f"- voice_id: {preset.get('voice_id')}\n"
            f"- speed: {preset.get('speed')}\n"
        )

    def format_oracle_console(
        self,
        payload: Dict[str, Any],
        response_text: str = "",
        *,
        oracle_label: str = "Oracle Console",
        canonical_tick_ms: float = 640.0,
    ) -> str:
        """Translate live King Wen consultation into the user-facing Oracle Console block."""
        reflections = payload.get("reflections", {}) if isinstance(payload, dict) else {}
        deltas = payload.get("emotional_deltas", {}) if isinstance(payload, dict) else {}
        resolved_emotion = float(deltas.get("coherence", 0.0))
        lines = [
            oracle_label,
            response_text,
            "Past",
            "Present",
            "Future",
            "Resolved Emotion",
            "",
            f"{resolved_emotion:.2f}",
            "CONSULT",
            "Response",
            f"{canonical_tick_ms:.0f}ms",
            "Past Reflection",
            reflections.get("past", ""),
            "Present Reflection",
            reflections.get("present", ""),
            "Future Reflection",
            reflections.get("future", ""),
            "Unified Oracle Weave",
            reflections.get("present", ""),
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Deterministic selector
    # ------------------------------------------------------------------

    def _select(self, text: str, session_id: str) -> int:
        """Deterministic hexagram selection."""
        seed = f"{session_id}:{text}".encode("utf-8")
        total = 0
        for byte in seed[:64]:
            total = (total * 31 + byte) % 2**31
        return (total % 64) + 1
