"""Skill index — load and search a remote/local skill catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(slots=True)
class SkillIndexEntry:
    """A single entry in the skill index catalog."""

    name: str
    version: str
    description: str
    author: str
    source: str
    sha256: str
    tags: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)


class SkillIndex:
    """Catalog of available skills loaded from an ``index.toml`` file.

    ``index.toml`` format::

        [[skills]]
        name = "research"
        version = "0.1.0"
        description = "Research a topic"
        author = "openjarvis"
        source = "github.com/openjarvis/skills/research"
        sha256 = "abc123"
        tags = ["research"]
        required_capabilities = ["network:fetch"]
    """

    def __init__(self, index_dir: str | Path) -> None:
        self._index_dir = Path(index_dir)
        self._entries: dict[str, SkillIndexEntry] = {}
        self._load()

    def _load(self) -> None:
        """Parse ``index.toml`` from the index directory if it exists."""
        index_file = self._index_dir / "index.toml"
        if not index_file.exists():
            return

        with open(index_file, "rb") as fh:
            data = tomllib.load(fh)

        for skill_data in data.get("skills", []):
            entry = SkillIndexEntry(
                name=skill_data.get("name", ""),
                version=skill_data.get("version", "0.1.0"),
                description=skill_data.get("description", ""),
                author=skill_data.get("author", ""),
                source=skill_data.get("source", ""),
                sha256=skill_data.get("sha256", ""),
                tags=skill_data.get("tags", []),
                required_capabilities=skill_data.get("required_capabilities", []),
            )
            self._entries[entry.name] = entry

    @property
    def entries(self) -> dict[str, SkillIndexEntry]:
        """Return all entries keyed by skill name."""
        return self._entries

    def search(self, query: str) -> list[SkillIndexEntry]:
        """Return entries whose name, description, or tags match *query*.

        Matching is case-insensitive substring search across name, description,
        and each tag value.
        """
        q = query.lower()
        results: list[SkillIndexEntry] = []
        for entry in self._entries.values():
            if (
                q in entry.name.lower()
                or q in entry.description.lower()
                or any(q in tag.lower() for tag in entry.tags)
            ):
                results.append(entry)
        return results

    def get(self, name: str) -> Optional[SkillIndexEntry]:
        """Look up a skill by exact name, returning ``None`` if not found."""
        return self._entries.get(name)


__all__ = ["SkillIndexEntry", "SkillIndex"]
