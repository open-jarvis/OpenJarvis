"""Source resolver ABC + ResolvedSkill dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(slots=True)
class ResolvedSkill:
    """A skill found in an upstream source, ready to import.

    Lightweight — does not include the full SKILL.md body.  The importer
    reads the file from *path* when actually installing.
    """

    name: str
    source: str
    path: Path
    category: str
    description: str
    commit: str
    sidecar_data: Dict[str, Any] = field(default_factory=dict)


class SourceResolver(ABC):
    """Abstract base for a skill source resolver.

    Implementations clone or pull an upstream repo into a cache directory,
    walk the cache to find SKILL.md files, and return ResolvedSkill objects
    that the importer can install.
    """

    name: str = ""

    @abstractmethod
    def cache_dir(self) -> Path:
        """Where this source clones its repo."""

    @abstractmethod
    def sync(self) -> None:
        """Clone or pull the upstream repo into the cache."""

    @abstractmethod
    def list_skills(self) -> List[ResolvedSkill]:
        """Walk the cache directory and return all discoverable skills."""

    def resolve(self, query: str) -> List[ResolvedSkill]:
        """Filter list_skills() by name (substring match).

        Empty *query* returns all skills.
        """
        all_skills = self.list_skills()
        if not query:
            return all_skills
        q = query.lower()
        return [s for s in all_skills if q in s.name.lower()]

    def filter_by_category(self, category: str) -> List[ResolvedSkill]:
        """Return skills whose category exactly matches *category*."""
        return [s for s in self.list_skills() if s.category == category]


__all__ = ["ResolvedSkill", "SourceResolver"]
