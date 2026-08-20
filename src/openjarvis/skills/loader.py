"""Skill loader — load and verify skill manifests from TOML files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from openjarvis.skills.types import SkillManifest, SkillStep

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import logging

LOGGER = logging.getLogger(__name__)


def _read_source_metadata(path: Path) -> dict:
    """Read .source TOML file if present, returning the parsed dict.

    Returns an empty dict if the file is missing or malformed.  Never
    raises — bad sidecar files should never break skill loading.  Logs
    a warning when a malformed file is encountered so users can debug
    why their imported source provenance is missing.
    """
    source_path = path / ".source"
    if not source_path.exists():
        return {}
    try:
        with open(source_path, "rb") as fh:
            return tomllib.load(fh)
    except Exception as exc:
        LOGGER.warning(
            "Malformed .source sidecar at %s (skill source provenance "
            "will be missing): %s",
            source_path,
            exc,
        )
        return {}


def load_skill(
    path: str | Path,
    *,
    verify_signature: bool = False,
    public_key: Optional[bytes] = None,
    scan_for_injection: bool = False,
) -> SkillManifest:
    """Load a skill manifest from a TOML file.

    Expected format:
    ```toml
    [skill]
    name = "research_and_summarize"
    version = "0.1.0"
    description = "Search web and summarize results"
    author = "openjarvis"
    required_capabilities = ["network:fetch"]
    signature = ""

    [[skill.steps]]
    tool_name = "web_search"
    arguments_template = '{"query": "{query}"}'
    output_key = "search_results"

    [[skill.steps]]
    tool_name = "think"
    arguments_template = '{"thought": "Summarize: {search_results}"}'
    output_key = "summary"
    ```
    """
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)

    skill_data = data.get("skill", {})

    steps = []
    for step_data in skill_data.get("steps", []):
        steps.append(
            SkillStep(
                tool_name=step_data.get("tool_name", ""),
                skill_name=step_data.get("skill_name", ""),
                arguments_template=step_data.get("arguments_template", "{}"),
                output_key=step_data.get("output_key", ""),
            )
        )

    manifest = SkillManifest(
        name=skill_data.get("name", path.stem),
        version=skill_data.get("version", "0.1.0"),
        description=skill_data.get("description", ""),
        author=skill_data.get("author", ""),
        steps=steps,
        required_capabilities=skill_data.get("required_capabilities", []),
        signature=skill_data.get("signature", ""),
        metadata=skill_data.get("metadata", {}),
        tags=skill_data.get("tags", []),
        depends=skill_data.get("depends", []),
        user_invocable=skill_data.get("user_invocable", True),
        disable_model_invocation=skill_data.get("disable_model_invocation", False),
    )

    # Verify signature if requested
    if verify_signature and public_key and manifest.signature:
        try:
            from openjarvis.security.signing import verify_b64

            valid = verify_b64(
                manifest.manifest_bytes(),
                manifest.signature,
                public_key,
            )
            if not valid:
                raise ValueError(f"Invalid signature for skill '{manifest.name}'")
        except ImportError:
            raise ImportError(
                "Signature verification requires 'cryptography'. "
                "Install with: uv sync --extra security-signing"
            )

    # Scan for prompt injection if requested
    if scan_for_injection:
        try:
            from openjarvis.security.scanner import SecretScanner

            scanner = SecretScanner()
            for step in manifest.steps:
                scan_result = scanner.scan(step.arguments_template)
                if scan_result.findings:
                    raise ValueError(
                        f"Potential prompt injection in skill '{manifest.name}', "
                        f"step '{step.tool_name}': "
                        f"{scan_result.findings[0].description}"
                    )
        except ImportError:
            pass

    return manifest


def load_skill_markdown(path: str | Path) -> SkillManifest:
    """Load a skill manifest from a SKILL.md file via SkillParser.

    Parses YAML frontmatter (between ``---`` delimiters) and the markdown
    body, then runs them through :class:`SkillParser` for strict validation
    and tolerant field mapping.
    """
    from openjarvis.skills.parser import SkillParseError, SkillParser

    path = Path(path)
    raw = path.read_text(encoding="utf-8")

    frontmatter: dict = {}
    markdown_content = raw

    if raw.startswith("---"):
        rest = raw[3:]
        if rest.startswith("\n"):
            rest = rest[1:]
        end_idx = rest.find("\n---")
        if end_idx != -1:
            yaml_block = rest[:end_idx]
            try:
                frontmatter = yaml.safe_load(yaml_block) or {}
            except yaml.YAMLError:
                frontmatter = {}
            after = rest[end_idx + 4 :]
            if after.startswith("\n"):
                after = after[1:]
            markdown_content = after

    # Default name to file stem if missing (preserves legacy behavior)
    if "name" not in frontmatter:
        frontmatter["name"] = path.stem
    if "description" not in frontmatter:
        frontmatter["description"] = frontmatter.get("name", path.stem)

    parser = SkillParser()
    try:
        return parser.parse_frontmatter(frontmatter, markdown_content=markdown_content)
    except SkillParseError:
        # Legacy fallback — build manifest directly without strict validation
        return SkillManifest(
            name=str(frontmatter.get("name", path.stem)),
            description=str(frontmatter.get("description", "")),
            version=str(frontmatter.get("version", "0.1.0")),
            author=str(frontmatter.get("author", "")),
            tags=list(frontmatter.get("tags", []) or []),
            required_capabilities=list(
                frontmatter.get("required_capabilities", []) or []
            ),
            user_invocable=bool(frontmatter.get("user_invocable", True)),
            disable_model_invocation=bool(
                frontmatter.get("disable_model_invocation", False)
            ),
            markdown_content=markdown_content,
        )


def load_skill_directory(path: str | Path) -> SkillManifest:
    """Load a skill from a directory containing ``skill.toml`` and/or ``SKILL.md``.

    - If only ``skill.toml`` is present the manifest is loaded from TOML.
    - If only ``SKILL.md`` is present the manifest is loaded from markdown.
    - If both are present the TOML manifest takes precedence for structured
      fields and ``markdown_content`` is merged in from the markdown file.
    - If neither is present a ``FileNotFoundError`` is raised.
    """
    path = Path(path)
    toml_path = path / "skill.toml"
    md_path = path / "SKILL.md"

    has_toml = toml_path.exists()
    has_md = md_path.exists()

    if not has_toml and not has_md:
        raise FileNotFoundError(
            f"No skill.toml or SKILL.md found in directory '{path}'"
        )

    if has_toml:
        manifest = load_skill(toml_path)
        if has_md:
            md_manifest = load_skill_markdown(md_path)
            # Merge markdown content into the TOML-sourced manifest
            manifest = SkillManifest(
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                author=manifest.author,
                steps=manifest.steps,
                required_capabilities=manifest.required_capabilities,
                signature=manifest.signature,
                metadata=manifest.metadata,
                tags=manifest.tags,
                depends=manifest.depends,
                user_invocable=manifest.user_invocable,
                disable_model_invocation=manifest.disable_model_invocation,
                markdown_content=md_manifest.markdown_content,
            )
    else:
        # Only markdown present
        manifest = load_skill_markdown(md_path)

    # Promote .source file's source field into manifest.metadata.openjarvis.source
    source_data = _read_source_metadata(path)
    if source_data:
        # Extract just the source name (e.g. "hermes" from "hermes:apple-notes")
        source_str = source_data.get("source", "")
        source_name = source_str.partition(":")[0] if source_str else ""
        if source_name:
            new_metadata = dict(manifest.metadata) if manifest.metadata else {}
            oj = dict(new_metadata.get("openjarvis", {}) or {})
            oj["source"] = source_name
            new_metadata["openjarvis"] = oj
            manifest.metadata = new_metadata

    return manifest


def discover_skills(directory: str | Path) -> list[SkillManifest]:
    """Scan a directory for skill definitions and load them.

    Handles three layouts:
    - Flat ``*.toml`` files directly inside *directory*.
    - Skill directories: ``<directory>/<name>/{skill.toml,SKILL.md}``.
    - Sourced layout: ``<directory>/<source>/<name>/{skill.toml,SKILL.md}``.
    """
    directory = Path(directory).expanduser()
    if not directory.exists():
        return []

    manifests: list[SkillManifest] = []

    # Flat *.toml files at the top level
    for toml_file in sorted(directory.glob("*.toml")):
        try:
            manifests.append(load_skill(toml_file))
        except Exception:
            continue

    # Walk one or two levels deep looking for skill packages
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        # Direct skill package: <child>/{skill.toml,SKILL.md}
        if (child / "skill.toml").exists() or (child / "SKILL.md").exists():
            try:
                manifests.append(load_skill_directory(child))
            except Exception:
                continue
            continue

        # Sourced layout: <child>/<grandchild>/{skill.toml,SKILL.md}
        for grandchild in sorted(child.iterdir()):
            if not grandchild.is_dir():
                continue
            if (grandchild / "skill.toml").exists() or (
                grandchild / "SKILL.md"
            ).exists():
                try:
                    manifests.append(load_skill_directory(grandchild))
                except Exception:
                    continue

    return manifests


__all__ = [
    "load_skill",
    "load_skill_markdown",
    "load_skill_directory",
    "discover_skills",
]
