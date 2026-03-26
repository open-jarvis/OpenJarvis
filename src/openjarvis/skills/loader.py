"""Skill loader — load and verify skill manifests from TOML files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from openjarvis.skills.types import SkillManifest, SkillStep

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


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
        steps.append(SkillStep(
            tool_name=step_data["tool_name"],
            arguments_template=step_data.get("arguments_template", "{}"),
            output_key=step_data.get("output_key", ""),
        ))

    manifest = SkillManifest(
        name=skill_data.get("name", path.stem),
        version=skill_data.get("version", "0.1.0"),
        description=skill_data.get("description", ""),
        author=skill_data.get("author", ""),
        steps=steps,
        required_capabilities=skill_data.get("required_capabilities", []),
        signature=skill_data.get("signature", ""),
        metadata=skill_data.get("metadata", {}),
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


def discover_skills(directory: str | Path) -> list[SkillManifest]:
    """Scan directory for TOML skill files and load them."""
    directory = Path(directory).expanduser()
    if not directory.exists():
        return []
    manifests = []
    for toml_file in sorted(directory.glob("*.toml")):
        try:
            manifests.append(load_skill(toml_file))
        except Exception:
            continue
    return manifests


__all__ = ["load_skill", "discover_skills"]
