"""Complete metadata-only policy planning for Phase 8 backups."""

from __future__ import annotations

import argparse
import json
import os
import stat
from collections import Counter
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from openjarvis.migration.backup import (
    SENSITIVE_DIRECTORY_NAMES,
    SENSITIVE_FILE_NAMES,
    TECHNICAL_DIRECTORIES,
    WINDOWS_SAFE_TARGET_PATH_LENGTH,
)


class PolicyPlanningError(RuntimeError):
    """Raised when policy planning cannot safely inspect metadata."""


class PathCategory(StrEnum):
    MIGRATION_SOURCE_CODE = "migration_source_code"
    MIGRATION_TEST = "migration_test"
    MIGRATION_DOCUMENTATION = "migration_documentation"
    MIGRATION_CONFIGURATION = "migration_configuration"
    MIGRATION_SKILL_METADATA = "migration_skill_metadata"
    MIGRATION_WORKFLOW_METADATA = "migration_workflow_metadata"
    RUNTIME_STATE_METADATA_ONLY = "runtime_state_metadata_only"
    MODEL_ARTIFACT_METADATA_ONLY = "model_artifact_metadata_only"
    TECHNICAL_CACHE_EXCLUDED = "technical_cache_excluded"
    BUILD_ARTIFACT_EXCLUDED = "build_artifact_excluded"
    CREDENTIAL_OR_SESSION_PROHIBITED = "credential_or_session_prohibited"
    BROWSER_RUNTIME_PROHIBITED = "browser_runtime_prohibited"
    TEMPORARY_EXCLUDED = "temporary_excluded"
    UNKNOWN_REVIEW_REQUIRED = "unknown_review_required"


@dataclass(frozen=True, slots=True)
class CategoryPolicy:
    definition: str
    root_context_rules: str
    backup_decision: str
    content_access_allowed: bool
    hashing_allowed: bool
    migration_allowed: bool
    reason: str


CATEGORY_POLICIES: dict[PathCategory, CategoryPolicy] = {
    PathCategory.MIGRATION_SOURCE_CODE: CategoryPolicy(
        "Application and support source code.",
        "backend/, frontend/, desktop/, scripts/, training code, or safe root code.",
        "content_backup",
        True,
        True,
        True,
        "Required for selective logic and test review.",
    ),
    PathCategory.MIGRATION_TEST: CategoryPolicy(
        "Test code and deterministic fixtures.",
        "test/, tests/, evals/, test-named paths inside source roots.",
        "content_backup",
        True,
        True,
        True,
        "Candidate for isolated test porting.",
    ),
    PathCategory.MIGRATION_DOCUMENTATION: CategoryPolicy(
        "Documentation without runtime authority.",
        "docs/ or documentation files outside prohibited roots.",
        "content_backup",
        True,
        True,
        True,
        "Supports traceable migration decisions.",
    ),
    PathCategory.MIGRATION_CONFIGURATION: CategoryPolicy(
        "Non-secret static project configuration.",
        "config/ or recognized configuration files after secret checks.",
        "content_backup",
        True,
        True,
        True,
        "Configuration can be reviewed but never trusted automatically.",
    ),
    PathCategory.MIGRATION_SKILL_METADATA: CategoryPolicy(
        "Legacy skill definitions treated as untrusted metadata.",
        "skills/ after credential and artifact exclusions.",
        "content_backup",
        True,
        True,
        False,
        "Skills require quarantine and explicit later review.",
    ),
    PathCategory.MIGRATION_WORKFLOW_METADATA: CategoryPolicy(
        "Legacy workflow or automation definitions as metadata.",
        "automations/ or workflows/ after prohibited-data checks.",
        "content_backup",
        True,
        True,
        False,
        "Workflows must never become active through backup.",
    ),
    PathCategory.RUNTIME_STATE_METADATA_ONLY: CategoryPolicy(
        "Runtime state represented only by filesystem metadata.",
        "state/ or runtime/, excluding model/cache/prohibited subtrees.",
        "metadata_only",
        False,
        False,
        False,
        "Historical runtime payloads are not trusted migration input.",
    ),
    PathCategory.MODEL_ARTIFACT_METADATA_ONLY: CategoryPolicy(
        "Model weights or downloaded model assets represented only by metadata.",
        "state/models/ or model-weight extensions outside a cache subtree.",
        "metadata_only",
        False,
        False,
        False,
        "Model binaries are not migration-relevant project content.",
    ),
    PathCategory.TECHNICAL_CACHE_EXCLUDED: CategoryPolicy(
        "Generated cache or model-download cache.",
        "Cache names only inside known runtime/model/generated contexts.",
        "exclude",
        False,
        False,
        False,
        "Regenerable cache data is excluded without content access.",
    ),
    PathCategory.BUILD_ARTIFACT_EXCLUDED: CategoryPolicy(
        "Dependency, VCS, build, or compiler artifact.",
        ".git, .venv, node_modules, build, dist, target, and related roots.",
        "exclude",
        False,
        False,
        False,
        "Build and dependency artifacts are not restore inputs.",
    ),
    PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED: CategoryPolicy(
        "Credential, token, cookie, secret, or session material.",
        "Known sensitive file and directory names in any root.",
        "prohibit",
        False,
        False,
        False,
        "Credential and session content must not be read or copied.",
    ),
    PathCategory.BROWSER_RUNTIME_PROHIBITED: CategoryPolicy(
        "Browser profile or browser runtime state.",
        "Known browser-profile and User Data directory names.",
        "prohibit",
        False,
        False,
        False,
        "Real browser state and accounts are outside migration scope.",
    ),
    PathCategory.TEMPORARY_EXCLUDED: CategoryPolicy(
        "Temporary files, logs, tool output, or generated transient data.",
        "temp/tmp/log roots or transient suffixes in technical contexts.",
        "exclude",
        False,
        False,
        False,
        "Transient data has no controlled restore role.",
    ),
    PathCategory.UNKNOWN_REVIEW_REQUIRED: CategoryPolicy(
        "Path without a complete root-based policy decision.",
        "Any root or file purpose not covered by an explicit rule.",
        "review_required",
        False,
        False,
        False,
        "Unknown data blocks backup simulation until explicitly classified.",
    ),
}


