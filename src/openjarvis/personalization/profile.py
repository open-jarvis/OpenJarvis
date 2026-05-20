"""UserProfile — structured view of ~/.openjarvis/USER.md.

The profile is the source of truth that Jarvis injects into every system
prompt so the model "remembers" the user. Format:

    # USER PROFILE

    Last updated: 2026-05-20T15:34:00+08:00

    ## Identity
    - user.name: Mac
    - user.locale: zh-TW

    ## Preferences
    - pref.language: 台灣繁體中文，台灣慣用詞
    - pref.coffee: 黑咖啡，不加糖

    ## Facts
    - fact.work: 賈維斯主程式維護者

    ## Relations
    - relation.wife_birthday: 1990-08-12

    ## Notes
    - 喜歡口語、語音化回應

Each section is a flat key/value list (one bullet per ``key: value``). The
parser preserves unrecognised sections so the user can hand-edit freely
without losing notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_PROFILE_PATH = Path("~/.openjarvis/USER.md").expanduser()

# Canonical section ordering — anything else is preserved at the end.
CANONICAL_SECTIONS: Tuple[str, ...] = (
    "Identity",
    "Preferences",
    "Facts",
    "Relations",
    "Notes",
)

# memory_learn-style key prefix -> section name
KEY_PREFIX_TO_SECTION: Dict[str, str] = {
    "user": "Identity",
    "pref": "Preferences",
    "fact": "Facts",
    "relation": "Relations",
    "note": "Notes",
}


@dataclass(slots=True)
class ProfileEntry:
    """A single key/value bullet within a profile section."""

    key: str
    value: str

    def render(self) -> str:
        return f"- {self.key}: {self.value}" if self.key else f"- {self.value}"


@dataclass(slots=True)
class ProfileSection:
    """A markdown ``## Name`` section of the profile."""

    name: str
    entries: List[ProfileEntry] = field(default_factory=list)

    def add(self, key: str, value: str) -> None:
        self.entries.append(ProfileEntry(key=key, value=value))

    def is_empty(self) -> bool:
        return not self.entries


@dataclass(slots=True)
class UserProfile:
    """Structured view of USER.md plus convenience I/O.

    ``sections`` preserves insertion order. ``updated_at`` is updated on
    every ``save()``; callers can read it to detect staleness.
    """

    sections: Dict[str, ProfileSection] = field(default_factory=dict)
    updated_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def section(self, name: str) -> ProfileSection:
        """Return (creating if needed) the section with *name*."""
        if name not in self.sections:
            self.sections[name] = ProfileSection(name=name)
        return self.sections[name]

    def add(self, key: str, value: str) -> None:
        """Place ``key: value`` into the section implied by the key prefix."""
        prefix = key.split(".", 1)[0]
        section_name = KEY_PREFIX_TO_SECTION.get(prefix, "Notes")
        self.section(section_name).add(key, value)

    def bulk_add(self, items: Iterable[Tuple[str, str]]) -> None:
        for key, value in items:
            self.add(key, value)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_entries(self) -> List[ProfileEntry]:
        out: List[ProfileEntry] = []
        for section in self.sections.values():
            out.extend(section.entries)
        return out

    def get(self, key: str) -> Optional[str]:
        for entry in self.all_entries():
            if entry.key == key:
                return entry.value
        return None

    def is_empty(self) -> bool:
        return all(s.is_empty() for s in self.sections.values())

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render the profile back to markdown."""
        lines: List[str] = ["# USER PROFILE", ""]
        if self.updated_at is not None:
            lines.append(f"Last updated: {self.updated_at.isoformat()}")
            lines.append("")

        ordered: List[str] = []
        for name in CANONICAL_SECTIONS:
            if name in self.sections and not self.sections[name].is_empty():
                ordered.append(name)
        for name in self.sections:
            if name in ordered:
                continue
            if not self.sections[name].is_empty():
                ordered.append(name)

        for name in ordered:
            section = self.sections[name]
            lines.append(f"## {name}")
            for entry in section.entries:
                lines.append(entry.render())
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def save(self, path: Path | str = DEFAULT_PROFILE_PATH) -> Path:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().astimezone()
        path.write_text(self.render(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PROFILE_PATH) -> "UserProfile":
        path = Path(path).expanduser()
        if not path.exists():
            return cls()
        return cls.parse(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    _SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
    _BULLET_RE = re.compile(r"^[-*]\s+(.+?)\s*$")
    _UPDATED_RE = re.compile(r"^Last updated:\s+(.+?)\s*$")

    @classmethod
    def parse(cls, raw: str) -> "UserProfile":
        profile = cls()
        current_section: Optional[ProfileSection] = None
        for line in raw.splitlines():
            m_updated = cls._UPDATED_RE.match(line)
            if m_updated and profile.updated_at is None:
                try:
                    profile.updated_at = datetime.fromisoformat(m_updated.group(1))
                except ValueError:
                    pass
                continue

            m_section = cls._SECTION_RE.match(line)
            if m_section:
                current_section = profile.section(m_section.group(1))
                continue

            m_bullet = cls._BULLET_RE.match(line)
            if m_bullet and current_section is not None:
                body = m_bullet.group(1)
                if ": " in body:
                    key, _, value = body.partition(": ")
                    current_section.add(key.strip(), value.strip())
                else:
                    current_section.add("", body.strip())
        return profile


__all__ = [
    "CANONICAL_SECTIONS",
    "DEFAULT_PROFILE_PATH",
    "KEY_PREFIX_TO_SECTION",
    "ProfileEntry",
    "ProfileSection",
    "UserProfile",
]
