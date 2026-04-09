"""SkillImporter — install ResolvedSkill instances into ~/.openjarvis/skills/.

Steps performed by ``import_skill``:

1. Parse the source SKILL.md through SkillParser (strict + tolerant).
2. Translate tool references in the markdown body via ToolTranslator.
3. Decide on scripts (default-skip; opt-in via with_scripts=True).
4. Write to disk at <target_root>/<source>/<name>/:
   - translated SKILL.md
   - references/, assets/, templates/ (always copied)
   - scripts/ (only if approved)
   - .source metadata file
5. Return ImportResult with status, warnings, translated/missing tools.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import yaml

from openjarvis.skills.parser import SkillParser
from openjarvis.skills.sources.base import ResolvedSkill
from openjarvis.skills.tool_translator import ToolTranslator

# Subdirectories of a skill that are always copied (never gated by --with-scripts)
COPIED_SUBDIRS = ("references", "assets", "templates")


@dataclass(slots=True)
class ImportResult:
    """Result of importing a single skill."""

    success: bool = True
    skipped: bool = False
    target_path: Path | None = None
    translated_tools: List[str] = field(default_factory=list)
    untranslated_tools: List[str] = field(default_factory=list)
    scripts_imported: bool = False
    warnings: List[str] = field(default_factory=list)


class SkillImporter:
    """Install resolved skills into the user skills directory."""

    def __init__(
        self,
        parser: SkillParser,
        tool_translator: ToolTranslator,
        target_root: Path | None = None,
    ) -> None:
        self._parser = parser
        self._translator = tool_translator
        if target_root is None:
            target_root = Path("~/.openjarvis/skills/").expanduser()
        self._target_root = Path(target_root)

    def import_skill(
        self,
        resolved: ResolvedSkill,
        *,
        with_scripts: bool = False,
        force: bool = False,
    ) -> ImportResult:
        """Install *resolved* into ``<target_root>/<source>/<name>/``.

        Returns an :class:`ImportResult` with status, paths, translated
        tools, untranslated tools, and warnings.
        """
        result = ImportResult()
        target_dir = self._target_root / resolved.source / resolved.name
        result.target_path = target_dir

        # Skip if already installed and force is False
        if target_dir.exists() and not force:
            result.skipped = True
            result.warnings.append(
                f"Skill already installed at {target_dir} (use force=True to overwrite)"
            )
            return result

        # 1. Parse source SKILL.md
        source_md = resolved.path / "SKILL.md"
        if not source_md.exists():
            source_md = resolved.path / "skill.md"
            if not source_md.exists():
                result.success = False
                result.warnings.append(f"No SKILL.md found in {resolved.path}")
                return result

        try:
            frontmatter, body = self._read_skill_md(source_md)
            self._parser.parse_frontmatter(frontmatter, markdown_content=body)
        except Exception as exc:
            result.success = False
            result.warnings.append(f"Parse error: {exc}")
            return result

        # 2. Translate tool references
        translated_body, untranslated = self._translator.translate_markdown(body)
        result.untranslated_tools = untranslated
        # Compute the list of translations actually applied
        applied: List[str] = []
        for ext, internal in self._translator._table.items():
            if ext in body and ext not in translated_body:
                applied.append(f"{ext}->{internal}")
        result.translated_tools = applied

        # 3. Write the target directory
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True)

        # 3a. Translated SKILL.md
        new_md = self._render_skill_md(frontmatter, translated_body)
        (target_dir / "SKILL.md").write_text(new_md, encoding="utf-8")

        # 3b. Always-copied subdirs
        for subdir in COPIED_SUBDIRS:
            src_sub = resolved.path / subdir
            if src_sub.exists():
                shutil.copytree(src_sub, target_dir / subdir)

        # 3c. Scripts (gated by with_scripts)
        scripts_src = resolved.path / "scripts"
        if scripts_src.exists() and with_scripts:
            shutil.copytree(scripts_src, target_dir / "scripts")
            result.scripts_imported = True
        elif scripts_src.exists():
            result.warnings.append(
                "Skipped scripts/ directory (use with_scripts=True to import)"
            )

        # 4. Write .source metadata
        self._write_source_metadata(target_dir, resolved, result)

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_skill_md(self, path: Path) -> tuple[dict, str]:
        """Parse a SKILL.md file into (frontmatter dict, markdown body)."""
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            return {}, raw
        rest = raw[3:].lstrip("\n")
        end = rest.find("\n---")
        if end == -1:
            return {}, raw
        fm_text = rest[:end]
        body = rest[end + 4 :].lstrip("\n")
        try:
            fm = yaml.safe_load(fm_text)
            if not isinstance(fm, dict):
                fm = {}
        except yaml.YAMLError:
            fm = {}
        return fm, body

    def _render_skill_md(self, frontmatter: dict, body: str) -> str:
        """Re-serialize a SKILL.md file from frontmatter dict + body."""
        fm_text = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
        return f"---\n{fm_text}---\n\n{body}"

    def _write_source_metadata(
        self,
        target_dir: Path,
        resolved: ResolvedSkill,
        result: ImportResult,
    ) -> None:
        """Write the .source TOML provenance file."""
        installed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        translated_str = ", ".join(f'"{t}"' for t in result.translated_tools)
        missing_str = ", ".join(f'"{t}"' for t in result.untranslated_tools)
        scripts_lower = "true" if result.scripts_imported else "false"

        content = (
            f'source = "{resolved.source}:{resolved.name}"\n'
            f'commit = "{resolved.commit}"\n'
            f'category = "{resolved.category}"\n'
            f'installed_at = "{installed_at}"\n'
            f"translated_tools = [{translated_str}]\n"
            f"missing_tools = [{missing_str}]\n"
            f"scripts_imported = {scripts_lower}\n"
        )
        (target_dir / ".source").write_text(content, encoding="utf-8")


__all__ = ["ImportResult", "SkillImporter"]
