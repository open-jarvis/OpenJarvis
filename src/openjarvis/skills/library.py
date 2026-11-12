"""On-demand skill library: search hundreds of SKILL.md skills, load one at a time.

Turning every installed skill into its own tool (``SkillManager``) works for a
handful of skills but swamps a small local model once there are hundreds. The
library instead keeps a lightweight keyword index of every skill's name and
description, so the agent can:

* get a short list of the skills relevant to the current request
  (``search`` - used for the per-request hint and the ``find_skills`` tool);
* load one skill's full instructions only when it decides to use it
  (``load`` - the ``use_skill`` tool).

Skills are read from ``[skills] skills_dir`` (default ``~/.openjarvis/skills``),
at any depth: ``<dir>/<name>/SKILL.md`` or ``<dir>/<source>/<name>/SKILL.md``.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_MAX_BODY_CHARS = 12_000
_MAX_DEPTH = 3
_TOKEN = re.compile(r"[a-z0-9]+")
# Words too common in skill descriptions to say anything about relevance.
_STOPWORDS = frozenset(
    "a an and are as at be by for from how i in into is it of on or that the this "
    "to use used uses using when with you your me my do does can should what which "
    "skill skills help helps make makes write create get need want new please give "
    "some any all about just like also more".split()
)


def _tokens(text: str) -> List[str]:
    return [
        t[:-1] if len(t) > 4 and t.endswith("s") else t
        for t in _TOKEN.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 1
    ]


@dataclass(frozen=True)
class SkillEntry:
    name: str
    description: str
    source: str
    path: Path  # the SKILL.md file


def _parse_skill(md: Path) -> Optional[Tuple[str, str, str]]:
    """Return (name, description, body) for a SKILL.md, or None if unreadable."""
    try:
        raw = md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    name, description, body = md.parent.name, "", raw
    if raw.startswith("---"):
        rest = raw[3:].lstrip("\r\n")
        end = rest.find("\n---")
        if end != -1:
            body = rest[end + 4 :].lstrip("\r\n-")
            try:
                meta = yaml.safe_load(rest[:end]) or {}
            except yaml.YAMLError:
                meta = {}
            if isinstance(meta, dict):
                name = str(meta.get("name") or name).strip() or name
                description = str(meta.get("description") or "").strip()
    return name, description, body


class SkillLibrary:
    """Keyword (BM25) index over installed skills."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser()
        self._lock = threading.Lock()
        self._entries: Dict[str, SkillEntry] = {}
        self._doc_tokens: Dict[str, Counter] = {}
        self._doc_len: Dict[str, int] = {}
        self._df: Counter = Counter()
        self._avg_len = 1.0
        self._loaded_mtime = -1.0

    # -- indexing ---------------------------------------------------------

    def _scan(self) -> List[Path]:
        if not self._root.is_dir():
            return []
        found: List[Path] = []
        for depth in range(1, _MAX_DEPTH + 1):
            pattern = "/".join(["*"] * depth) + "/SKILL.md"
            found.extend(self._root.glob(pattern))
        return found

    def refresh(self, *, force: bool = False) -> None:
        """(Re)build the index when the skills folder changed."""
        try:
            mtime = max(
                [self._root.stat().st_mtime]
                + [p.stat().st_mtime for p in self._root.iterdir() if p.is_dir()]
            )
        except OSError:
            mtime = 0.0
        if not force and mtime == self._loaded_mtime:
            return
        entries: Dict[str, SkillEntry] = {}
        for md in sorted(self._scan()):
            parsed = _parse_skill(md)
            if parsed is None:
                continue
            name, description, _ = parsed
            rel = md.parent.relative_to(self._root).parts
            source = rel[0] if len(rel) > 1 else "local"
            entries.setdefault(name.lower(), SkillEntry(name, description, source, md))
        doc_tokens: Dict[str, Counter] = {}
        df: Counter = Counter()
        for key, entry in entries.items():
            # Name words count double: they are the strongest signal.
            toks = _tokens(entry.name.replace("-", " ")) * 2 + _tokens(
                entry.description
            )
            counts = Counter(toks)
            doc_tokens[key] = counts
            df.update(counts.keys())
        with self._lock:
            self._entries = entries
            self._doc_tokens = doc_tokens
            self._doc_len = {k: sum(c.values()) for k, c in doc_tokens.items()}
            self._df = df
            self._avg_len = (
                sum(self._doc_len.values()) / len(self._doc_len)
                if self._doc_len
                else 1.0
            )
            self._loaded_mtime = mtime
        logger.info("Skill library indexed %d skills from %s", len(entries), self._root)

    # -- queries ----------------------------------------------------------

    def __len__(self) -> int:
        self.refresh()
        return len(self._entries)

    def search(self, query: str, k: int = 5) -> List[Tuple[SkillEntry, float]]:
        """Return up to *k* (skill, score) pairs, best first, BM25-ranked."""
        self.refresh()
        q = set(_tokens(query))
        if not q:
            return []
        with self._lock:
            n = len(self._entries) or 1
            k1, b = 1.2, 0.75
            scored: List[Tuple[SkillEntry, float]] = []
            for key, counts in self._doc_tokens.items():
                score = 0.0
                dl = self._doc_len.get(key, 1)
                for term in q:
                    tf = counts.get(term, 0)
                    if not tf:
                        continue
                    df = self._df.get(term, 0)
                    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                    score += (
                        idf
                        * tf
                        * (k1 + 1)
                        / (tf + k1 * (1 - b + b * dl / self._avg_len))
                    )
                if score > 0:
                    scored.append((self._entries[key], score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def get(self, name: str) -> Optional[SkillEntry]:
        self.refresh()
        key = name.strip().lower()
        with self._lock:
            if key in self._entries:
                return self._entries[key]
            # Tolerate "claude:foo" and spacing/underscore variants.
            key = key.split(":")[-1].replace("_", "-").replace(" ", "-")
            return self._entries.get(key)

    def load(self, name: str) -> Optional[str]:
        """Full instructions for *name* (markdown body), size-capped."""
        entry = self.get(name)
        if entry is None:
            return None
        parsed = _parse_skill(entry.path)
        if parsed is None:
            return None
        _, description, body = parsed
        extras = sorted(
            p.name
            for p in entry.path.parent.iterdir()
            if p.name not in ("SKILL.md", ".source")
        )
        text = f"# Skill: {entry.name}\n{description}\n\n{body.strip()}"
        if len(text) > _MAX_BODY_CHARS:
            text = text[:_MAX_BODY_CHARS] + "\n\n… (skill instructions truncated)"
        if extras:
            text += f"\n\n(Extra files in this skill folder: {', '.join(extras)})"
        return text


_LIBRARY: Optional[SkillLibrary] = None
_LIBRARY_LOCK = threading.Lock()


def get_skill_library() -> SkillLibrary:
    """Process-wide library for the configured skills folder."""
    global _LIBRARY
    with _LIBRARY_LOCK:
        if _LIBRARY is None:
            try:
                from openjarvis.core.config import load_config

                root = Path(load_config().skills.skills_dir)
            except Exception:
                from openjarvis.core.paths import get_config_dir

                root = get_config_dir() / "skills"
            _LIBRARY = SkillLibrary(root)
        return _LIBRARY


def skill_hint(query: str, *, k: int = 3, min_score: float = 6.0) -> str:
    """A short note naming the skills most relevant to *query*, or ''.

    Only skills that clear *min_score* are mentioned, so everyday chit-chat
    gets no hint at all.
    """
    try:
        hits = [
            (e, s) for e, s in get_skill_library().search(query, k=k) if s >= min_score
        ]
    except Exception:
        logger.debug("Skill hint failed", exc_info=True)
        return ""
    if not hits:
        return ""
    lines = [
        "Skills in your library that may help with this request "
        "(call use_skill with the name to load its full instructions, "
        "only if it is actually useful):"
    ]
    for entry, _ in hits:
        lines.append(
            f"- {entry.name}: "
            + (entry.description.splitlines()[0][:160] if entry.description else "")
        )
    return "\n".join(lines)


__all__ = ["SkillEntry", "SkillLibrary", "get_skill_library", "skill_hint"]
