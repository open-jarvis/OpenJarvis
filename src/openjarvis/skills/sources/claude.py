"""ClaudeResolver — import the user's own Claude Code skills.

Claude Code keeps personal skills in ``~/.claude/skills/<name>/SKILL.md``
(the same Agent Skills format OpenJarvis uses), so no download is needed:
the "cache" is that local folder. Override with ``OPENJARVIS_CLAUDE_SKILLS_DIR``.

Layout:
    ~/.claude/skills/<skill-name>/SKILL.md
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

import yaml

from openjarvis.skills.sources.base import ResolvedSkill, SourceResolver

LOGGER = logging.getLogger(__name__)


def default_claude_skills_dir() -> Path:
    override = os.environ.get("OPENJARVIS_CLAUDE_SKILLS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "skills"


class ClaudeResolver(SourceResolver):
    """Resolves skills from the local Claude Code skills folder."""

    name = "claude"

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._root = Path(skills_dir) if skills_dir else default_claude_skills_dir()

    def cache_dir(self) -> Path:
        return self._root

    def sync(self) -> None:
        """Nothing to fetch: the skills already live on this computer."""
        self.refresh_warning = ""
        if not self._root.is_dir():
            self.refresh_warning = f"No Claude skills folder at {self._root}"

    def list_skills(self) -> List[ResolvedSkill]:
        if not self._root.is_dir():
            return []
        results: List[ResolvedSkill] = []
        for skill_dir in sorted(self._root.iterdir()):
            # Skip symlinked skill folders: the importer refuses to copy links.
            if not skill_dir.is_dir() or skill_dir.is_symlink():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            name, description = _read_preview(skill_md, skill_dir.name)
            results.append(
                ResolvedSkill(
                    name=name,
                    source=self.name,
                    path=skill_dir,
                    category="claude",
                    description=description,
                    commit="local",
                )
            )
        return results


def _read_preview(skill_md: Path, default_name: str) -> tuple[str, str]:
    """Return (name, description) from the SKILL.md frontmatter."""
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except Exception:
        return default_name, ""
    if not raw.startswith("---"):
        return default_name, ""
    rest = raw[3:].lstrip("\r\n")
    end = rest.find("\n---")
    if end == -1:
        return default_name, ""
    try:
        meta = yaml.safe_load(rest[:end]) or {}
    except yaml.YAMLError:
        LOGGER.debug("Bad frontmatter in %s", skill_md)
        return default_name, ""
    if not isinstance(meta, dict):
        return default_name, ""
    name = str(meta.get("name") or default_name).strip() or default_name
    description = str(meta.get("description") or "").strip()
    return name, description


__all__ = ["ClaudeResolver", "default_claude_skills_dir"]
