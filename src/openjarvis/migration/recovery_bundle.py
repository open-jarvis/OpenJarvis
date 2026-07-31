"""Build an atomic, relative-path-only Phase 8A recovery evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Iterable

from openjarvis.migration.archive_backup import verify_content_archive
from openjarvis.migration.backup import load_manifest, verify_manifest


class RecoveryBundleError(RuntimeError):
    """Raised when recovery evidence cannot be verified and bundled atomically."""


REQUIRED_EXTERNAL_FILES = (
    "backup-policy-plan.json",
    "backup-policy-plan-v2.json",
    "legacy-backup-failure.txt",
    "legacy-backup-retry-failure.txt",
    "legacy-backup-proof.json",
    "legacy-content-backup.zip",
    "legacy-function-inventory-v2.json",
    "legacy-runtime-metadata.json",
    "runtime-conversion-dry-run.json",
    "vault-compatibility-diagnostic-v2.json",
    "vault-pilot-dry-run.json",
)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _tree_fingerprint(root: Path) -> dict[str, Any]:
    rows: list[bytes] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise RecoveryBundleError("recovery tree contains an unsafe path")
        size = path.stat().st_size
        rows.append(
            _canonical_json(
                {"path": relative, "sha256": _hash_file(path), "size": size}
            )
        )
        file_count += 1
        total_bytes += size
    return {
        "file_count": file_count,
        "sha256": hashlib.sha256(b"".join(rows)).hexdigest(),
        "total_bytes": total_bytes,
    }


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", os.fspath(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return completed.stdout.strip()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RecoveryBundleError(f"expected JSON object: {path.name}")
    return value


def _write(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _restore_instructions() -> str:
    return """# Phase 8A recovery and restore evidence

This bundle is evidence and a recovery map; it never authorizes a cutover.
All paths in the bundle and artifact manifest are relative to the bundle's
parent Phase-8A output directory.

## Legacy content archive

1. Verify `../legacy-content-backup.zip` against the SHA-256 in `summary.json`.
2. Run `verify_content_archive()` before every restore.
3. Restore only into a new, empty, short staging directory. Never extract over
   the legacy source, this repository, or a production workspace.
4. Accept only `content/*` members listed by the internal canonical manifest.
   Reject absolute paths, traversal, drive prefixes, ADS markers, links,
   encrypted members, missing files, extra files, size drift, or hash drift.
5. Keep skills and workflows quarantined. Restore is not registration,
   promotion, activation, or execution.

## Vault backup

1. Verify `../vault-backup/manifests/source-before.jsonl` and `summary.json`.
2. Verify every file under `../vault-backup/data` against that manifest.
3. Restore only into a new empty directory and compare all relative paths,
   sizes, mtimes, and SHA-256 values.
4. Do not replace or write the real Vault without a separate user-approved
   migration and cutover plan.
5. The current compatibility blocker is recorded in `summary.json`: IDs and
   schema versions require an explicit mapping decision.

## Failure rule

