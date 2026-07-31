from __future__ import annotations

import ast
import socket
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from openjarvis.learning.candidates import (
    CandidateExtractor,
    CandidateOrigin,
    CandidateState,
    CandidateType,
    CodeImprovementProposalContent,
    FactContent,
    FactValidity,
    LearningCandidate,
    ProposedDestination,
    ProvenanceEntry,
    ProvenanceSourceKind,
    QuarantineReason,
    RouteRecommendation,
    RoutingRuleContent,
    StructuredCandidateRequest,
)
from openjarvis.learning.candidates.models import ExtractionMethod
from openjarvis.learning.candidates.quarantine import scan_text
from openjarvis.learning.evaluation import TrustedBoundary

from .conftest import NOW, digest, envelope, make_evaluation

CANDIDATE_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "openjarvis"
    / "learning"
    / "candidates"
)


def _candidate() -> LearningCandidate:
    return (
        CandidateExtractor()
        .extract((envelope(make_evaluation()),), created_at=NOW)
        .candidates[0]
    )


def _rebuild(candidate: LearningCandidate, **changes: object) -> LearningCandidate:
    payload = {
        field_name: getattr(candidate, field_name)
        for field_name in type(candidate).model_fields
        if field_name != "content_hash"
    }
    payload.update(changes)
    draft = LearningCandidate.model_construct(**payload, content_hash="0" * 64)
    return LearningCandidate(**payload, content_hash=draft.recompute_hash())


def test_candidate_types_are_closed_and_complete() -> None:
    assert {item.value for item in CandidateType} == {
        "fact",
        "user_correction",
        "preference",
        "failure_pattern",
        "successful_solution",
        "routing_rule",
        "skill",
        "test_case",
        "documentation_improvement",
        "code_improvement_proposal",
    }


def test_candidate_states_are_minimal() -> None:
    assert {item.value for item in CandidateState} == {
        "proposed",
        "under_review",
        "rejected",
        "quarantined",
    }


@pytest.mark.parametrize("forbidden", ["verified", "active", "promoted", "testing"])
def test_later_candidate_state_is_rejected(forbidden: str) -> None:
    with pytest.raises(ValueError):
        CandidateState(forbidden)


def test_candidate_is_immutable() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError):
        candidate.state = CandidateState.REJECTED


def test_candidate_rejects_unknown_fields() -> None:
    payload = _candidate().model_dump()
    payload["raw_tool_output"] = "synthetic"
    with pytest.raises(ValidationError):
        LearningCandidate.model_validate(payload)


def test_candidate_rejects_naive_utc_timestamp() -> None:
    payload = _candidate().model_dump()
    payload["created_at"] = datetime(2026, 7, 31, 12, 0)
    with pytest.raises(ValidationError, match="UTC offset"):
        LearningCandidate.model_validate(payload)


def test_candidate_rejects_revision_zero() -> None:
    payload = _candidate().model_dump()
    payload["revision"] = 0
    with pytest.raises(ValidationError):
        LearningCandidate.model_validate(payload)


def test_candidate_detects_content_hash_tampering() -> None:
    payload = _candidate().model_dump()
    payload["title"] = "Changed synthetic title"
    with pytest.raises(ValidationError, match="content_hash"):
        LearningCandidate.model_validate(payload)


def test_automatic_candidate_cannot_enter_review_state() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="only propose or quarantine"):
        _rebuild(candidate, state=CandidateState.UNDER_REVIEW)


def test_fact_request_without_feedback_is_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit feedback"):
        StructuredCandidateRequest(
            request_id="request_fact",
            candidate_type=CandidateType.FACT,
            title="Synthetic fact",
            content=FactContent(
                subject="synthetic user",
                predicate="locale",
                value="locale alpha",
                scope="user",
                validity=FactValidity.UNKNOWN,
                explicit_user_confirmation_required=True,
            ),
            scope="user",
            project="project_a",
            source_evaluation_ids=("evaluation_a",),
            proposed_tests=("synthetic fact review",),
            proposed_verification=("explicit user confirmation",),
            proposed_destination=ProposedDestination.MEMORY_CANDIDATE,
        )


def test_routing_destination_is_restricted() -> None:
    with pytest.raises(ValidationError, match="routing_shadow"):
        StructuredCandidateRequest(
            request_id="request_route",
            candidate_type=CandidateType.ROUTING_RULE,
            title="Synthetic route",
            content=RoutingRuleContent(
                condition_key="synthetic.condition",
                recommended_route=RouteRecommendation.READ_ONLY_ANALYSIS,
                expected_risk=0,
            ),
            scope="project",
            project="project_a",
            source_evaluation_ids=("evaluation_a",),
            proposed_tests=("synthetic route review",),
            proposed_verification=("shadow evaluation",),
            proposed_destination=ProposedDestination.LEARNING_REVIEW,
        )


