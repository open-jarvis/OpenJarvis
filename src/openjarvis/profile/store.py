"""ProfileStore — section-aware reader/writer for USER.md personal profile.

The profile is stored as a structured Markdown file at
``~/.openjarvis/USER.md`` (path is configurable).  The format is:

    # User Profile

    ## Identity
    - Name: Akhil Yadav
    - Timezone: Asia/Kolkata
    - Preferred address: sir
    - Role: Software Engineer

    ## Contacts
    - Alice (boss): Needs weekly status update. alice@corp.com
    - Dev team (colleagues): Daily standup 9 am IST

    ## Active Projects
    - OpenJarvis [active]: Building an open-source AI assistant
    - Client Dashboard [review]: Pending design sign-off by 2026-04-20

    ## Preferences
    - Always schedule meetings after 10 am
    - Never send emails without explicit confirmation
    - Prefer concise bullet-point responses

    ## Notes
    - Works from home on Mondays and Fridays

The file is:
  - **Injected** into every agent's system prompt via ``SystemPromptBuilder``
    (existing mechanism, unchanged).
  - **Writable** by agents via the enhanced ``user_profile_manage`` tool.
  - **Managed** directly by the user via ``jarvis profile`` CLI commands.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical section order written by ensure_template()
STANDARD_SECTIONS: List[str] = [
    "Identity",
    "Contacts",
    "Active Projects",
    "Preferences",
    "Notes",
]

_DEFAULT_TITLE = "User Profile"


class ProfileStore:
    """Section-aware reader/writer for a Markdown personal profile file.

    Parameters
    ----------
    path:
        Path to the profile file (``~`` expanded automatically).
    """

    def __init__(self, path: str | Path = "~/.openjarvis/USER.md") -> None:
        self._path = Path(path).expanduser()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists() and bool(self._path.read_text().strip())

    def load_text(self) -> str:
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8")

    def _parse(self, text: str) -> Tuple[str, Dict[str, List[str]]]:
        """Parse Markdown into (h1_title, {section: [lines]}).

        Lines within each section are stored exactly as they appear in the
        file (preserving ``-`` bullets).
        """
        title = _DEFAULT_TITLE
        sections: Dict[str, List[str]] = {}
        current: Optional[str] = None

        for line in text.split("\n"):
            if line.startswith("# ") and not line.startswith("## "):
                title = line[2:].strip()
                continue
            if line.startswith("## "):
                current = line[3:].strip()
                sections[current] = []
                continue
            if current is not None:
                sections[current].append(line)

        # Strip trailing blank lines from each section
        for key in sections:
            while sections[key] and not sections[key][-1].strip():
                sections[key].pop()

        return title, sections

    def load_sections(self) -> Dict[str, List[str]]:
        """Return ``{section_name: [lines]}`` for all sections in the file."""
        _, sections = self._parse(self.load_text())
        return sections

    def _render(
        self, title: str, sections: Dict[str, List[str]]
    ) -> str:
        """Render (title, sections) back to Markdown."""
        # Preserve canonical ordering for standard sections; extras at the end
        ordered_keys: List[str] = []
        for s in STANDARD_SECTIONS:
            if s in sections:
                ordered_keys.append(s)
        for s in sections:
            if s not in ordered_keys:
                ordered_keys.append(s)

        parts = [f"# {title}", ""]
        for key in ordered_keys:
            parts.append(f"## {key}")
            parts.extend(sections.get(key, []))
            parts.append("")

        return "\n".join(parts)

    def _write(self, title: str, sections: Dict[str, List[str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(self._render(title, sections), encoding="utf-8")

    # ------------------------------------------------------------------
    # High-level mutators
    # ------------------------------------------------------------------

    def ensure_template(self) -> None:
        """Write a blank structured template if the file is absent or empty."""
        if self._path.exists() and self._path.read_text().strip():
            return
        self._write(_DEFAULT_TITLE, {s: [] for s in STANDARD_SECTIONS})

    def set_field(self, section: str, field: str, value: str) -> None:
        """Set or update a ``- Field: Value`` entry inside *section*.

        If the field already exists it is overwritten in-place;
        otherwise a new entry is appended.
        """
        title, sections = self._parse(self.load_text())
        entries = sections.setdefault(section, [])
        prefix = f"- {field}:"
        new_line = f"- {field}: {value}"

        for i, line in enumerate(entries):
            if line.strip().startswith(prefix):
                entries[i] = new_line
                self._write(title, sections)
                return

        entries.append(new_line)
        self._write(title, sections)

    def get_field(self, section: str, field: str) -> Optional[str]:
        """Return the value of ``- Field: Value`` or ``None`` if not found."""
        _, sections = self._parse(self.load_text())
        prefix = f"- {field}:".lower()
        for line in sections.get(section, []):
            stripped = line.strip()
            if stripped.lower().startswith(prefix):
                return stripped[len(prefix):].strip()
        return None

    def add_item(self, section: str, text: str) -> None:
        """Append a bullet entry to *section*."""
        title, sections = self._parse(self.load_text())
        entries = sections.setdefault(section, [])
        entry = text if text.startswith("- ") else f"- {text}"
        entries.append(entry)
        self._write(title, sections)

    def remove_item(self, section: str, pattern: str) -> bool:
        """Remove the first entry in *section* whose text contains *pattern*.

        Returns ``True`` if an entry was removed.
        """
        title, sections = self._parse(self.load_text())
        entries = sections.get(section, [])
        lower_pat = pattern.lower()
        new_entries = [e for e in entries if lower_pat not in e.lower()]

        if len(new_entries) == len(entries):
            return False

        sections[section] = new_entries
        self._write(title, sections)
        return True

    def replace_section(self, section: str, lines: List[str]) -> None:
        """Replace all lines in *section* with *lines*."""
        title, sections = self._parse(self.load_text())
        sections[section] = list(lines)
        self._write(title, sections)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_section(self, section: str) -> List[str]:
        """Return all lines in *section* (empty list if absent)."""
        _, sections = self._parse(self.load_text())
        return sections.get(section, [])

    def get_identity(self) -> Dict[str, str]:
        """Parse the Identity section into ``{field: value}``."""
        entries = self.get_section("Identity")
        result: Dict[str, str] = {}
        for line in entries:
            stripped = line.strip().lstrip("- ")
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                result[k.strip()] = v.strip()
        return result

    # ------------------------------------------------------------------
    # Rendering for context injection
    # ------------------------------------------------------------------

    def render_full(self) -> str:
        """Return the complete profile text."""
        return self.load_text()

    def render_summary(self, max_chars: int = 1_200) -> str:
        """Return a compact profile summary for token-limited contexts.

        Priority order: Identity, Preferences, then as many Contacts /
        Active Projects / Notes as fit within *max_chars*.
        """
        text = self.load_text()
        if not text.strip():
            return ""
        if len(text) <= max_chars:
            return text

        _, sections = self._parse(text)
        parts: List[str] = []

        priority = ["Identity", "Preferences"]
        secondary = ["Contacts", "Active Projects", "Notes"]

        for s in priority:
            if entries := sections.get(s, []):
                parts += [f"## {s}"] + entries + [""]

        used = sum(len(p) + 1 for p in parts)
        for s in secondary:
            if entries := sections.get(s, []):
                block = [f"## {s}"] + entries + [""]
                block_len = sum(len(b) + 1 for b in block)
                if used + block_len <= max_chars:
                    parts += block
                    used += block_len

        return "\n".join(parts).strip()

    def __repr__(self) -> str:
        return f"ProfileStore(path={self._path!r}, exists={self.exists()})"
