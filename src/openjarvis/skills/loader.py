"""Skill loader — load and verify skill manifests from TOML files."""

from __future__ import annotations

import json
import urllib.parse
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

_SUPPORTED_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "minLength",
    "minimum",
    "maximum",
    "enum",
    "items",
}
_SUPPORTED_SCHEMA_TYPES = {"object", "array", "string", "integer", "number", "boolean"}


def _validate_schema_node(schema: object, path: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"input_schema {path} must be an object")

    unsupported = set(schema) - _SUPPORTED_SCHEMA_KEYS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"input_schema {path} uses unsupported keyword(s): {names}")

    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in _SUPPORTED_SCHEMA_TYPES:
        raise ValueError(f"input_schema {path}.type is unsupported")

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError(f"input_schema {path}.properties must be an object")
        for name, child in properties.items():
            if not isinstance(name, str):
                raise ValueError(
                    f"input_schema {path}.properties names must be strings"
                )
            _validate_schema_node(child, f"{path}.properties.{name}")

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or not all(
            isinstance(name, str) for name in required
        ):
            raise ValueError(f"input_schema {path}.required must be a string list")
        declared = set(properties or {})
        if not set(required).issubset(declared):
            raise ValueError(
                f"input_schema {path}.required contains undeclared properties"
            )

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        raise ValueError(
            f"input_schema {path}.additionalProperties must be a boolean"
        )

    min_length = schema.get("minLength")
    if min_length is not None and (
        not isinstance(min_length, int)
        or isinstance(min_length, bool)
        or min_length < 0
    ):
        raise ValueError(
            f"input_schema {path}.minLength must be a non-negative integer"
        )

    for keyword in ("minimum", "maximum"):
        value = schema.get(keyword)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ValueError(f"input_schema {path}.{keyword} must be a number")

    if "enum" in schema and not isinstance(schema["enum"], list):
        raise ValueError(f"input_schema {path}.enum must be an array")

    if "items" in schema:
        _validate_schema_node(schema["items"], f"{path}.items")


def _parse_input_schema(skill_data: dict) -> dict:
    if "input_schema_json" not in skill_data:
        return {}
    try:
        schema = json.loads(skill_data["input_schema_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("input_schema_json must contain valid JSON") from exc
    if not isinstance(schema, dict):
        raise ValueError("input_schema must be an object")
    _validate_schema_node(schema, "root")
    if schema.get("type") != "object":
        raise ValueError("input_schema root type must be object")
    if not isinstance(schema.get("properties"), dict):
        raise ValueError("input_schema root properties must be an object")
    return schema


def _validate_request_recipe_metadata(recipe: object, input_schema: dict) -> None:
    if not isinstance(recipe, dict):
        raise ValueError("request_recipe metadata must be an object")

    origin = recipe.get("origin")
    try:
        parsed = urllib.parse.urlsplit(origin if isinstance(origin, str) else "")
        parsed.port
    except ValueError as exc:
        raise ValueError("request_recipe origin must be a valid HTTP origin") from exc
    valid_origin = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
    if not valid_origin:
        raise ValueError("request_recipe origin must be a valid HTTP origin")
    if recipe.get("method") not in {"GET", "HEAD"}:
        raise ValueError("request_recipe method must be exactly GET or HEAD")
    if recipe.get("read_only") is not True:
        raise ValueError("request_recipe read_only must be true")
    if input_schema.get("additionalProperties") is not False:
        raise ValueError(
            "request_recipe input_schema additionalProperties must be false"
        )


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
    input_schema = _parse_input_schema(skill_data)
    if skill_data.get("checkout", False) and "input_schema_json" in skill_data:
        raise ValueError("checkout skill cannot replace its guarded input schema")

    metadata = skill_data.get("metadata", {})
    openjarvis_metadata = (
        metadata.get("openjarvis", {}) if isinstance(metadata, dict) else {}
    )
    if (
        isinstance(openjarvis_metadata, dict)
        and "request_recipe" in openjarvis_metadata
    ):
        _validate_request_recipe_metadata(
            openjarvis_metadata["request_recipe"], input_schema
        )

    steps = []
    for step_data in skill_data.get("steps", []):
        steps.append(
            SkillStep(
                tool_name=step_data.get("tool_name", ""),
                skill_name=step_data.get("skill_name", ""),
                arguments_template=step_data.get("arguments_template", "{}"),
                output_key=step_data.get("output_key", ""),
                assertions=(
                    json.loads(step_data["assertions_json"])
                    if "assertions_json" in step_data
                    else step_data.get("assertions", [])
                ),
            )
        )

    manifest = SkillManifest(
        name=skill_data.get("name", path.stem),
        checkout=skill_data.get("checkout", False),
        accepts_cart_lines=skill_data.get("accepts_cart_lines", False),
        version=skill_data.get("version", "0.1.0"),
        description=skill_data.get("description", ""),
        author=skill_data.get("author", ""),
        steps=steps,
        required_capabilities=skill_data.get("required_capabilities", []),
        signature=skill_data.get("signature", ""),
        metadata=metadata,
        input_schema=input_schema,
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
                input_schema=manifest.input_schema,
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
