"""Read-only Phase 8A inventories and isolated migration dry-runs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from openjarvis.memory.migration import analyze_vault_migration
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.migration.archive_backup import (
    CONTENT_PREFIX,
    ContentManifestEntry,
    verify_content_archive,
)
from openjarvis.migration.backup import load_manifest, verify_manifest


class AssessmentError(RuntimeError):
    """Raised when a Phase 8A assessment cannot stay read-only and bounded."""


_TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".css",
        ".html",
        ".in",
        ".ini",
        ".js",
        ".json",
        ".jsonl",
        ".lock",
        ".md",
        ".ps1",
        ".py",
        ".rst",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_FEATURE_PREFIXES = {
    "api_and_conversation": (
        "backend/jarvis_backend/app.py",
        "backend/jarvis_backend/conversation.py",
    ),
    "automations": ("backend/jarvis_backend/automations/",),
    "controlled_learning": (
        "backend/jarvis_backend/demonstrations/",
        "backend/jarvis_backend/improvement/",
        "backend/jarvis_backend/internet_learning/",
        "backend/jarvis_backend/learning/",
    ),
    "documents": ("backend/jarvis_backend/documents/",),
    "memory": ("backend/jarvis_backend/memory/",),
    "model_routing_and_providers": (
        "backend/jarvis_backend/providers/",
        "backend/jarvis_backend/routing/",
    ),
    "security_audit_and_budgets": (
        "backend/jarvis_backend/audit.py",
        "backend/jarvis_backend/budgets.py",
        "backend/jarvis_backend/privacy/",
        "backend/jarvis_backend/security/",
        "backend/jarvis_backend/usage.py",
    ),
    "skills": ("backend/jarvis_backend/skills/", "skills/"),
    "speech_vision_and_video": (
        "backend/jarvis_backend/speech/",
        "backend/jarvis_backend/video/",
        "backend/jarvis_backend/vision/",
    ),
    "tasks": ("backend/jarvis_backend/tasks/",),
    "tiktok": ("backend/jarvis_backend/tiktok/", "training/tiktok/"),
    "tools_and_browser": ("backend/jarvis_backend/tools/",),
    "training": (
        "backend/jarvis_backend/training/",
        "training/assistant/",
        "training/company/",
    ),
    "website_staging": ("backend/jarvis_backend/website/",),
}


def _safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if (
        not value
        or value == "."
        or "\\" in value
        or relative.as_posix() != value
        or relative.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in relative.parts)
    ):
        raise AssessmentError("assessment encountered an unsafe relative path")
    return relative


def _read_member(archive: ZipFile, entry: ContentManifestEntry) -> bytes:
    _safe_relative(entry.path)
    if entry.size > 8 * 1024 * 1024:
        raise AssessmentError("static-analysis input exceeds the bounded size limit")
    with archive.open(f"{CONTENT_PREFIX}{entry.path}", "r") as stream:
        payload = stream.read(8 * 1024 * 1024 + 1)
    if len(payload) != entry.size or len(payload) > 8 * 1024 * 1024:
        raise AssessmentError("static-analysis member size changed")
    if hashlib.sha256(payload).hexdigest() != entry.sha256:
        raise AssessmentError("static-analysis member differs from the manifest")
    return payload


def _python_structure(path: str, payload: bytes) -> dict[str, Any]:
    try:
        source = payload.decode("utf-8")
        tree = ast.parse(source, filename=path)
    except (UnicodeDecodeError, SyntaxError) as error:
        return {"path": path, "parse_error": type(error).__name__}
    functions: list[str] = []
    classes: list[str] = []
    routes: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                method = decorator.func.attr.casefold()
                if method not in {"delete", "get", "patch", "post", "put"}:
                    continue
                if not decorator.args or not isinstance(
                    decorator.args[0], ast.Constant
                ):
                    continue
                route = decorator.args[0].value
                if isinstance(route, str):
                    routes.append(
                        {"function": node.name, "method": method.upper(), "path": route}
                    )
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
    return {
        "classes": sorted(classes),
        "functions": sorted(functions),
        "path": path,
        "routes": sorted(routes, key=lambda item: (item["path"], item["method"])),
    }


def _configuration_keys(path: str, payload: bytes) -> list[str]:
    if not path.endswith(".json") or not path.startswith("config/"):
        return []
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        return sorted(str(key) for key in value)
    return []


def assess_legacy_archive(archive_path: Path) -> dict[str, Any]:
    """Build a static function inventory from a fully verified content archive."""

    manifest, manifest_sha256 = verify_content_archive(archive_path)
    by_top_level: Counter[str] = Counter()
    by_suffix: Counter[str] = Counter()
    python_modules: list[dict[str, Any]] = []
    configuration_keys: dict[str, list[str]] = {}
    names = tuple(entry.path for entry in manifest)
    with ZipFile(archive_path, "r") as archive:
        for entry in manifest:
            relative = _safe_relative(entry.path)
            by_top_level[relative.parts[0]] += 1
            by_suffix[relative.suffix.casefold() or "no_extension"] += 1
            if relative.suffix.casefold() not in _TEXT_SUFFIXES:
                continue
            payload = _read_member(archive, entry)
            if relative.suffix.casefold() == ".py":
                python_modules.append(_python_structure(entry.path, payload))
            keys = _configuration_keys(entry.path, payload)
            if keys:
                configuration_keys[entry.path] = keys

    feature_counts = {
        feature: sum(
            any(path == prefix or path.startswith(prefix) for prefix in prefixes)
            for path in names
        )
        for feature, prefixes in _FEATURE_PREFIXES.items()
    }
    routes = [route for module in python_modules for route in module.get("routes", [])]
    skill_paths = sorted(
        path for path in names if path.startswith("skills/") and path.endswith(".json")
    )
    workflow_paths = sorted(path for path in names if path.startswith("automations/"))
    return {
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "content_file_count": len(manifest),
        "content_manifest_sha256": manifest_sha256,
        "configuration_keys": configuration_keys,
        "feature_file_counts": feature_counts,
        "file_counts_by_suffix": dict(sorted(by_suffix.items())),
        "file_counts_by_top_level": dict(sorted(by_top_level.items())),
        "python_class_count": sum(
            len(item.get("classes", [])) for item in python_modules
        ),
        "python_function_count": sum(
            len(item.get("functions", [])) for item in python_modules
        ),
        "python_module_count": len(python_modules),
        "route_count": len(routes),
        "routes": sorted(routes, key=lambda item: (item["path"], item["method"])),
        "skill_definition_count": len(skill_paths),
        "skill_definitions": skill_paths,
        "skills_untrusted": True,
        "static_analysis_only": True,
        "workflow_metadata_count": len(workflow_paths),
        "workflow_metadata": workflow_paths,
        "workflows_untrusted": True,
    }


def assess_runtime_metadata(inventory_path: Path) -> dict[str, Any]:
    """Summarize runtime metadata without opening any represented source content."""

    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    if payload.get("content_accessed") is not False:
        raise AssessmentError("runtime inventory does not prove metadata-only access")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise AssessmentError("runtime inventory entries are invalid")
    categories: Counter[str] = Counter()
    entry_types: Counter[str] = Counter()
    total_known_bytes: Counter[str] = Counter()
    for entry in entries:
        path = str(entry.get("path", ""))
        _safe_relative(path)
        category = str(entry.get("category", ""))
        categories[category] += 1
        entry_types[str(entry.get("entry_type", "unknown"))] += 1
        size = entry.get("size")
        if isinstance(size, int) and size >= 0:
            total_known_bytes[category] += size
    actions = {
        "browser_runtime_prohibited": "never_migrate_reauthenticate_fresh",
        "credential_or_session_prohibited": "never_migrate_reauthenticate_fresh",
        "model_artifact_metadata_only": "do_not_copy_review_configuration_separately",
        "runtime_state_metadata_only": (
            "no_direct_import_use_schema_converter_only_after_review"
        ),
        "technical_cache_excluded": "discard_and_regenerate",
        "temporary_excluded": "discard",
    }
    return {
        "actions": actions,
        "category_counts": dict(sorted(categories.items())),
        "entry_count": len(entries),
        "entry_type_counts": dict(sorted(entry_types.items())),
        "known_bytes_by_category": dict(sorted(total_known_bytes.items())),
        "metadata_only": True,
        "prohibited_roots_recursive": payload.get("prohibited_roots_recursive"),
        "relative_paths_only": payload.get("relative_paths_only"),
    }


def _is_reparse(path: Path) -> bool:
    metadata = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _assert_safe_tree(root: Path) -> None:
    if not root.is_dir() or _is_reparse(root):
        raise AssessmentError("vault backup data root is not a safe directory")
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as iterator:
            for child in iterator:
                path = Path(child.path)
                if _is_reparse(path):
                    raise AssessmentError("vault backup contains a reparse point")
                if child.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif not child.is_file(follow_symlinks=False):
                    raise AssessmentError("vault backup contains a special file")


def _tree_fingerprint(root: Path) -> tuple[str, int, int]:
    rows: list[bytes] = []
    count = 0
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        _safe_relative(relative)
        payload = path.read_bytes()
        count += 1
        total_bytes += len(payload)
        rows.append(
            _canonical_json(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            )
        )
    return hashlib.sha256(b"".join(rows)).hexdigest(), count, total_bytes


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def run_vault_pilot(vault_backup: Path, workspace: Path) -> dict[str, Any]:
    """Run migration analysis and indexing only on an ephemeral backup copy."""

    vault_backup = vault_backup.absolute()
    workspace = workspace.absolute()
    data_root = vault_backup / "data"
    manifests_root = vault_backup / "manifests"
    _assert_safe_tree(data_root)
    expected = load_manifest(manifests_root / "source-before.jsonl")
    if not verify_manifest(data_root, expected):
        raise AssessmentError("vault backup data does not match its verified manifest")
    summary = json.loads((manifests_root / "summary.json").read_text(encoding="utf-8"))
    before_backup = _tree_fingerprint(data_root)

    workspace.mkdir(parents=True, exist_ok=True)
    pilot_root = Path(tempfile.mkdtemp(prefix="phase8a-vault-pilot-", dir=workspace))
    pilot_vault = pilot_root / "vault"
    try:
        shutil.copytree(data_root, pilot_vault, copy_function=shutil.copy2)
        pilot_before = _tree_fingerprint(pilot_vault)
        if pilot_before != before_backup:
            raise AssessmentError("vault pilot copy differs from the verified backup")

        migration = analyze_vault_migration(pilot_vault)
        index_path = pilot_root / "state" / "memory.sqlite3"
        with VaultIndex(
            pilot_vault,
            index_path,
            mode="read-only",
            embeddings_enabled=False,
        ) as index:
            index_report = index.rebuild()
            health = index.health()
            error_types = Counter(
                str(item["error_type"]) for item in index.list_errors(limit=10_000)
            )

        pilot_after = _tree_fingerprint(pilot_vault)
        after_backup = _tree_fingerprint(data_root)
        if pilot_after != pilot_before or after_backup != before_backup:
            raise AssessmentError("vault data changed during the isolated dry-run")
        return {
            "backup_file_count": before_backup[1],
            "backup_manifest_sha256": summary.get("manifest_sha256"),
            "backup_total_bytes": before_backup[2],
            "backup_tree_fingerprint_before": before_backup[0],
            "backup_tree_fingerprint_after": after_backup[0],
            "backup_unchanged": after_backup == before_backup,
            "dry_run": True,
            "embeddings_enabled": False,
            "finding_counts": dict(
                sorted(Counter(item.kind for item in migration.findings).items())
            ),
            "index": {
                "conflicts": index_report.conflicts,
                "duplicate_contents": index_report.duplicate_contents,
                "duplicate_ids": index_report.duplicate_ids,
                "error_types": dict(sorted(error_types.items())),
                "fts5_available": health.fts5_available,
                "indexed": index_report.indexed,
                "parser_errors": index_report.parser_errors,
                "scanned": index_report.scanned,
            },
            "migration": {
                "duplicate_ids": migration.duplicate_ids,
                "invalid_yaml": migration.invalid_yaml,
                "markdown_files": migration.markdown_files,
                "missing_ids": migration.missing_ids,
                "parallel_folder_note_counts": migration.parallel_folder_schemas,
                "planned_change_count": len(migration.planned_changes),
                "possible_conflicts": migration.possible_conflicts,
                "possible_duplicate_groups": migration.possible_duplicate_groups,
                "schema_counts": migration.schema_counts,
                "source_hashes_unchanged": migration.source_hashes_unchanged,
            },
            "pilot_file_count": pilot_before[1],
            "pilot_total_bytes": pilot_before[2],
            "pilot_tree_fingerprint_before": pilot_before[0],
            "pilot_tree_fingerprint_after": pilot_after[0],
            "pilot_unchanged": pilot_after == pilot_before,
            "real_vault_accessed": False,
            "restore_or_write_applied": False,
        }
    finally:
        shutil.rmtree(pilot_root, ignore_errors=False)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode(
                    "utf-8"
                )
            )
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-archive", type=Path, required=True)
    parser.add_argument("--runtime-inventory", type=Path, required=True)
    parser.add_argument("--vault-backup", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--legacy-output", type=Path, required=True)
    parser.add_argument("--runtime-output", type=Path, required=True)
    parser.add_argument("--vault-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    outputs = (args.legacy_output, args.runtime_output, args.vault_output)
    if any(path.exists() for path in outputs):
        raise AssessmentError("assessment outputs must not already exist")
    try:
        legacy = assess_legacy_archive(args.legacy_archive)
        runtime = assess_runtime_metadata(args.runtime_inventory)
        vault = run_vault_pilot(args.vault_backup, args.workspace)
        vault["pilot_removed"] = not any(args.workspace.glob("phase8a-vault-pilot-*"))
        _atomic_json(args.legacy_output, legacy)
        _atomic_json(args.runtime_output, runtime)
        _atomic_json(args.vault_output, vault)
    except Exception:
        for path in outputs:
            path.unlink(missing_ok=True)
        raise
    print(
        json.dumps(
            {
                "legacy_content_files": legacy["content_file_count"],
                "runtime_entries": runtime["entry_count"],
                "vault_indexed": vault["index"]["indexed"],
                "vault_markdown_files": vault["migration"]["markdown_files"],
                "vault_pilot_removed": vault["pilot_removed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
