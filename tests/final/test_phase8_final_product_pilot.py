"""Hermetic tests for the fixed final product-pilot evidence validator."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from scripts.phase8_final_product_pilot import (
    FINAL_RUNTIME_MARKER,
    FINAL_WEBSITE_WORKSPACE_ID,
    OfflineSocketViolation,
    PilotEvidenceError,
    loopback_socket_guard,
    validate_final_pilot_evidence,
)

from openjarvis.migration.vault_schema_pilot import build_manifest


def _health(pid: int) -> dict[str, Any]:
    return {
        "runtime_marker": FINAL_RUNTIME_MARKER,
        "runtime": "phase8-final",
        "status": "ready",
        "backend": "python_sdk",
        "pid": pid,
        "memory_note_count": 46,
        "memory_parser_errors": 0,
        "memory_schema_valid": 46,
        "memory_type_supported": 46,
        "memory_fts_documents": 46,
        "learning_status": "healthy",
        "skill_registry_readable": True,
        "skill_count": 0,
    }


def _source(
    count: int,
    retrieval_class: str | None = None,
    note_type: str | None = None,
    authority: str | None = None,
) -> dict[str, Any]:
    return {
        "selected_count": count,
        "retrieval_classes": [] if retrieval_class is None else [retrieval_class],
        "note_types": [] if note_type is None else [note_type],
        "authority_classes": [] if authority is None else [authority],
    }


def _evidence(vault: Path) -> dict[str, Any]:
    _manifest, digest = build_manifest(vault)
    return {
        "schema_version": "1.0",
        "origin": "http://127.0.0.1:8000",
        "health": {"before": _health(1001), "after": _health(1002)},
        "retrieval": {
            "normal": _source(1, "normal", "fact", "none"),
            "project_exact": _source(1, "project_scoped", "project_profile", "none"),
            "project_wrong": _source(0),
            "project_missing": _source(0),
            "review_memory_proposal": _source(
                1, "review_only", "memory_proposal", "none"
            ),
            "structure_category": _source(1, "taxonomy_only", "category", "none"),
            "structure_navigation": _source(1, "navigation_only", "navigation", "none"),
            "explicit_system_policy": _source(
                1,
                "explicit_review_only",
                "system_policy",
                "prohibited_runtime_authority",
            ),
            "explicit_system_profile": _source(
                1,
                "explicit_review_only",
                "system_profile",
                "prohibited_runtime_authority",
            ),
            "normal_authority_exclusion": _source(0),
        },
        "tool_action": {
            "preview": True,
            "policy": True,
            "allow_once": True,
            "apply": True,
            "verification": True,
            "timeline": True,
            "rollback": True,
            "cleanup": True,
            "workspace_removed": True,
            "action_id": "action-final",
            "timeline_events": 7,
            "verification_status": "passed",
        },
        "website": {
            "preview": True,
            "apply": True,
            "artifact_manifest": True,
            "verification": True,
            "restart_readback": True,
            "rollback": True,
            "rollback_byte_identical": True,
            "cleanup": True,
            "no_javascript": True,
            "no_network": True,
            "no_publish": True,
            "workspace_id": FINAL_WEBSITE_WORKSPACE_ID,
            "execution_id": "execution-final",
            "manifest_sha256": "a" * 64,
        },
        "learning": {
            "trace_evaluation": True,
            "evaluation_id": "evaluation-final",
            "candidate_states": ["proposed"],
            "promotion_count_delta": 0,
            "activation_count_delta": 0,
            "shadow_mode": True,
            "productive_route_changed": False,
            "feedback_revisions": 2,
            "learning_readback": True,
        },
        "restart": {
            "calls": 1,
            "controlled_shutdown": True,
            "health_after_restart": True,
            "new_process": True,
        },
        "offline_guard": {
            "enabled": True,
            "non_loopback_denied": True,
            "external_calls": 0,
            "codex_live_calls": 0,
        },
        "vault_stability": {
            "before_manifest_sha256": digest,
            "after_manifest_sha256": digest,
            "file_count": 59,
            "stable": True,
        },
    }


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    vault = tmp_path / "vault"
    runtime.mkdir()
    vault.mkdir()
    for index in range(59):
        (vault / f"item-{index:02}.txt").write_text(
            f"synthetic-{index}\n", encoding="utf-8"
        )
    return runtime, vault


def test_valid_fixed_evidence_produces_payload_safe_report(tmp_path: Path) -> None:
    runtime, vault = _roots(tmp_path)
    report = validate_final_pilot_evidence(
        evidence=_evidence(vault),
        base_url="http://127.0.0.1:8000",
        runtime_root=runtime,
        vault_root=vault,
    )
    assert report["status"] == "passed"
    assert report["vault_stability"]["file_count"] == 59
    assert report["restart"]["calls"] == 1
    rendered = json.dumps(report)
    assert str(runtime) not in rendered
    assert str(vault) not in rendered
    for forbidden in ("payload", "content", "authorization", "cookie", "token"):
        assert forbidden not in rendered.casefold()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["learning"].update({"activation_count_delta": 1}),
            "learning authority",
        ),
        (
            lambda value: value["retrieval"]["normal"].update(
                {
                    "retrieval_classes": ["explicit_review_only"],
                    "authority_classes": ["prohibited_runtime_authority"],
                }
            ),
            "retrieval.normal",
        ),
        (
            lambda value: value["restart"].update({"calls": 2}),
            "controlled restart",
        ),
    ],
)
def test_authority_retrieval_and_restart_fail_closed(
    tmp_path: Path, mutate, message: str
) -> None:  # noqa: ANN001
    runtime, vault = _roots(tmp_path)
    evidence = _evidence(vault)
    mutate(evidence)
    with pytest.raises(PilotEvidenceError, match=message):
        validate_final_pilot_evidence(
            evidence=evidence,
            base_url="http://127.0.0.1:8000",
            runtime_root=runtime,
            vault_root=vault,
        )


def test_current_vault_and_cleanup_state_are_verified(tmp_path: Path) -> None:
    runtime, vault = _roots(tmp_path)
    evidence = _evidence(vault)
    (vault / "item-00.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(PilotEvidenceError, match="vault changed"):
        validate_final_pilot_evidence(
            evidence=evidence,
            base_url="http://127.0.0.1:8000",
            runtime_root=runtime,
            vault_root=vault,
        )
    evidence = _evidence(vault)
    leftover = runtime / "phase8-final-product-pilot-workspace"
    leftover.mkdir()
    with pytest.raises(PilotEvidenceError, match="cleanup"):
        validate_final_pilot_evidence(
            evidence=evidence,
            base_url="http://127.0.0.1:8000",
            runtime_root=runtime,
            vault_root=vault,
        )


def test_non_loopback_origin_and_socket_are_rejected(tmp_path: Path) -> None:
    runtime, vault = _roots(tmp_path)
    with pytest.raises(PilotEvidenceError, match="loopback"):
        validate_final_pilot_evidence(
            evidence=_evidence(vault),
            base_url="http://198.51.100.10:8000",
            runtime_root=runtime,
            vault_root=vault,
        )
    with loopback_socket_guard(), pytest.raises(OfflineSocketViolation):
        socket.create_connection(("198.51.100.10", 9), timeout=0.01)
