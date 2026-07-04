from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional

LOGGER = logging.getLogger(__name__)

_DEFAULT_PATH = Path(os.environ.get("OPENJARVIS_OLLAMA_USAGES", "")) or (
    Path.home() / ".openjarvis" / "ollama-model-usages.json"
)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    model: str
    success: bool = True
    latency_ms: float = 0.0
    tokens_used: int = 0
    timestamp: float = field(default_factory=time.time)


class OllamaModelUsageStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state: Dict[str, Dict[str, object]] = {}
        self._load()

    def record(self, usage: ModelUsage) -> None:
        current = self._state.setdefault(
            usage.model,
            {
                "model": usage.model,
                "success_count": 0,
                "failure_count": 0,
                "tokens_used": 0,
                "avg_latency_ms": 0.0,
                "last_latency_ms": 0.0,
                "samples": 0,
                "last_seen": 0.0,
            },
        )
        if usage.success:
            current["success_count"] = int(current.get("success_count", 0)) + 1
        else:
            current["failure_count"] = int(current.get("failure_count", 0)) + 1
        current["tokens_used"] = int(current.get("tokens_used", 0)) + usage.tokens_used
        samples = int(current.get("samples", 0)) + 1
        latency = usage.latency_ms
        current["avg_latency_ms"] = (
            float(current.get("avg_latency_ms", 0.0)) * (samples - 1) + latency
        ) / samples
        current["last_latency_ms"] = latency
        current["samples"] = samples
        current["last_seen"] = usage.timestamp
        self._persist()

    def sorted_by_latency(self, models):
        by_key = {
            m: self._state.get(m, {}).get("avg_latency_ms", float("inf"))
            for m in models
        }
        return sorted(models, key=lambda m: by_key.get(m, float("inf")))

    def usage_for(self, model: str) -> Dict[str, object]:
        return self._state.get(model, {})

    def _load(self) -> None:
        path = self._path
        if not path.exists():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            self._state = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.debug("Ollama usage store load failed: %s", exc)
            self._state = {}

    def _persist(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._state, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            LOGGER.debug("Ollama usage store write failed: %s", exc)
