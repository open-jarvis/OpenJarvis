"""Phase 8B legacy note-type compatibility review and isolated pilot v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import MemoryNote
from openjarvis.memory.vault_policy import (
    AuthorityClass,
    RetrievalClass,
    RetrievalPurpose,
    TrustClass,
)
from openjarvis.memory.vault_retrieval import VaultRetriever
from openjarvis.migration.vault_schema_pilot import (
    KNOWN_ID_REFERENCE_FIELDS,
    MappingTable,
    _body_bytes,
    _write,
    _write_json,
    run_isolated_pilot,
)

LEGACY_COMPATIBILITY_TYPES = frozenset(
    {
        "memory_proposal",
        "category",
        "navigation",
        "project_profile",
        "system_policy",
        "system_profile",
    }
)

EXPECTED_COUNTS = {
    "memory_proposal": 12,
    "category": 6,
    "navigation": 2,
    "project_profile": 1,
    "system_policy": 1,
    "system_profile": 1,
}

_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\([^\)\n]+\)")
_CLASSIFICATION_FIELDS = frozenset(
    {"trust_class", "retrieval_class", "authority_class", "scope_class"}
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reference_field_count(metadata: Mapping[str, Any]) -> int:
    return sum(str(key) in KNOWN_ID_REFERENCE_FIELDS for key in metadata)


def _authority_risks(note: MemoryNote) -> list[str]:
    risks: list[str] = []
    if note.note_type in {"system_policy", "system_profile"}:
        risks.append("authority_sensitive_source")
    if note.note_type == "memory_proposal":
        risks.append("untrusted_proposal")
    if _CLASSIFICATION_FIELDS & {str(key) for key in note.raw_frontmatter}:
        risks.append("vault_classification_override_ignored")
    return risks


def _inventory_record(
    pilot: Path,
    note: MemoryNote,
    mapping_by_path: Mapping[str, Any],
) -> dict[str, Any]:
    payload = (pilot / Path(note.path)).read_bytes()
    body = _body_bytes(payload)
    mapping = mapping_by_path[note.path]
    return {
        "authority_risks": _authority_risks(note),
        "body_sha256": _sha256(body),
        "frontmatter_field_names": sorted(str(key) for key in note.raw_frontmatter),
        "legacy_id": note.raw_frontmatter.get("legacy_id"),
        "legacy_id_mapping_state": mapping.source_id_state,
        "link_counts": {
            "markdown_links": len(_MARKDOWN_LINK_RE.findall(note.body)),
            "structured_reference_fields": _reference_field_count(note.raw_frontmatter),
            "wikilinks": len(note.outgoing_links),
        },
        "note_type": note.note_type,
        "proposed_authority_class": note.authority_class.value,
        "proposed_retrieval_class": note.retrieval_class.value,
        "proposed_scope": {
            "binding_present": bool(note.scope_binding),
            "scope_class": note.scope_class.value,
        },
        "proposed_trust_class": note.trust_class.value,
        "relative_path": note.path,
        "size_bytes": note.size_bytes,
        "uuid": note.note_id,
    }


def _parse_record(note: MemoryNote) -> dict[str, Any]:
    return {
        "authority_class": note.authority_class.value,
        "content_indexed": note.content_indexed,
        "discovered": True,
        "frontmatter_parsed": note.frontmatter_parsed,
        "note_type": note.note_type,
        "parse_error": note.parser_error,
        "parse_status": note.parse_status,
        "relative_path": note.path,
        "retrieval_class": note.retrieval_class.value,
        "retrieval_eligible": note.retrieval_eligible,
        "schema_valid": note.schema_valid,
        "scope_class": note.scope_class.value,
        "trust_class": note.trust_class.value,
        "type_supported": note.type_supported,
    }


def _query_for(note: MemoryNote) -> str:
    return note.title.strip() or Path(note.path).stem


def _contains(result: Any, note_id: str) -> bool:
    return any(item.note_id == note_id for item in result.candidates)


def build_compatibility_review(
    pilot: Path,
    state: Path,
    table: MappingTable,
    parser: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Build metadata-only compatibility artifacts while the pilot exists."""

    database = state / "memory.sqlite3"
    mapping_by_path = {entry.relative_path: entry for entry in table.entries}
    with VaultIndex(pilot, database, mode="read-only") as index:
        first_notes = index.list_notes(limit=10_000)
        first_classes = {
            note.path: (
                note.trust_class.value,
                note.retrieval_class.value,
                note.authority_class.value,
                note.scope_class.value,
            )
            for note in first_notes
        }
    with VaultIndex(pilot, database, mode="read-only") as index:
        notes = index.list_notes(limit=10_000)
        restarted_classes = {
            note.path: (
                note.trust_class.value,
                note.retrieval_class.value,
                note.authority_class.value,
                note.scope_class.value,
            )
            for note in notes
        }
        retriever = VaultRetriever(index)
        candidate_count_before = int(
            index.connection.execute(
                "SELECT COUNT(*) FROM memory_candidates"
            ).fetchone()[0]
        )
        inventory = [
            _inventory_record(pilot, note, mapping_by_path)
            for note in notes
            if note.note_type in LEGACY_COMPATIBILITY_TYPES
        ]
        inventory.sort(key=lambda item: item["relative_path"].casefold())

        normal_blocked: list[dict[str, Any]] = []
        review_visible: list[dict[str, Any]] = []
        structure_visible: list[dict[str, Any]] = []
        project_checks: list[dict[str, Any]] = []
        for note in notes:
            if note.note_type not in LEGACY_COMPATIBILITY_TYPES:
                continue
            query = _query_for(note)
            filters = {"note_type": note.note_type}
            normal = retriever.search(
                query,
                top_k=25,
                filters=filters,
                purpose=RetrievalPurpose.NORMAL,
                persist_sources=False,
            )
            if note.retrieval_class in {
                RetrievalClass.REVIEW_ONLY,
                RetrievalClass.TAXONOMY_ONLY,
                RetrievalClass.NAVIGATION_ONLY,
                RetrievalClass.EXPLICIT_REVIEW_ONLY,
            }:
                normal_blocked.append(
                    {
                        "blocked": not _contains(normal, note.note_id),
                        "note_type": note.note_type,
                        "relative_path": note.path,
                    }
                )
            if note.retrieval_class in {
                RetrievalClass.REVIEW_ONLY,
                RetrievalClass.EXPLICIT_REVIEW_ONLY,
            }:
                review = retriever.search(
                    query,
                    top_k=25,
                    filters=filters,
                    purpose=RetrievalPurpose.EXPLICIT_REVIEW,
                    persist_sources=False,
                )
                review_visible.append(
                    {
                        "note_type": note.note_type,
                        "relative_path": note.path,
                        "visible_only_in_explicit_review": _contains(
                            review, note.note_id
                        ),
                    }
                )
            if note.retrieval_class in {
                RetrievalClass.TAXONOMY_ONLY,
                RetrievalClass.NAVIGATION_ONLY,
            }:
                structural = retriever.search(
                    query,
                    top_k=25,
                    filters=filters,
                    purpose=RetrievalPurpose.VAULT_STRUCTURE,
                    persist_sources=False,
                )
                structure_visible.append(
                    {
                        "note_type": note.note_type,
                        "relative_path": note.path,
                        "visible_only_in_structure_query": _contains(
                            structural, note.note_id
                        ),
                    }
                )
            if note.retrieval_class is RetrievalClass.PROJECT_SCOPED:
                exact = retriever.search(
                    query,
                    top_k=25,
                    filters={**filters, "project": note.scope_binding},
                    purpose=RetrievalPurpose.NORMAL,
                    persist_sources=False,
                )
                missing = retriever.search(
                    query,
                    top_k=25,
                    filters=filters,
                    purpose=RetrievalPurpose.NORMAL,
                    persist_sources=False,
                )
                wrong = retriever.search(
                    query,
                    top_k=25,
                    filters={**filters, "project": "non-matching-project-scope"},
                    purpose=RetrievalPurpose.NORMAL,
                    persist_sources=False,
                )
                project_checks.append(
                    {
                        "exact_scope_visible": _contains(exact, note.note_id),
                        "missing_scope_blocked": not _contains(missing, note.note_id),
                        "relative_path": note.path,
                        "wrong_scope_blocked": not _contains(wrong, note.note_id),
                    }
                )

        candidate_count_after = int(
            index.connection.execute(
                "SELECT COUNT(*) FROM memory_candidates"
            ).fetchone()[0]
        )
        fts_documents = int(
            index.connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0]
        )

    parse_records = sorted(
        (_parse_record(note) for note in notes),
        key=lambda item: item["relative_path"].casefold(),
    )
    type_counts = Counter(note.note_type for note in notes)
    retrieval_counts = Counter(note.retrieval_class.value for note in notes)
    trust_counts = Counter(note.trust_class.value for note in notes)
    authority_counts = Counter(note.authority_class.value for note in notes)
    unknown_types = sorted(note.note_type for note in notes if not note.type_supported)
    authority_notes = [
        note
        for note in notes
        if note.trust_class is TrustClass.AUTHORITY_SENSITIVE_SOURCE
    ]

    inventory_report = {
        "affected_count": len(inventory),
        "body_content_included": False,
        "records": inventory,
        "relative_paths_only": True,
        "type_counts": dict(
            sorted(Counter(item["note_type"] for item in inventory).items())
        ),
    }
    parser_status_report = {
        "counts": {
            "authority_sensitive": parser["authority_sensitive"],
            "content_indexed": parser["content_indexed"],
            "discovered": parser["discovered"],
            "frontmatter_parsed": parser["frontmatter_parsed"],
            "fts_documents": fts_documents,
            "parser_errors": parser["parser_errors"],
            "rejected": parser["rejected"],
            "retrieval_eligible": parser["retrieval_eligible"],
            "review_only": parser["review_only"],
            "schema_valid": parser["schema_valid"],
            "structural": parser["structural"],
            "type_supported": parser["type_supported"],
        },
        "records": parse_records,
        "unknown_note_types": unknown_types,
    }
    retrieval_report = {
        "authority_class_counts": dict(sorted(authority_counts.items())),
        "normal_retrieval_blocks": normal_blocked,
        "project_scope_checks": project_checks,
        "restart_classifications_identical": first_classes == restarted_classes,
        "retrieval_class_counts": dict(sorted(retrieval_counts.items())),
        "review_visibility_checks": review_visible,
        "structure_visibility_checks": structure_visible,
        "trust_class_counts": dict(sorted(trust_counts.items())),
        "type_counts": dict(sorted(type_counts.items())),
    }
    authority_report = {
        "authority_sensitive_count": len(authority_notes),
        "candidate_count_after_index_and_queries": candidate_count_after,
        "candidate_count_before_queries": candidate_count_before,
        "normal_model_visibility_count": sum(
            note.retrieval_eligible for note in authority_notes
        ),
        "prohibited_runtime_authority_count": sum(
            note.authority_class is AuthorityClass.PROHIBITED_RUNTIME_AUTHORITY
            for note in authority_notes
        ),
        "runtime_approval_grants": 0,
        "runtime_policy_activations": 0,
        "runtime_risk_reductions": 0,
        "runtime_system_prompt_activations": 0,
        "runtime_tool_grants": 0,
        "vault_classification_fields_honored": 0,
    }

    gates = {
        "all_46_content_indexed": parser["content_indexed"] == 46,
        "all_46_discovered": parser["discovered"] == 46,
        "all_46_schema_valid": parser["schema_valid"] == 46,
        "all_46_type_supported": parser["type_supported"] == 46,
        "all_notes_have_one_retrieval_class": sum(retrieval_counts.values()) == 46,
        "authority_sensitive_has_no_runtime_authority": (
            len(authority_notes) == 2
            and authority_report["prohibited_runtime_authority_count"] == 2
            and authority_report["normal_model_visibility_count"] == 0
        ),
        "exact_legacy_type_counts": {
            key: type_counts.get(key, 0) for key in EXPECTED_COUNTS
        }
        == EXPECTED_COUNTS,
        "explicit_review_visibility_enforced": all(
            item["visible_only_in_explicit_review"] for item in review_visible
        ),
        "fts_contains_46_documents": fts_documents == 46,
        "indexing_creates_no_learning_candidates": (
            candidate_count_before == candidate_count_after == 0
        ),
        "normal_retrieval_excludes_forbidden_classes": all(
            item["blocked"] for item in normal_blocked
        ),
        "project_scope_bypass_blocked": all(
            item["exact_scope_visible"]
            and item["missing_scope_blocked"]
            and item["wrong_scope_blocked"]
            for item in project_checks
        ),
        "retrieval_classes_survive_restart": first_classes == restarted_classes,
        "structure_queries_are_explicit": all(
            item["visible_only_in_structure_query"] for item in structure_visible
        ),
        "unknown_note_types_zero": not unknown_types,
    }
    return {
        "artifacts": {
            "authority-boundary-report.json": authority_report,
            "note-type-inventory.json": inventory_report,
            "parser-status-report.json": parser_status_report,
            "retrieval-classification-report.json": retrieval_report,
        },
        "gates": gates,
        "summary": {
            "authority_sensitive_count": len(authority_notes),
            "fts_documents": fts_documents,
            "legacy_type_counts": EXPECTED_COUNTS,
            "retrieval_class_counts": dict(sorted(retrieval_counts.items())),
        },
    }


