"""HermesResolver — resolves skills from NousResearch/hermes-agent.

Layout:
    skills/<category>/<skill-name>/SKILL.md
    skills/<category>/DESCRIPTION.md  (skipped)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List

import yaml

from openjarvis.skills.sources.base import ResolvedSkill, SourceResolver

LOGGER = logging.getLogger(__name__)

HERMES_REPO_URL = "https://github.com/NousResearch/hermes-agent.git"


class HermesResolver(SourceResolver):
    """Resolves skills from the Hermes Agent repository."""

    name = "hermes"

    def __init__(self, cache_root: Path | None = None) -> None:
        if cache_root is None:
            cache_root = Path("~/.openjarvis/skill-cache/hermes/").expanduser()
        self._cache_root = Path(cache_root)

    def cache_dir(self) -> Path:
        return self._cache_root

    def sync(self) -> None:
        """Clone or pull the Hermes repo into the cache directory."""
        if self._cache_root.exists() and (self._cache_root / ".git").exists():
            subprocess.run(
                ["git", "-C", str(self._cache_root), "pull", "--ff-only"],
                check=True,
            )
        else:
            self._cache_root.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", HERMES_REPO_URL, str(self._cache_root)],
                check=True,
            )

    def list_skills(self) -> List[ResolvedSkill]:
        """Walk skills/<category>/<skill>/SKILL.md."""
        skills_root = self._cache_root / "skills"
        if not skills_root.exists():
            return []

        results: List[ResolvedSkill] = []
        commit = self._read_commit()

        for category_dir in sorted(skills_root.iterdir()):
            if not category_dir.is_dir():
                continue
            category = category_dir.name
            for skill_dir in sorted(category_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue  # skip DESCRIPTION.md and other files
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                # Read minimal frontmatter for the preview
                name, description = self._read_preview(
                    skill_md, default_name=skill_dir.name
                )
                results.append(
                    ResolvedSkill(
                        name=name,
                        source=self.name,
                        path=skill_dir,
                        category=category,
                        description=description,
                        commit=commit,
                    )
                )

        return results

    def _read_preview(self, skill_md: Path, default_name: str) -> tuple[str, str]:
        """Read just enough frontmatter to populate ResolvedSkill preview fields."""
        try:
            raw = skill_md.read_text(encoding="utf-8")
        except Exception:
            return default_name, ""

        if not raw.startswith("---"):
            return default_name, ""

        rest = raw[3:].lstrip("\n")
        end = rest.find("\n---")
        if end == -1:
            return default_name, ""
        try:
            fm = yaml.safe_load(rest[:end])
        except yaml.YAMLError:
            return default_name, ""
        if not isinstance(fm, dict):
            return default_name, ""

        return (
            str(fm.get("name", default_name)),
            str(fm.get("description", "")),
        )

    def _read_commit(self) -> str:
        """Return the current HEAD SHA of the cached repo, or empty string."""
        if not (self._cache_root / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(self._cache_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""


__all__ = ["HermesResolver", "HERMES_REPO_URL"]