CONTENT_CATEGORIES = frozenset(
    {
        PathCategory.MIGRATION_SOURCE_CODE,
        PathCategory.MIGRATION_TEST,
        PathCategory.MIGRATION_DOCUMENTATION,
        PathCategory.MIGRATION_CONFIGURATION,
        PathCategory.MIGRATION_SKILL_METADATA,
        PathCategory.MIGRATION_WORKFLOW_METADATA,
    }
)

PROTECTED_CONTENT_ROOTS = frozenset({"docs", "src", "test", "tests"})
SOURCE_ROOTS = frozenset(
    {"backend", "desktop", "frontend", "scripts", "src", "training"}
)
TEST_ROOTS = frozenset({"evals", "test", "tests"})
DOCUMENTATION_ROOTS = frozenset({"docs"})
CONFIGURATION_ROOTS = frozenset({"config"})
SKILL_ROOTS = frozenset({"skills"})
WORKFLOW_ROOTS = frozenset({"automations", "workflows"})
RUNTIME_ROOTS = frozenset({"runtime", "state"})
MODEL_ROOT_NAMES = frozenset({"model-data", "model_data", "models"})
GENERATED_ROOT_NAMES = frozenset(
    {"artifacts", "generated", "generated-data", "generated_data", "var"}
)
TEMPORARY_ROOT_NAMES = frozenset({"logs", "temp", "temporary", "tmp"})
BROWSER_RUNTIME_NAMES = frozenset(
    {
        "browser-profile",
        "browser-profiles",
        "browser_profile",
        "browser_profiles",
        "playwright-profile",
        "playwright_profile",
        "user data",
    }
)
CACHE_NAMES = frozenset({".cache", "cache", "caches", "review-cache"})
MODEL_DOWNLOAD_NAMES = frozenset({"blobs", "download", "downloads", "snapshots"})
MODEL_WEIGHT_SUFFIXES = frozenset(
    {".bin", ".ckpt", ".gguf", ".onnx", ".pt", ".pth", ".safetensors"}
)
SOURCE_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".css",
        ".html",
        ".js",
        ".jsx",
        ".ps1",
        ".py",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".ts",
        ".tsx",
    }
)
DOCUMENTATION_SUFFIXES = frozenset({".md", ".rst"})
CONFIGURATION_SUFFIXES = frozenset(
    {".cfg", ".ini", ".json", ".lock", ".toml", ".yaml", ".yml"}
)
UNUSUAL_SEGMENT_LENGTH = 80


@dataclass(frozen=True, slots=True)
class PlanEntry:
    path: str
    entry_type: str
    file_type: str
    size: int | None
    mtime_ns: int
    category: PathCategory
    backup_decision: str
    content_access_allowed: bool
    hashing_allowed: bool
    migration_allowed: bool
    exclusion_reason: str | None
    relative_length: int
    planned_target_length: int
    longest_segment: int
    depth: int
    reparse_point: bool


