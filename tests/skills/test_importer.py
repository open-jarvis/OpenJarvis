"""Tests for SkillImporter — installs ResolvedSkill instances on disk."""

from __future__ import annotations

from pathlib import Path

from openjarvis.skills.importer import SkillImporter
from openjarvis.skills.parser import SkillParser
from openjarvis.skills.sources.base import ResolvedSkill
from openjarvis.skills.tool_translator import ToolTranslator


def _make_resolved(tmp_path: Path, body: str = "Body") -> ResolvedSkill:
    """Create a fake source skill directory and return a ResolvedSkill."""
    src_dir = tmp_path / "source" / "my-skill"
    src_dir.mkdir(parents=True)
    (src_dir / "SKILL.md").write_text(
        f"---\nname: my-skill\ndescription: A test skill\n---\n{body}"
    )
    return ResolvedSkill(
        name="my-skill",
        source="hermes",
        path=src_dir,
        category="testing",
        description="A test skill",
        commit="abc123",
    )


class TestImportSkill:
    def test_imports_to_sourced_subdir(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        resolved = _make_resolved(tmp_path)
        result = importer.import_skill(resolved)

        assert result.success
        target = target_root / "hermes" / "my-skill"
        assert target.exists()
        assert (target / "SKILL.md").exists()

    def test_writes_source_metadata_file(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        resolved = _make_resolved(tmp_path)
        importer.import_skill(resolved)

        source_file = target_root / "hermes" / "my-skill" / ".source"
        assert source_file.exists()
        content = source_file.read_text()
        assert "source = " in content
        assert "abc123" in content
        assert "scripts_imported = false" in content

    def test_translates_tool_references_in_body(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        resolved = _make_resolved(
            tmp_path, body="First use the Bash tool, then Read the file."
        )
        result = importer.import_skill(resolved)

        installed = target_root / "hermes" / "my-skill" / "SKILL.md"
        body = installed.read_text()
        assert "shell_exec" in body
        assert "file_read" in body
        assert "Bash" not in body
        assert "Bash->shell_exec" in str(result.translated_tools)

    def test_scripts_skipped_by_default(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        # Source has a scripts/ directory
        src_dir = tmp_path / "source" / "my-skill"
        src_dir.mkdir(parents=True)
        (src_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: x\n---\n")
        scripts_dir = src_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.py").write_text("print('hi')")

        resolved = ResolvedSkill(
            name="my-skill",
            source="hermes",
            path=src_dir,
            category="x",
            description="x",
            commit="a",
        )
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        result = importer.import_skill(resolved)

        target = target_root / "hermes" / "my-skill"
        assert not (target / "scripts").exists()
        assert result.scripts_imported is False

    def test_scripts_imported_with_flag(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        src_dir = tmp_path / "source" / "my-skill"
        src_dir.mkdir(parents=True)
        (src_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: x\n---\n")
        scripts_dir = src_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.py").write_text("print('hi')")

        resolved = ResolvedSkill(
            name="my-skill",
            source="hermes",
            path=src_dir,
            category="x",
            description="x",
            commit="a",
        )
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        result = importer.import_skill(resolved, with_scripts=True)

        target = target_root / "hermes" / "my-skill"
        assert (target / "scripts" / "helper.py").exists()
        assert result.scripts_imported is True

    def test_references_assets_always_copied(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        src_dir = tmp_path / "source" / "my-skill"
        src_dir.mkdir(parents=True)
        (src_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: x\n---\n")
        (src_dir / "references").mkdir()
        (src_dir / "references" / "REFERENCE.md").write_text("# Reference")
        (src_dir / "assets").mkdir()
        (src_dir / "assets" / "template.txt").write_text("template")

        resolved = ResolvedSkill(
            name="my-skill",
            source="hermes",
            path=src_dir,
            category="x",
            description="x",
            commit="a",
        )
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        importer.import_skill(resolved)

        target = target_root / "hermes" / "my-skill"
        assert (target / "references" / "REFERENCE.md").exists()
        assert (target / "assets" / "template.txt").exists()

    def test_force_overwrites_existing_install(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        resolved = _make_resolved(tmp_path, body="Original body")
        importer.import_skill(resolved)

        # Modify source and re-import with force
        (resolved.path / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\nUpdated body"
        )
        importer.import_skill(resolved, force=True)

        installed = target_root / "hermes" / "my-skill" / "SKILL.md"
        assert "Updated body" in installed.read_text()

    def test_install_without_force_skips_existing(self, tmp_path: Path):
        target_root = tmp_path / "skills"
        importer = SkillImporter(
            parser=SkillParser(),
            tool_translator=ToolTranslator(),
            target_root=target_root,
        )
        resolved = _make_resolved(tmp_path, body="Original")
        importer.import_skill(resolved)

        (resolved.path / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\nNew body"
        )
        result = importer.import_skill(resolved, force=False)
        assert result.skipped

        installed = target_root / "hermes" / "my-skill" / "SKILL.md"
        assert "Original" in installed.read_text()
