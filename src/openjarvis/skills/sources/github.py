"""GitHubResolver — generic resolver for any GitHub repo containing skills.

Performs a recursive walk for SKILL.md (or skill.md) files anywhere
under the cache directory.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List

import yaml

from openjarvis.skills.sources.base import ResolvedSkill, SourceResolver

LOGGER = logging.getLogger(__name__)


class GitHubResolver(SourceResolver):
    """Generic resolver for any GitHub repo containing SKILL.md files."""

    name = "github"

    def __init__(self, cache_root: Path, repo_url: str) -> None:
        self._cache_root = Path(cache_root)
        self._repo_url = repo_url

    def cache_dir(self) -> Path:
        return self._cache_root

    def sync(self) -> None:
        if self._cache_root.exists() and (self._cache_root / ".git").exists():
            subprocess.run(
                ["git", "-C", str(self._cache_root), "pull", "--ff-only"],
                check=True,
            )
        else:
            self._cache_root.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", self._repo_url, str(self._cache_root)],
                check=True,
            )

    def list_skills(self) -> List[ResolvedSkill]:
        if not self._cache_root.exists():
            return []

        results: List[ResolvedSkill] = []
        commit = self._read_commit()
        seen_dirs: set[Path] = set()

        # Recursive walk for SKILL.md or skill.md
        for pattern in ("SKILL.md", "skill.md"):
            for skill_md in sorted(self._cache_root.rglob(pattern)):
                # Skip files inside .git
                if ".git" in skill_md.parts:
                    continue
                skill_dir = skill_md.parent
                if skill_dir in seen_dirs:
                    continue
                seen_dirs.add(skill_dir)

                name, description = self._read_preview(
                    skill_md, default_name=skill_dir.name
                )
                # Use the immediate parent directory of the skill dir as category
                try:
                    category = skill_dir.parent.relative_to(self._cache_root).as_posix()
                except ValueError:
                    category = ""

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
        return str(fm.get("name", default_name)), str(fm.get("description", ""))

    def _read_commit(self) -> str:
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


__all__ = ["GitHubResolver"]
