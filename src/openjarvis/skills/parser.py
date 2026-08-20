"""SkillParser — strict spec validation + tolerant field mapping.

The parser is the single chokepoint for converting raw frontmatter dicts
into normalized SkillManifest instances.  It runs two passes:

1. Strict pass — validates required fields, length limits, naming rules.
2. Tolerant pass — maps non-spec top-level fields to their canonical
   locations under metadata.openjarvis.* via FIELD_MAPPING.

The mapping table is data, not code paths.  Adding support for a new
vendor's fields means adding entries to FIELD_MAPPING — no logic changes.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from openjarvis.skills.types import SkillManifest

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spec constants
# ---------------------------------------------------------------------------

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500

# Spec-allowed top-level frontmatter fields
SPEC_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

# ---------------------------------------------------------------------------
# Field mapping table — non-spec top-level fields → canonical locations
# ---------------------------------------------------------------------------

# Each entry maps a non-spec top-level field name to (target_kind, attr).
# When target_kind is "field" the value is set directly on the SkillManifest
# dataclass attribute.  When target_kind is "openjarvis_meta" the value is
# stored under manifest.metadata["openjarvis"][attr].
FIELD_MAPPING: Dict[str, tuple[str, str]] = {
    "version": ("field", "version"),
    "author": ("field", "author"),
    "tags": ("field", "tags"),
    "depends": ("field", "depends"),
    "required_capabilities": ("field", "required_capabilities"),
    "user_invocable": ("field", "user_invocable"),
    "disable_model_invocation": ("field", "disable_model_invocation"),
    "platforms": ("openjarvis_meta", "platforms"),
    "prerequisites": ("openjarvis_meta", "prerequisites"),
}

# Naming pattern: lowercase alnum + hyphens, no leading/trailing/consecutive hyphens
_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$|^[a-z0-9]$")


class SkillParseError(ValueError):
    """Raised when a skill frontmatter cannot be parsed."""


class SkillParser:
    """Parse SKILL.md frontmatter into a SkillManifest.

    Two-pass design:

    - :meth:`parse_frontmatter` runs the strict pass + tolerant pass and
      returns a normalized :class:`SkillManifest`.
    """

    def parse_frontmatter(
        self,
        frontmatter: Dict[str, Any],
        *,
        markdown_content: str = "",
    ) -> SkillManifest:
        """Parse a frontmatter dict, returning a SkillManifest.

        Runs strict validation first, then applies tolerant field mapping.
        """
        self._validate_strict(frontmatter)
        return self._build_manifest(frontmatter, markdown_content)

    # ------------------------------------------------------------------
    # Strict pass
    # ------------------------------------------------------------------

    def _validate_strict(self, frontmatter: Dict[str, Any]) -> None:
        """Validate required fields, length limits, and naming rules."""
        # Required fields
        if "name" not in frontmatter:
            raise SkillParseError("Missing required field in frontmatter: name")
        if "description" not in frontmatter:
            raise SkillParseError("Missing required field in frontmatter: description")

        name = frontmatter["name"]
        description = frontmatter["description"]

        # Type check
        if not isinstance(name, str):
            raise SkillParseError(f"Field 'name' must be a string, got {type(name)}")
        if not isinstance(description, str):
            raise SkillParseError(
                f"Field 'description' must be a string, got {type(description)}"
            )

        # Length limits
        if len(name) == 0 or len(name) > MAX_NAME_LENGTH:
            raise SkillParseError(
                f"Field 'name' must be 1-{MAX_NAME_LENGTH} chars, got {len(name)}"
            )
        if len(description) == 0 or len(description) > MAX_DESCRIPTION_LENGTH:
            raise SkillParseError(
                f"Field 'description' must be 1-{MAX_DESCRIPTION_LENGTH} chars, "
                f"got {len(description)}"
            )

        # Naming rules
        self._validate_name(name)

        # compatibility length (optional field)
        compat = frontmatter.get("compatibility")
        if compat is not None:
            if not isinstance(compat, str):
                raise SkillParseError("Field 'compatibility' must be a string")
            if len(compat) > MAX_COMPATIBILITY_LENGTH:
                raise SkillParseError(
                    f"Field 'compatibility' exceeds {MAX_COMPATIBILITY_LENGTH} chars"
                )

    def _validate_name(self, name: str) -> None:
        """Validate the spec naming rules for a skill name."""
        if name != name.lower():
            raise SkillParseError(f"Skill name '{name}' must be lowercase")
        if name.startswith("-") or name.endswith("-"):
            raise SkillParseError(
                f"Skill name '{name}' must not start or end with a hyphen"
            )
        if "--" in name:
            raise SkillParseError(
                f"Skill name '{name}' must not contain consecutive hyphens"
            )
        for ch in name:
            if not (ch.isalnum() or ch == "-"):
                raise SkillParseError(
                    f"Skill name '{name}' contains invalid character '{ch}'; "
                    f"only lowercase alphanumeric and hyphens are allowed"
                )

    # ------------------------------------------------------------------
    # Build manifest (placeholder — Task 2 adds tolerant pass)
    # ------------------------------------------------------------------

    def _build_manifest(
        self,
        frontmatter: Dict[str, Any],
        markdown_content: str,
    ) -> SkillManifest:
        """Construct a SkillManifest from validated frontmatter.

        Runs the tolerant pass: applies FIELD_MAPPING for non-spec fields,
        captures unknown fields under metadata.openjarvis.original_frontmatter,
        and merges metadata.openjarvis.* into canonical fields.
        """
        # Start with required + optional spec fields
        manifest = SkillManifest(
            name=frontmatter["name"],
            description=frontmatter["description"],
            markdown_content=markdown_content,
        )

        # Pre-existing metadata block (if any)
        raw_metadata = frontmatter.get("metadata") or {}
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        # Initialize openjarvis namespace
        oj_meta = dict(raw_metadata.get("openjarvis") or {})

        # Apply FIELD_MAPPING for non-spec top-level fields
        unmapped: Dict[str, Any] = {}
        for key, value in frontmatter.items():
            if key in SPEC_FIELDS:
                continue
            if key in FIELD_MAPPING:
                target, attr = FIELD_MAPPING[key]
                if target == "field":
                    setattr(manifest, attr, value)
                else:  # "openjarvis_meta"
                    oj_meta[attr] = value
            else:
                unmapped[key] = value
                LOGGER.warning(
                    "Unmapped frontmatter field '%s' in skill '%s' "
                    "(value preserved in metadata.openjarvis.original_frontmatter)",
                    key,
                    manifest.name,
                )

        # Merge metadata.openjarvis.* into canonical fields (these override
        # top-level mappings since they are explicit OpenJarvis-namespaced).
        for key in (
            "version",
            "author",
            "tags",
            "depends",
            "required_capabilities",
            "user_invocable",
            "disable_model_invocation",
        ):
            if key in oj_meta:
                setattr(manifest, key, oj_meta[key])

        # Preserve unmapped fields under metadata.openjarvis.original_frontmatter
        if unmapped:
            oj_meta["original_frontmatter"] = unmapped

        # Stash the openjarvis metadata block back
        if oj_meta:
            new_metadata = dict(raw_metadata)
            new_metadata["openjarvis"] = oj_meta
            manifest.metadata = new_metadata
        else:
            manifest.metadata = raw_metadata

        return manifest


__all__ = ["SkillParseError", "SkillParser", "SPEC_FIELDS", "FIELD_MAPPING"]
