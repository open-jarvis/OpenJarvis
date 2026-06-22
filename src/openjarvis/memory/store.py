"""Persistent stores for automatically extracted long-term memory facts.

A *fact* is a short, durable statement worth remembering about the user
(e.g. ``"Prefers concise answers"``).  Facts are produced by the memory
service's background extractor and persisted here so they survive across
sessions.  The store is intentionally small and self-contained: it dedupes,
caps the total number of facts, and is safe to call from multiple threads.
"""

from __future__ import annotations

import json
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(slots=True)
class Fact:
    """A single durable memory entry."""

    text: str
    source: str = ""
    created_at: float = 0.0


class FactStore(ABC):
    """Abstract persistent store for extracted memory facts."""

    @abstractmethod
    def add(self, text: str, source: str = "") -> bool:
        """Store *text* as a fact. Returns True if a new fact was stored."""

    def add_many(self, texts: Iterable[str], source: str = "") -> int:
        """Store several facts, returning the count of newly stored ones."""
        added = 0
        for text in texts:
            if self.add(text, source=source):
                added += 1
        return added

    @abstractmethod
    def list(self) -> List[Fact]:
        """Return all stored facts, oldest first."""

    @abstractmethod
    def clear(self) -> int:
        """Remove all stored facts, returning the number removed."""

    @abstractmethod
    def count(self) -> int:
        """Return the number of stored facts."""


class LocalFactStore(FactStore):
    """Append-only JSONL fact store on the local filesystem.

    Facts are kept human-readable (one JSON object per line) so they can be
    inspected or edited by hand.  Writes are atomic (temp file + rename) and
    guarded by a lock, so concurrent ``add`` calls from the extraction worker
    and ``list``/``clear`` from the CLI never corrupt the file.
    """

    def __init__(
        self,
        path: str | Path = "~/.openjarvis/memory_facts.jsonl",
        *,
        max_facts: int = 1000,
    ) -> None:
        self._path = Path(path).expanduser()
        self._max_facts = max(0, int(max_facts))
        self._lock = threading.Lock()
        self._facts: List[Fact] = self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> List[Fact]:
        if not self._path.exists():
            return []
        facts: List[Fact] = []
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue  # skip malformed lines rather than crashing
            fact_text = str(obj.get("text", "")).strip()
            if not fact_text:
                continue
            facts.append(
                Fact(
                    text=fact_text,
                    source=str(obj.get("source", "")),
                    created_at=float(obj.get("created_at", 0.0) or 0.0),
                )
            )
        return facts

    def _flush(self) -> None:
        """Atomically rewrite the JSONL file from the in-memory list."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = "".join(
            json.dumps(asdict(f), ensure_ascii=False) + "\n" for f in self._facts
        )
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    # -- FactStore API ------------------------------------------------------

    def add(self, text: str, source: str = "") -> bool:
        text = (text or "").strip()
        if not text:
            return False
        with self._lock:
            lowered = text.lower()
            if any(f.text.lower() == lowered for f in self._facts):
                return False  # dedupe
            self._facts.append(Fact(text=text, source=source, created_at=time.time()))
            # Enforce the cap by evicting the oldest entries.
            if self._max_facts and len(self._facts) > self._max_facts:
                self._facts = self._facts[-self._max_facts :]
            self._flush()
        return True

    def list(self) -> List[Fact]:
        with self._lock:
            return list(self._facts)

    def clear(self) -> int:
        with self._lock:
            removed = len(self._facts)
            self._facts = []
            if self._path.exists():
                try:
                    self._path.unlink()
                except OSError:
                    self._flush()
        return removed

    def count(self) -> int:
        with self._lock:
            return len(self._facts)

    @property
    def path(self) -> Path:
        """Filesystem location of the JSONL store."""
        return self._path


def create_fact_store(
    backend: str = "local",
    *,
    path: str | Path = "~/.openjarvis/memory_facts.jsonl",
    max_facts: int = 1000,
) -> FactStore:
    """Construct a fact store for the configured *backend*.

    Only the ``"local"`` (on-disk JSONL) backend is supported today; the
    factory exists so additional backends can be added without changing the
    service or CLI wiring.
    """
    key = (backend or "local").strip().lower()
    if key == "local":
        return LocalFactStore(path, max_facts=max_facts)
    raise ValueError(f"Unknown memory backend '{backend}'. Supported backends: local")


__all__ = ["Fact", "FactStore", "LocalFactStore", "create_fact_store"]
