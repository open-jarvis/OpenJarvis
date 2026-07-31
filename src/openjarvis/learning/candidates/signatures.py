"""Stable semantic signatures for candidates, duplicates, and conflicts."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel

from openjarvis.learning.candidates.models import (
    CandidateContent,
    CandidateScope,
    CandidateType,
    CodeImprovementProposalContent,
    DocumentationImprovementContent,
    FactContent,
    FailurePatternContent,
    PreferenceContent,
    ProposedDestination,
    RoutingRuleContent,
    SkillCandidateContent,
    SuccessfulSolutionContent,
    TestCaseContent,
    UserCorrectionContent,
)
from openjarvis.tasks.policy import RiskLevel


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def stable_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: str) -> str:
    return " ".join(value.casefold().split())


def _texts(values: tuple[str, ...]) -> list[str]:
    return sorted({_text(value) for value in values})


def duplicate_content_payload(content: CandidateContent) -> dict[str, object]:
    """Return semantic content with provenance-only references removed."""

    if isinstance(content, FactContent):
        return {
            "subject": _text(content.subject),
            "predicate": _text(content.predicate),
            "value": _text(content.value),
            "scope": content.scope.value,
            "validity": content.validity.value,
        }
    if isinstance(content, UserCorrectionContent):
        return {
            "target_reference": content.target_reference,
            "previous_value_digest": content.previous_value_digest,
            "corrected_value": _text(content.corrected_value),
            "scope": content.correction_scope.value,
        }
    if isinstance(content, PreferenceContent):
        return {
            "subject": _text(content.subject),
            "preference": _text(content.preference),
            "context": _text(content.context),
        }
    if isinstance(content, FailurePatternContent):
        return {
            "failure_category": content.failure_category.value,
            "task_type": content.task_type,
            "triggers": _texts(content.trigger_conditions),
            "symptoms": _texts(content.observed_symptoms),
            "causes": _texts(content.canonical_causes),
            "excluded_causes": _texts(content.excluded_causes),
            "mitigation": _text(content.proposed_mitigation),
            "verification": _texts(content.verification_requirements),
        }
    if isinstance(content, SuccessfulSolutionContent):
        return {
            "task_type": content.task_type,
            "allowed_scope": content.allowed_scope.value,
            "precondition_types": sorted(
                {item.evidence_type.value for item in content.verified_preconditions}
            ),
            "step_types": sorted(
                {item.evidence_type.value for item in content.verified_steps}
            ),
            "postcondition_types": sorted(
                {item.evidence_type.value for item in content.verified_postconditions}
            ),
            "limitations": _texts(content.limitations),
        }
    if isinstance(content, RoutingRuleContent):
        return {
            "condition_key": content.condition_key,
            "recommended_route": content.recommended_route.value,
            "alternatives": sorted(value.value for value in content.alternatives),
            "expected_risk": int(content.expected_risk),
            "limitations": _texts(content.known_limitations),
            "shadow_mode": True,
        }
    if isinstance(content, SkillCandidateContent):
        return {
            "proposed_name": content.proposed_name,
            "purpose": _text(content.purpose),
            "input_schema": content.input_schema_proposal,
            "output_schema": content.output_schema_proposal,
            "preconditions": _texts(content.preconditions),
            "postconditions": _texts(content.postconditions),
            "allowed_tool_ids": sorted(content.allowed_tool_ids),
            "maximum_risk_level": int(content.maximum_risk_level),
            "proposed_steps": [
                {
                    "step_id": step.step_id,
                    "tool_id": step.tool_id,
                    "purpose": _text(step.purpose),
                    "input_binding_ids": sorted(step.input_binding_ids),
                    "expected_evidence_types": sorted(
                        value.value for value in step.expected_evidence_types
                    ),
                }
                for step in content.proposed_steps
            ],
            "negative_cases": _texts(content.negative_cases),
            "rollback_expectation": content.rollback_expectation.value,
        }
    if isinstance(content, TestCaseContent):
        return {
            "fixture_id": content.fixture_id,
            "task_type": content.task_type,
            "expected_evaluation_class": content.expected_evaluation_class.value,
            "evidence_requirements": sorted(
                value.value for value in content.evidence_requirements
            ),
            "negative_case": content.negative_case,
        }
    if isinstance(content, DocumentationImprovementContent):
        return {
            "target_document_id": content.target_document_id,
            "issue_summary": _text(content.issue_summary),
            "proposed_change_summary": _text(content.proposed_change_summary),
            "verification": _texts(content.verification_requirements),
        }
    if isinstance(content, CodeImprovementProposalContent):
        return {
            "component_id": content.component_id,
            "problem_statement": _text(content.problem_statement),
            "safety_boundaries": _texts(content.expected_safety_boundaries),
            "proposed_tests": _texts(content.proposed_tests),
            "expected_behavior": _text(content.expected_behavior),
            "contains_patch": False,
        }
    raise TypeError(f"unsupported candidate content: {type(content).__name__}")


def duplicate_signature(
    *,
    candidate_type: CandidateType,
    scope: CandidateScope,
    project: str,
    content: CandidateContent,
    proposed_destination: ProposedDestination,
    risk_level: RiskLevel,
) -> str:
    """Hash only the normalized fachlich equivalent candidate statement."""

    return stable_digest(
        {
            "candidate_type": candidate_type.value,
            "scope": scope.value,
            "project": project.casefold(),
            "content": duplicate_content_payload(content),
            "proposed_destination": proposed_destination.value,
            "risk_level": int(risk_level),
        }
    )


def conflict_key_payload(
    *,
    candidate_type: CandidateType,
    scope: CandidateScope,
    project: str,
    content: CandidateContent,
) -> dict[str, object]:
    """Return the stable identity of the proposition that could conflict."""

    base: dict[str, object] = {
        "scope": scope.value,
        "project": project.casefold(),
    }
    if isinstance(content, FactContent):
        base.update(
            {
                "family": "fact",
                "subject": _text(content.subject),
                "predicate": _text(content.predicate),
            }
        )
    elif isinstance(content, RoutingRuleContent):
        base.update({"family": "routing", "condition": content.condition_key})
    elif isinstance(content, SkillCandidateContent):
        base.update({"family": "skill", "name": content.proposed_name})
    elif isinstance(content, SuccessfulSolutionContent):
        base.update({"family": "task_behavior", "task_type": content.task_type})
    elif isinstance(content, FailurePatternContent):
        base.update({"family": "task_behavior", "task_type": content.task_type})
    elif isinstance(content, UserCorrectionContent):
        base.update({"family": "user_correction", "target": content.target_reference})
    elif isinstance(content, PreferenceContent):
        base.update({"family": "preference", "subject": _text(content.subject)})
    else:
        base.update(
            {
                "family": candidate_type.value,
                "content": duplicate_content_payload(content),
            }
        )
    return base


def conflict_signature(
    *,
    candidate_type: CandidateType,
    scope: CandidateScope,
    project: str,
    content: CandidateContent,
) -> str:
    return stable_digest(
        conflict_key_payload(
            candidate_type=candidate_type,
            scope=scope,
            project=project,
            content=content,
        )
    )


__all__ = [
    "canonical_json",
    "conflict_key_payload",
    "conflict_signature",
    "duplicate_content_payload",
    "duplicate_signature",
    "stable_digest",
]