def test_code_proposal_cannot_contain_patch() -> None:
    with pytest.raises(ValidationError):
        CodeImprovementProposalContent(
            component_id="synthetic.component",
            problem_statement="Synthetic problem",
            expected_safety_boundaries=("no external effect",),
            proposed_tests=("synthetic regression",),
            expected_behavior="Remain metadata only",
            contains_patch=True,
        )


@pytest.mark.parametrize(
    "fragment",
    [
        "ev" + "al(user_text)",
        "ex" + "ec(user_text)",
        "pickle" + ".loads(user_text)",
        "__im" + "port__(user_text)",
    ],
)
def test_executable_free_text_is_rejected(fragment: str) -> None:
    with pytest.raises(ValidationError, match="forbidden executable code"):
        CodeImprovementProposalContent(
            component_id="synthetic.component",
            problem_statement=fragment,
            expected_safety_boundaries=("no external effect",),
            proposed_tests=("synthetic regression",),
            expected_behavior="Remain metadata only",
        )


def test_secret_like_text_is_rejected() -> None:
    secret = "sk-" + "A" * 24
    with pytest.raises(ValidationError, match="secret-like"):
        FactContent(
            subject="synthetic user",
            predicate="credential",
            value=secret,
            scope="user",
            validity=FactValidity.UNKNOWN,
            explicit_user_confirmation_required=True,
        )


def test_base64_scanner_does_not_flag_benign_digest() -> None:
    assert QuarantineReason.BASE64_CODE not in scan_text(digest("benign"))


def test_user_provenance_requires_explicit_user_boundary() -> None:
    with pytest.raises(ValidationError, match="explicit_user boundary"):
        ProvenanceEntry(
            source_kind=ProvenanceSourceKind.EXPLICIT_USER_FEEDBACK,
            source_id="feedback_a",
            source_digest=digest("feedback_a"),
            trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
            extraction_method=ExtractionMethod.EXPLICIT_USER_FEEDBACK,
            extraction_version="1.0.0",
            created_at=NOW,
        )


def test_evaluation_provenance_requires_evaluation_id() -> None:
    with pytest.raises(ValidationError, match="requires evaluation_id"):
        ProvenanceEntry(
            source_kind=ProvenanceSourceKind.DETERMINISTIC_TRACE_EVALUATION,
            source_id="evaluation_a",
            source_digest=digest("evaluation_a"),
            trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
            extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
            extraction_version="1.0.0",
            created_at=NOW,
        )


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "raw_model_answer",
        "raw_tool_output",
        "browser_dom",
        "webpage_content",
        "note_content",
        "audio",
        "screenshot",
        "cookie",
        "token",
        "credential",
        "chain_of_thought",
        "reasoning_tokens",
    ],
)
def test_private_payload_is_not_candidate_schema_field(forbidden_field: str) -> None:
    properties = LearningCandidate.model_json_schema()["properties"]
    assert forbidden_field not in properties


@pytest.mark.parametrize(
    "forbidden_import",
    [
        "openai",
        "requests",
        "httpx",
        "socket",
        "subprocess",
    ],
)
def test_candidate_source_has_no_forbidden_import(forbidden_import: str) -> None:
    imported: set[str] = set()
    for path in CANDIDATE_SOURCE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert forbidden_import not in imported


@pytest.mark.parametrize(
    "forbidden_symbol",
    [
        "ToolExecutor",
        "SkillExecutor",
        "LearnedRouter",
        "Codex",
        "Ollama",
        "SpecSearch",
        "Spec Search",
        "OptimizationStore",
        "StoreImport",
    ],
)
def test_candidate_source_has_no_forbidden_runtime_symbol(
    forbidden_symbol: str,
) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in CANDIDATE_SOURCE.glob("*.py")
    )
    assert forbidden_symbol not in source


@pytest.mark.parametrize(
    "restricted_marker",
    [
        "jarvis-desktop",
        "Obsidian",
        "46 notes",
        "full_access sandbox",
    ],
)
def test_candidate_source_has_no_restricted_local_data_marker(
    restricted_marker: str,
) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in CANDIDATE_SOURCE.glob("*.py")
    )
    assert restricted_marker not in source


def test_extraction_result_hash_validates() -> None:
    result = CandidateExtractor().extract(
        (envelope(make_evaluation()),), created_at=NOW
    )
    assert result.run_hash == result.recompute_hash()


def test_extraction_does_not_open_network_socket(monkeypatch) -> None:
    def fail_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("candidate extraction attempted network access")

    monkeypatch.setattr(socket, "socket", fail_socket)
    result = CandidateExtractor().extract(
        (envelope(make_evaluation()),), created_at=NOW
    )
    assert result.candidates


def test_origin_enum_has_no_candidate_derived_source() -> None:
    assert "candidate" not in {item.value for item in CandidateOrigin}