@dataclass(frozen=True, slots=True)
class SimulationResult:
    passed: bool
    source_destination_disjoint: bool
    unknown_count: int
    unknown_long_path_count: int
    migration_long_path_count: int
    prohibited_content_backup_count: int
    reparse_points_not_followed: int
    violations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackupPlan:
    source_label: str
    destination_label: str
    target_root_length: int
    safe_target_limit: int
    source_stable: bool
    top_level: tuple[str, ...]
    entries: tuple[PlanEntry, ...]
    category_counts: dict[str, int]
    category_bytes: dict[str, int]
    extension_counts: dict[str, int]
    long_paths: tuple[PlanEntry, ...]
    safely_excluded_long_path_count: int
    migration_long_path_count: int
    unknown_long_path_count: int
    near_limit_paths: tuple[PlanEntry, ...]
    unusual_segment_paths: tuple[PlanEntry, ...]
    unknown_paths: tuple[PlanEntry, ...]
    maximum_planned_target_length: int
    maximum_safe_content_target_root_length: int
    simulation: SimulationResult


def _is_reparse(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _is_sensitive_file(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in SENSITIVE_FILE_NAMES
        or lowered.startswith(".env.")
        or lowered.endswith((".cookie", ".cookies", ".session"))
        or lowered.startswith(("credential.", "credentials.", "secret.", "token."))
    )


def _contains_contextual_cache(parts: tuple[str, ...]) -> bool:
    if not parts or parts[0] in PROTECTED_CONTENT_ROOTS:
        return False
    runtime_context = RUNTIME_ROOTS | MODEL_ROOT_NAMES | GENERATED_ROOT_NAMES
    for index, part in enumerate(parts):
        cache_name = part in CACHE_NAMES or part.endswith(("-cache", "_cache"))
        if cache_name and any(parent in runtime_context for parent in parts[:index]):
            return True
    in_model_root = parts[0] in RUNTIME_ROOTS and any(
        part in MODEL_ROOT_NAMES for part in parts[1:]
    )
    if (
        in_model_root
        and "huggingface" in parts
        and any(part in MODEL_DOWNLOAD_NAMES for part in parts)
    ):
        return True
    if (
        in_model_root
        and "piper" in parts
        and any(part in CACHE_NAMES for part in parts)
    ):
        return True
    return False


def _looks_like_test(parts: tuple[str, ...], name: str) -> bool:
    return (
        any(part in {"__tests__", "test", "tests"} for part in parts)
        or ".test." in name
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _looks_like_configuration(name: str, suffix: str) -> bool:
    return (
        suffix in CONFIGURATION_SUFFIXES
        or name.startswith(("pyproject.", "tsconfig.", "vite.config."))
        or name in {".gitattributes", ".gitignore", "package.json", "package-lock.json"}
    )


def classify_path(
    relative: Path, *, is_directory: bool, is_reparse: bool
) -> PathCategory:
    parts = tuple(part.casefold() for part in relative.parts)
    root = parts[0]
    name = parts[-1]
    suffix = Path(name).suffix.casefold()

    if is_reparse:
        return PathCategory.UNKNOWN_REVIEW_REQUIRED
    if name in BROWSER_RUNTIME_NAMES:
        return PathCategory.BROWSER_RUNTIME_PROHIBITED
    if name in SENSITIVE_DIRECTORY_NAMES or (
        not is_directory and _is_sensitive_file(name)
    ):
        return PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED
    if any(part in TECHNICAL_DIRECTORIES for part in parts):
        return PathCategory.BUILD_ARTIFACT_EXCLUDED
    if root == "deployment-backups":
        return PathCategory.BUILD_ARTIFACT_EXCLUDED
    if _contains_contextual_cache(parts):
        return PathCategory.TECHNICAL_CACHE_EXCLUDED
    if root in TEMPORARY_ROOT_NAMES:
        return PathCategory.TEMPORARY_EXCLUDED
    if root in RUNTIME_ROOTS and (
        name.endswith((".log", ".tmp", ".temp"))
        or any(part in TEMPORARY_ROOT_NAMES for part in parts[1:])
    ):
        return PathCategory.TEMPORARY_EXCLUDED
    in_model_root = root in RUNTIME_ROOTS and any(
        part in MODEL_ROOT_NAMES for part in parts[1:]
    )
    if in_model_root or suffix in MODEL_WEIGHT_SUFFIXES:
        return PathCategory.MODEL_ARTIFACT_METADATA_ONLY
    if root in RUNTIME_ROOTS:
        return PathCategory.RUNTIME_STATE_METADATA_ONLY
    if root in TEST_ROOTS or _looks_like_test(parts, name):
        return PathCategory.MIGRATION_TEST
    if root in DOCUMENTATION_ROOTS or suffix in DOCUMENTATION_SUFFIXES:
        return PathCategory.MIGRATION_DOCUMENTATION
    if root in SKILL_ROOTS:
        return PathCategory.MIGRATION_SKILL_METADATA
    if root in WORKFLOW_ROOTS:
        return PathCategory.MIGRATION_WORKFLOW_METADATA
    if root in CONFIGURATION_ROOTS or _looks_like_configuration(name, suffix):
        return PathCategory.MIGRATION_CONFIGURATION
    if root in SOURCE_ROOTS or suffix in SOURCE_SUFFIXES:
        return PathCategory.MIGRATION_SOURCE_CODE
    return PathCategory.UNKNOWN_REVIEW_REQUIRED


def _entry(
    path: Path,
    root: Path,
    destination_root: Path,
    *,
    is_directory: bool,
    is_reparse: bool,
) -> PlanEntry:
    relative = path.relative_to(root)
    relative_text = relative.as_posix()
    category = classify_path(relative, is_directory=is_directory, is_reparse=is_reparse)
    policy = CATEGORY_POLICIES[category]
    metadata = path.stat(follow_symlinks=False)
    suffix = path.suffix.casefold() if not is_directory else "directory"
    file_type = suffix or "no_extension"
    target = destination_root / "data" / relative
    exclusion_reason = (
        policy.reason if policy.backup_decision != "content_backup" else None
    )
    return PlanEntry(
        path=relative_text,
        entry_type="reparse_point"
        if is_reparse
        else "directory"
        if is_directory
        else "file",
        file_type=file_type,
        size=None if is_directory else metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        category=category,
        backup_decision=policy.backup_decision,
        content_access_allowed=policy.content_access_allowed,
        hashing_allowed=policy.hashing_allowed,
        migration_allowed=policy.migration_allowed,
        exclusion_reason=exclusion_reason,
        relative_length=len(relative_text),
        planned_target_length=len(os.fspath(target)),
        longest_segment=max(len(part) for part in relative.parts),
        depth=len(relative.parts),
        reparse_point=is_reparse,
    )


def scan_metadata(source: Path, destination_root: Path) -> tuple[PlanEntry, ...]:
    entries: list[PlanEntry] = []
    pending = [source]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as iterator:
                children = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as error:
            relative = current.relative_to(source).as_posix() or "."
            raise PolicyPlanningError(
                f"cannot enumerate metadata for relative path: {relative}"
            ) from error
        for child in children:
            path = Path(child.path)
            try:
                reparse = _is_reparse(path)
                is_directory = child.is_dir(follow_symlinks=False)
                entries.append(
                    _entry(
                        path,
                        source,
                        destination_root,
                        is_directory=is_directory,
                        is_reparse=reparse,
                    )
                )
                if is_directory and not reparse:
                    pending.append(path)
            except OSError as error:
                relative = path.relative_to(source).as_posix()
                raise PolicyPlanningError(
                    f"cannot inspect metadata for relative path: {relative}"
                ) from error
    return tuple(sorted(entries, key=lambda item: item.path.casefold()))


def _simulate(
    entries: tuple[PlanEntry, ...], *, source_destination_disjoint: bool
) -> SimulationResult:
    unknown = tuple(
        entry
        for entry in entries
        if entry.category is PathCategory.UNKNOWN_REVIEW_REQUIRED
    )
    unknown_long = tuple(
        entry
        for entry in unknown
        if entry.planned_target_length > WINDOWS_SAFE_TARGET_PATH_LENGTH
    )
    migration_long = tuple(
        entry
        for entry in entries
        if entry.category in CONTENT_CATEGORIES
        and entry.planned_target_length > WINDOWS_SAFE_TARGET_PATH_LENGTH
    )
    prohibited_content = tuple(
        entry
        for entry in entries
        if entry.backup_decision == "content_backup"
        and entry.category not in CONTENT_CATEGORIES
    )
    violations: list[str] = []
    if not source_destination_disjoint:
        violations.append("source_and_destination_not_disjoint")
    if unknown:
        violations.append(f"unknown_review_required:{len(unknown)}")
    if migration_long:
        violations.append(f"migration_long_paths:{len(migration_long)}")
    if prohibited_content:
        violations.append(f"prohibited_content_backup:{len(prohibited_content)}")
    return SimulationResult(
        passed=not violations,
        source_destination_disjoint=source_destination_disjoint,
        unknown_count=len(unknown),
        unknown_long_path_count=len(unknown_long),
        migration_long_path_count=len(migration_long),
        prohibited_content_backup_count=len(prohibited_content),
        reparse_points_not_followed=sum(entry.reparse_point for entry in entries),
        violations=tuple(violations),
    )


def create_backup_plan(
    source: Path,
    destination_root: Path,
    *,
    source_label: str,
    destination_label: str,
) -> BackupPlan:
    """Inspect all path metadata twice and simulate a backup without copying."""

    source = source.absolute()
    destination_root = destination_root.absolute()
    if not source.is_dir():
        raise PolicyPlanningError("source must be an existing directory")
    if _is_reparse(source):
        raise PolicyPlanningError("source root must not be a symlink or junction")
    disjoint = not (
        destination_root == source
        or source in destination_root.parents
        or destination_root in source.parents
    )
    first = scan_metadata(source, destination_root)
    second = scan_metadata(source, destination_root)
    if first != second:
        raise PolicyPlanningError("source metadata changed during policy planning")

    category_counts = Counter(entry.category.value for entry in first)
    category_bytes = Counter()
    extension_counts = Counter()
    for entry in first:
        if entry.size is not None:
            category_bytes[entry.category.value] += entry.size
            extension_counts[entry.file_type] += 1
    long_paths = tuple(
        entry
        for entry in first
        if entry.planned_target_length > WINDOWS_SAFE_TARGET_PATH_LENGTH
    )
    near_limit = tuple(
        entry
        for entry in first
        if WINDOWS_SAFE_TARGET_PATH_LENGTH - 20
        <= entry.planned_target_length
        <= WINDOWS_SAFE_TARGET_PATH_LENGTH
    )
    unusual = tuple(
        entry for entry in first if entry.longest_segment >= UNUSUAL_SEGMENT_LENGTH
    )
    unknown = tuple(
        entry
        for entry in first
        if entry.category is PathCategory.UNKNOWN_REVIEW_REQUIRED
    )
    migration_long = sum(entry.category in CONTENT_CATEGORIES for entry in long_paths)
    unknown_long = sum(
        entry.category is PathCategory.UNKNOWN_REVIEW_REQUIRED for entry in long_paths
    )
    safely_excluded_long = len(long_paths) - migration_long - unknown_long
    content_suffix_lengths = [
        len(os.fspath(Path("data") / Path(entry.path)))
        for entry in first
        if entry.category in CONTENT_CATEGORIES
    ]
    maximum_root = (
        WINDOWS_SAFE_TARGET_PATH_LENGTH - 1 - max(content_suffix_lengths, default=0)
    )
    top_level = tuple(
        entry.path
        for entry in first
        if entry.depth == 1 and entry.entry_type == "directory"
    )
    return BackupPlan(
        source_label=source_label,
        destination_label=destination_label,
        target_root_length=len(os.fspath(destination_root)),
        safe_target_limit=WINDOWS_SAFE_TARGET_PATH_LENGTH,
        source_stable=True,
        top_level=top_level,
        entries=first,
        category_counts=dict(sorted(category_counts.items())),
        category_bytes=dict(sorted(category_bytes.items())),
        extension_counts=dict(sorted(extension_counts.items())),
        long_paths=long_paths,
        safely_excluded_long_path_count=safely_excluded_long,
        migration_long_path_count=migration_long,
        unknown_long_path_count=unknown_long,
        near_limit_paths=near_limit,
        unusual_segment_paths=unusual,
        unknown_paths=unknown,
        maximum_planned_target_length=max(
            (entry.planned_target_length for entry in first), default=0
        ),
        maximum_safe_content_target_root_length=maximum_root,
        simulation=_simulate(first, source_destination_disjoint=disjoint),
    )


def plan_to_dict(plan: BackupPlan) -> dict[str, Any]:
    payload = asdict(plan)
    payload["category_policies"] = {
        category.value: asdict(policy) for category, policy in CATEGORY_POLICIES.items()
    }
    return payload


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("`", "\\`")


def _entry_table(entries: tuple[PlanEntry, ...]) -> list[str]:
    lines = [
        "| Relativer Pfad | Typ | Kategorie | Zielpfad | Relativ | Segment | "
        "Tiefe | Entscheidung |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for entry in entries:
        lines.append(
            f"| `{_md(entry.path)}` | {entry.entry_type} | `{entry.category.value}` "
            f"| {entry.planned_target_length} | {entry.relative_length} "
            f"| {entry.longest_segment} | {entry.depth} | `{entry.backup_decision}` |"
        )
    return lines


def render_policy_report(
    plan: BackupPlan,
    *,
    legacy_head: str,
    legacy_status_count: int,
    vault_source_manifest_sha256: str,
    vault_backup_tree_sha256: str,
) -> str:
    """Render the complete committed policy report without private absolute paths."""

    lines = [
        "# Phase 8A: vollständige Backup-Policy-Planung",
        "",
        "Stand: 31. Juli 2026",
        "",
        "## Entscheidung und Grenzen",
        "",
        "Dieser Bericht dokumentiert ausschließlich den metadata-only Planungsmodus. "
        "Es wurde kein dritter Legacy-Backupversuch gestartet, kein Legacy-Backupziel "
        "erzeugt, kein Vault-Dry-Run begonnen und keine Phase-8B-Arbeit ausgeführt.",
        "",
        f"- Quellenlabel: `{plan.source_label}`",
        f"- Legacy-HEAD: `{legacy_head}`",
        f"- Legacy-Git-Status-Einträge: {legacy_status_count}",
        f"- geplantes Ziellabel: `{plan.destination_label}`",
        f"- erfasste Pfade: {len(plan.entries)}",
        "- Quelle über zwei Metadatenscans stabil: "
        f"`{str(plan.source_stable).lower()}`",
        "- Quelldateiinhalte geöffnet oder gehasht: `0`",
        "- Copy- oder Netzwerkaufrufe: `0`",
        "",
        "## Vollständige Top-Level-Inventur",
        "",
        "| Relativer Pfad | Typ | Kategorie | Entscheidung |",
        "| --- | --- | --- | --- |",
    ]
    for entry in (item for item in plan.entries if item.depth == 1):
        lines.append(
            f"| `{_md(entry.path)}` | {entry.entry_type} | `{entry.category.value}` "
            f"| `{entry.backup_decision}` |"
        )

    lines.extend(
        [
            "",
            "## Klassifikationsmodell",
            "",
            "Jeder erfasste Pfad besitzt genau eine der folgenden Kategorien. "
            "Die Policy wird vor jeder Content-Entscheidung angewendet.",
            "",
            "| Kategorie | Definition | Root-/Kontextregel | Backup | Lesen | "
            "Hashen | Migration | Begründung |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for category, policy in CATEGORY_POLICIES.items():
        lines.append(
            f"| `{category.value}` | {_md(policy.definition)} | "
            f"{_md(policy.root_context_rules)} | `{policy.backup_decision}` | "
            f"{str(policy.content_access_allowed).lower()} | "
            f"{str(policy.hashing_allowed).lower()} | "
            f"{str(policy.migration_allowed).lower()} | {_md(policy.reason)} |"
        )

    lines.extend(
        [
            "",
            "### Ergebnis nach Kategorie",
            "",
            "| Kategorie | Pfade | Dateibytes |",
            "| --- | ---: | ---: |",
        ]
    )
    for category in PathCategory:
        lines.append(
            f"| `{category.value}` | {plan.category_counts.get(category.value, 0)} "
            f"| {plan.category_bytes.get(category.value, 0)} |"
        )

    lines.extend(
        [
            "",
            "## Root-basierte technische Policy",
            "",
            "Positive Content-Roots sind `backend`, `desktop`, `frontend`, `scripts`, "
            "`src`, `training`, `tests`, `test`, `evals`, `docs`, `config`, `skills`, "
            "`automations` und `workflows`. In `src`, `docs`, `test` und `tests` "
            "führt ein Name wie `cache`, `*-cache` oder `*_cache` allein niemals zum "
            "Ausschluss.",
            "",
            "Technische beziehungsweise Runtime-Kontexte sind `state`, `runtime`, "
            "`models`, `model-data`, `generated`, `generated-data`, `artifacts` und "
            "`var`. Nur innerhalb dieser Kontexte gelten `.cache`, `cache`, `caches`, "
            "`review-cache`, `*-cache`, `*_cache`, Hugging-Face-Downloadstrukturen "
            "und Piper-Caches als `technical_cache_excluded`.",
            "",
            "Build-/Dependency-Roots wie `.git`, `.venv`, `node_modules`, `build`, "
            "`dist` und `target` sind `build_artifact_excluded`. Credential-, "
            "Session- und Browserprofile haben unabhängig vom Root Vorrang und sind "
            "prohibited. Reparse Points werden als `unknown_review_required` erfasst "
            "und niemals verfolgt.",
            "",
            "## Content-Backup und metadata-only Runtime-Inventar",
            "",
            "### A. Migrationsrelevanter Content-Backup",
            "",
            "Vorgesehen sind ausschließlich die sechs `migration_*`-Kategorien. "
            "Skill- und Workflow-Dateien bleiben untrusted metadata und dürfen durch "
            "einen Backup weder registriert noch aktiviert werden.",
            "",
            "### B. Metadata-only Runtime-Inventar",
            "",
            "`state` und `runtime` werden nicht als normale Projektdateien behandelt. "
            "Das Inventar enthält nur relative Pfade, Kategorie, Größe, Erweiterung "
            "und Struktur. Inhalte, Hashes, Logs, Tooloutputs, Sessions, Browserdaten "
            "und Credentials sind ausgeschlossen.",
            "",
            "**Empfehlung:** Der gesamte Root `state/models` bleibt standardmäßig "
            "`model_artifact_metadata_only`. Selbst kleine JSON-/YAML-/TOML-Dateien "
            "werden nicht still übernommen. Eine spätere Allowlist für einzelne "
            "Modellkonfigurationen benötigt eine separate Nutzerentscheidung.",
            "",
            "### Runtime-/Modellstruktur auf Ebene 2",
            "",
            "| Pfad | Kategorie | Entscheidung |",
            "| --- | --- | --- |",
        ]
    )
    runtime_roots = tuple(
        entry
        for entry in plan.entries
        if entry.entry_type == "directory"
        and entry.depth == 2
        and entry.path.split("/", 1)[0].casefold() in RUNTIME_ROOTS
    )
    for entry in runtime_roots:
        lines.append(
            f"| `{_md(entry.path)}` | `{entry.category.value}` | "
            f"`{entry.backup_decision}` |"
        )

    runtime_categories = {
        PathCategory.RUNTIME_STATE_METADATA_ONLY,
        PathCategory.MODEL_ARTIFACT_METADATA_ONLY,
        PathCategory.TECHNICAL_CACHE_EXCLUDED,
        PathCategory.TEMPORARY_EXCLUDED,
        PathCategory.CREDENTIAL_OR_SESSION_PROHIBITED,
        PathCategory.BROWSER_RUNTIME_PROHIBITED,
    }
    extension_counts = Counter(
        entry.file_type
        for entry in plan.entries
        if entry.entry_type == "file" and entry.category in runtime_categories
    )
    lines.extend(
        [
            "",
            "### Erweiterungen im Runtime-/Modell-Metadateninventar",
            "",
            "| Erweiterung/Typ | Anzahl |",
            "| --- | ---: |",
        ]
    )
    for extension, count in sorted(
        extension_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"| `{_md(extension)}` | {count} |")

    lines.extend(
        [
            "",
            "## Langpfadanalyse",
            "",
            f"- Sicheres Windows-Ziellimit: {plan.safe_target_limit}",
            f"- Zielroot-Länge der bestehenden Variante: {plan.target_root_length}",
            f"- Pfade oberhalb des Limits: {len(plan.long_paths)}",
            "- davon sicher ausgeschlossen/metadata-only: "
            f"{plan.safely_excluded_long_path_count}",
            f"- davon migrationsrelevant: {plan.migration_long_path_count}",
            f"- davon unbekannt: {plan.unknown_long_path_count}",
            f"- maximal geplante Zielpfadlänge: {plan.maximum_planned_target_length}",
            f"- Pfade bis 20 Zeichen unter dem Limit: {len(plan.near_limit_paths)}",
            f"- Pfade mit Segmenten ab {UNUSUAL_SEGMENT_LENGTH} Zeichen: "
            f"{len(plan.unusual_segment_paths)}",
            f"- maximal zulässige Content-Zielroot-Länge: "
            f"{plan.maximum_safe_content_target_root_length}",
            "- kürzester praktisch geplanter Staging-Root: `C:\\j8` (5 Zeichen; "
            "nur Strategie, nicht erzeugt)",
            "",
            "### Alle Pfade oberhalb des Sicherheitslimits",
            "",
        ]
    )
    lines.extend(_entry_table(plan.long_paths))
    lines.extend(
        [
            "",
            "### Alle Pfade bis 20 Zeichen unter dem Limit",
            "",
        ]
    )
    lines.extend(_entry_table(plan.near_limit_paths))
    lines.extend(
        [
            "",
            "### Pfade mit ungewöhnlich langen Segmenten",
            "",
        ]
    )
    lines.extend(_entry_table(plan.unusual_segment_paths))
    lines.extend(["", "### Unbekannte Pfade", ""])
    if plan.unknown_paths:
        lines.extend(_entry_table(plan.unknown_paths))
    else:
        lines.append("Keine. `unknown_review_required = 0`.")

    lines.extend(
        [
            "",
            "## Planender Vergleich der Zielstrategien",
            "",
            "| Variante | Zuverlässigkeit | Restore | Windows | Risiko | "
            "Portabilität | Codeänderung | Urteil |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
            "| Langes externes Verzeichnisziel | Mittel | Direkter Tree-Restore | "
            "Langpfade bleiben relevant | Teilkopie muss atomar verhindert werden | "
            "Hoch | Policy-Filter und Preflight | Nicht bevorzugt |",
            "| Kurzes externes Staging-Ziel | Hoch für Content | Direkter "
            "Tree-Restore | Beste Pfadreserve | Zusätzlicher sicherer Staging-Root | "
            "Mittel | Root-Allowlist und Cleanup | Geeignet für Restore-Probe |",
            "| Archivcontainer plus SHA-256-Manifest | Hoch | Extraktion plus "
            "Manifestprüfung | Keine langen physischen Backup-Unterbäume | Archiv "
            "muss atomar und traversal-sicher sein | Hoch | Sicherer "
            "Archivwriter/-reader | **Empfohlen** |",
            "| Windows-Long-Path-Präfix | Technisch hoch | Windows-spezifisch | "
            "Abhängig von APIs/Policy | Kann fachlich falsche Cachekopien "
            "kaschieren | Niedrig | Durchgehende Extended-Path-Unterstützung | "
            "Nur interne Metadatenanalyse |",
            "",
            "Empfehlung ist ein atomar erzeugter Archivcontainer mit SHA-256-Manifest "
            "für den migrationsrelevanten Content. Eine Restore-Probe darf ein kurzes, "
            "isoliertes Staging-Ziel verwenden. Long-Path-Präfixe sollen keine Cache-, "
            "Modell- oder Runtime-Daten in den Content-Backup ziehen.",
            "",
            "## Policy-Simulation",
            "",
            f"- Ergebnis: `{'PASS' if plan.simulation.passed else 'FAIL'}`",
            "- Source/Destination disjunkt: "
            f"`{str(plan.simulation.source_destination_disjoint).lower()}`",
            f"- unbekannte Pfade: {plan.simulation.unknown_count}",
            f"- unbekannte Langpfade: {plan.simulation.unknown_long_path_count}",
            "- migrationsrelevante Langpfade: "
            f"{plan.simulation.migration_long_path_count}",
            f"- technische/sensitive Pfade im Content-Backup: "
            f"{plan.simulation.prohibited_content_backup_count}",
            "- nicht verfolgte Reparse Points: "
            f"{plan.simulation.reparse_points_not_followed}",
            f"- Verletzungen: `{', '.join(plan.simulation.violations) or 'none'}`",
            "",
            "Der Planungsmodus erzeugte kein Backupziel. Die vollständige externe "
            "Planungsdatei enthält für jeden Pfad genau eine Kategorie, Größe, Typ, "
            "Zielpfadlänge und Entscheidung; sie enthält keine Dateiinhalte oder "
            "Hashes.",
            "",
            "## Eindeutige Vault-Hashbezeichnungen",
            "",
            f"- `vault_source_manifest_sha256`: `{vault_source_manifest_sha256}`",
            f"- `vault_backup_tree_sha256`: `{vault_backup_tree_sha256}`",
            "",
            "Der erste Wert bindet das verifizierte Dateimanifest der Vault-Quelle. "
            "Der zweite Wert bindet den vollständigen bestehenden Backupbaum "
            "einschließlich seiner Manifestdateien. Die Werte haben unterschiedliche "
            "Bedeutung und wurden nicht gleichgesetzt oder überschrieben.",
            "",
            "## Notwendige Nutzerentscheidungen",
            "",
            "Vor genau einem späteren finalen Legacy-Backupversuch sind ausdrücklich "
            "zu bestätigen:",
            "",
            "1. `state/models` bleibt vollständig metadata-only; eine spätere "
            "Konfigurations-Allowlist ist ein eigener Review.",
            "2. Runtime-Caches einschließlich `.cache`, Hugging-Face-Downloads und "
            "Piper-Caches werden nur metadata-only inventarisiert und nicht kopiert.",
            "3. Der Content-Backup wird als atomarer Archivcontainer mit "
            "SHA-256-Manifest geplant; ein kurzes Staging-Ziel dient ausschließlich "
            "der Restore-Probe.",
            "4. Skills und Workflows bleiben untrusted metadata und werden nicht "
            "registriert oder aktiviert.",
            "",
            "## Aussage zu einem finalen Versuch",
            "",
            (
                "Die Policy-Simulation ist **bestanden**: Es existiert kein "
                "unbekannter Pfad, kein migrationsrelevanter Langpfad und kein "
                "technischer oder "
                "sensitiver Content-Leak. Genau ein finaler Legacy-Backupversuch wäre "
                "nach ausdrücklicher Bestätigung der vier Entscheidungen technisch "
                "sicher planbar. Dieser Auftrag erteilt diese Freigabe nicht."
                if plan.simulation.passed
                else "Die Policy-Simulation ist **nicht bestanden**. Ein finaler "
                "Legacy-Backupversuch ist nicht sicher freigabefähig."
            ),
            "",
            "Phase 8A bleibt gestoppt. Phase 8B, Migration, Cutover und Vault-Writes "
            "wurden nicht begonnen.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--destination-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--legacy-head", default="not-provided")
    parser.add_argument("--legacy-status-count", type=int, default=-1)
    parser.add_argument("--vault-source-manifest-sha256", default="not-provided")
    parser.add_argument("--vault-backup-tree-sha256", default="not-provided")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    plan = create_backup_plan(
        args.source,
        args.destination_root,
        source_label=args.source_label,
        destination_label=args.destination_label,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan_to_dict(plan), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    if args.report_output is not None:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(
            render_policy_report(
                plan,
                legacy_head=args.legacy_head,
                legacy_status_count=args.legacy_status_count,
                vault_source_manifest_sha256=args.vault_source_manifest_sha256,
                vault_backup_tree_sha256=args.vault_backup_tree_sha256,
            ),
            encoding="utf-8",
            newline="\n",
        )
    print(
        json.dumps(
            {
                "entry_count": len(plan.entries),
                "long_path_count": len(plan.long_paths),
                "maximum_planned_target_length": plan.maximum_planned_target_length,
                "simulation_passed": plan.simulation.passed,
                "unknown_count": len(plan.unknown_paths),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