Any mismatch stops recovery. Do not repair manifests, infer exclusion rules,
reuse credentials, or accept a partial restore as successful.
"""


def create_recovery_bundle(
    output_root: Path,
    target: Path,
    repo_root: Path,
    documentation: Iterable[Path],
    *,
    vault_backup_tree_sha256: str,
) -> Path:
    """Verify Phase 8A artifacts and publish one atomic evidence directory."""

    output_root = output_root.absolute()
    target = target.absolute()
    repo_root = repo_root.absolute()
    if not output_root.is_dir() or not repo_root.is_dir():
        raise RecoveryBundleError("output and repository roots must exist")
    if target.exists():
        raise RecoveryBundleError("recovery bundle target must not already exist")
    if target.parent != output_root:
        raise RecoveryBundleError("recovery bundle must be inside the Phase 8A root")
    required = {name: output_root / name for name in REQUIRED_EXTERNAL_FILES}
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise RecoveryBundleError(f"required recovery artifacts are missing: {missing}")

    archive_manifest, archive_manifest_sha256 = verify_content_archive(
        required["legacy-content-backup.zip"]
    )
    proof = _json(required["legacy-backup-proof.json"])
    if proof.get("archive_sha256") != _hash_file(required["legacy-content-backup.zip"]):
        raise RecoveryBundleError("legacy archive hash differs from its proof")
    if proof.get("content_manifest_sha256") != archive_manifest_sha256:
        raise RecoveryBundleError("legacy content manifest differs from its proof")

    vault_backup = output_root / "vault-backup"
    vault_data = vault_backup / "data"
    vault_manifests = vault_backup / "manifests"
    vault_expected = load_manifest(vault_manifests / "source-before.jsonl")
    if not verify_manifest(vault_data, vault_expected):
        raise RecoveryBundleError("vault backup differs from its source manifest")
    vault_summary = _json(vault_manifests / "summary.json")
    vault_tree = _tree_fingerprint(vault_backup)
    vault_data_tree = _tree_fingerprint(vault_data)

    legacy_inventory = _json(required["legacy-function-inventory-v2.json"])
    runtime_dry_run = _json(required["runtime-conversion-dry-run.json"])
    vault_pilot = _json(required["vault-pilot-dry-run.json"])
    vault_compatibility = _json(required["vault-compatibility-diagnostic-v2.json"])
    if not vault_pilot.get("pilot_removed") or not vault_pilot.get("backup_unchanged"):
        raise RecoveryBundleError("vault pilot cleanup or stability proof is missing")
    if not vault_compatibility.get("backup_unchanged"):
        raise RecoveryBundleError("vault compatibility scan changed the backup")

    temporary = output_root / f".recovery-bundle-{uuid.uuid4().hex}.tmp"
    temporary.mkdir()
    try:
        documents_root = temporary / "documentation"
        documents_root.mkdir()
        for source in documentation:
            source = source.absolute()
            if not source.is_file() or repo_root not in source.parents:
                raise RecoveryBundleError("documentation must be a repository file")
            _write(documents_root / source.name, source.read_bytes())

        artifacts = []
        for name, path in sorted(required.items()):
            artifacts.append(
                {
                    "path": f"../{name}",
                    "sha256": _hash_file(path),
                    "size": path.stat().st_size,
                    "type": "file",
                }
            )
        artifacts.extend(
            [
                {
                    "established_sha256": vault_backup_tree_sha256,
                    "fingerprint_sha256": vault_tree["sha256"],
                    "file_count": vault_tree["file_count"],
                    "path": "../vault-backup",
                    "total_bytes": vault_tree["total_bytes"],
                    "type": "directory",
                },
                {
                    "fingerprint_sha256": vault_data_tree["sha256"],
                    "file_count": vault_data_tree["file_count"],
                    "path": "../vault-backup/data",
                    "total_bytes": vault_data_tree["total_bytes"],
                    "type": "directory",
                },
            ]
        )

        summary = {
            "legacy": {
                "archive_sha256": proof["archive_sha256"],
                "content_file_count": len(archive_manifest),
                "content_manifest_sha256": archive_manifest_sha256,
                "content_total_bytes": proof["content_total_bytes"],
                "git_head": proof["git_head_after"],
                "git_status_count": proof["git_status_count"],
                "python_classes": legacy_inventory["python_class_count"],
                "python_functions": legacy_inventory["python_function_count"],
                "python_modules": legacy_inventory["python_module_count"],
                "routes": legacy_inventory["route_count"],
                "source_stable": proof["source_stable"],
            },
            "repository": {
                "branch": _git(repo_root, "branch", "--show-current"),
                "head": _git(repo_root, "rev-parse", "HEAD"),
                "status_clean": not _git(repo_root, "status", "--porcelain"),
                "upstream_fetch": "official OpenJarvis repository",
                "upstream_push": "disabled",
            },
            "runtime": runtime_dry_run,
            "scope": {
                "codex_live_turns": False,
                "external_models": False,
                "legacy_source_written": False,
                "phase_8b_started": False,
                "push_performed": False,
                "real_vault_accessed_by_pilot": False,
                "real_vault_written": False,
                "skills_or_workflows_activated": False,
            },
            "vault": {
                "backup_file_count": vault_summary["file_count"],
                "backup_total_bytes": vault_summary["total_bytes"],
                "id_state_counts": vault_compatibility["id_state_counts"],
                "markdown_files": vault_compatibility["markdown_files"],
                "pilot_indexed": vault_pilot["index"]["indexed"],
                "pilot_removed": vault_pilot["pilot_removed"],
                "schema_version_counts": vault_compatibility["schema_version_counts"],
                "vault_backup_tree_sha256": vault_backup_tree_sha256,
                "vault_source_manifest_sha256": vault_summary["manifest_sha256"],
            },
        }
        _write(
            temporary / "artifact-manifest.json",
            json.dumps(artifacts, indent=2, ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n",
        )
        _write(
            temporary / "summary.json",
            json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n",
        )
        _write(temporary / "RESTORE.md", _restore_instructions().encode("utf-8"))

        internal = []
        for path in sorted(item for item in temporary.rglob("*") if item.is_file()):
            internal.append(
                {
                    "path": path.relative_to(temporary).as_posix(),
                    "sha256": _hash_file(path),
                    "size": path.stat().st_size,
                }
            )
        _write(
            temporary / "bundle-index.json",
            json.dumps(internal, indent=2, ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
            + b"\n",
        )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--documentation", type=Path, action="append", required=True)
    parser.add_argument("--vault-backup-tree-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    target = create_recovery_bundle(
        args.output_root,
        args.target,
        args.repo_root,
        args.documentation,
        vault_backup_tree_sha256=args.vault_backup_tree_sha256,
    )
    print(json.dumps({"recovery_bundle": target.name}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
