"""Read-only inspection adapter for local, untrusted legacy skill fixtures."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 compatibility
    import tomli as tomllib  # type: ignore[no-redef]

from openjarvis.learning.skills.manifest import SkillManifestDraft

_ALLOWED_NAMES = frozenset({"skill.toml", "SKILL.md", "skill.md", "optimized.toml"})
_KNOWN_TOP_LEVEL = frozenset({"skill", "optimized", "name", "description", "metadata"})
_KNOWN_SKILL_FIELDS = frozenset(
    {
        "name",
        "version",
        "description",
        "author",
        "tags",
        "steps",
        "required_capabilities",
        "depends",
        "user_invocable",
        "disable_model_invocation",
    }
)


class LegacySkillAssessment(BaseModel):
    """Metadata-only result; it never registers or activates a legacy skill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    source_digest: str
    metadata: dict[str, Any]
    unknown_fields: tuple[str, ...]
    findings: tuple[str, ...]
    quarantined: bool = True
    draft: SkillManifestDraft | None = None


class LegacySkillAdapter:
    """Inspect one explicitly supplied local fixture without following links."""

    def __init__(self, *, maximum_bytes: int = 262_144) -> None:
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        self._maximum_bytes = maximum_bytes

    def inspect(self, path: Path) -> LegacySkillAssessment:
        path = Path(path)
        if path.name not in _ALLOWED_NAMES:
            raise ValueError("unsupported legacy skill metadata file")
        if path.is_symlink():
            raise ValueError("legacy adapter does not follow symbolic links")
        size = path.stat().st_size
        if size > self._maximum_bytes:
            raise ValueError("legacy skill metadata exceeds size limit")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        data = self._parse(path, raw)
        unknown_fields = set(data) - _KNOWN_TOP_LEVEL
        skill = data.get("skill")
        if isinstance(skill, dict):
            unknown_fields.update(
                f"skill.{key}" for key in set(skill) - _KNOWN_SKILL_FIELDS
            )
        unknown = tuple(sorted(unknown_fields))
        findings = list(self._scan(raw.decode("utf-8"), data))
        if unknown:
            findings.append("unknown_fields")
        return LegacySkillAssessment(
            source_path=str(path.resolve(strict=False)),
            source_digest=digest,
            metadata=self._metadata_only(data),
            unknown_fields=unknown,
            findings=tuple(sorted(set(findings))),
            draft=None,
        )

    @staticmethod
    def _parse(path: Path, raw: bytes) -> dict[str, Any]:
        if path.suffix.lower() == ".toml":
            data = tomllib.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        text = raw.decode("utf-8")
        if not text.startswith("---"):
            return {"description": text[:1024]}
        remainder = text[3:].lstrip("\r\n")
        marker = remainder.find("\n---")
        if marker < 0:
            return {}
        parsed = yaml.safe_load(remainder[:marker])
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _metadata_only(data: dict[str, Any]) -> dict[str, Any]:
        source = data.get("skill") if isinstance(data.get("skill"), dict) else data
        return {
            key: source[key]
            for key in ("name", "version", "author", "tags")
            if key in source and isinstance(source[key], (str, int, bool, list))
        }

    @staticmethod
    def _scan(text: str, data: dict[str, Any]) -> tuple[str, ...]:
        lowered = text.lower()
        findings: list[str] = []
        if any(marker in lowered for marker in ("eval(", "exec(", "pickle.loads")):
            findings.append("forbidden_code")
        if any(marker in lowered for marker in ("full_access", "always allow")):
            findings.append("authority_escalation")
        if any(marker in lowered for marker in ("http://", "https://")):
            findings.append("external_url")
        if any(marker in lowered for marker in ("password=", "api_key=", "token=")):
            findings.append("secret_like_material")
        skill = data.get("skill")
        if isinstance(skill, dict) and skill.get("steps"):
            findings.append("untrusted_executable_steps")
        return tuple(findings)


__all__ = ["LegacySkillAdapter", "LegacySkillAssessment"]