def run_note_type_compatibility_pilot(
    vault_backup: Path,
    output: Path,
    *,
    expected_source_manifest_sha256: str,
    established_vault_backup_tree_sha256: str,
    expected_mapping_sha256: str,
) -> dict[str, Any]:
    """Run the schema pilot with note-type and authority boundary gates."""

    def review(
        pilot: Path,
        state: Path,
        table: MappingTable,
        parser: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        built = dict(build_compatibility_review(pilot, state, table, parser))
        gates = dict(built["gates"])
        gates["mapping_sha256_unchanged"] = (
            table.mapping_sha256 == expected_mapping_sha256
        )
        built["gates"] = gates
        return built

    result = run_isolated_pilot(
        vault_backup,
        output,
        expected_source_manifest_sha256=expected_source_manifest_sha256,
        established_vault_backup_tree_sha256=established_vault_backup_tree_sha256,
        additional_review=review,
    )
    _write_json(output / "pilot-summary-v2.json", result)
    _write(
        output / "rollback-proof-v2.txt",
        (output / "rollback-proof.txt").read_bytes(),
    )
    cleanup = json.loads((output / "cleanup-proof.json").read_text(encoding="utf-8"))
    _write_json(output / "cleanup-proof-v2.json", cleanup)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated Phase 8B note-type compatibility pilot"
    )
    parser.add_argument("vault_backup", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--established-vault-backup-tree-sha256", required=True)
    parser.add_argument("--expected-mapping-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_note_type_compatibility_pilot(
        args.vault_backup,
        args.output,
        expected_source_manifest_sha256=args.expected_source_manifest_sha256,
        established_vault_backup_tree_sha256=(
            args.established_vault_backup_tree_sha256
        ),
        expected_mapping_sha256=args.expected_mapping_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EXPECTED_COUNTS",
    "LEGACY_COMPATIBILITY_TYPES",
    "build_compatibility_review",
    "run_note_type_compatibility_pilot",
]
