from __future__ import annotations

import ast
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

import openjarvis.learning.evaluation as evaluation_package
from openjarvis.learning.evaluation import (
    CanonicalTaskOutcome,
    EvaluationClass,
    EvaluationInput,
    ToolActionSnapshot,
    TraceClassifier,
    canonical_json,
)


def test_canonical_evaluation_classes_are_closed() -> None:
    assert {item.value for item in EvaluationClass} == {
        "completed",
        "completed_with_warning",
        "partial",
        "interrupted",
        "canceled",
        "policy_denied",
        "approval_denied",
        "approval_timeout",
        "verification_failed",
        "tool_failed",
        "browser_failed",
        "insufficient_evidence",
        "conflicting_evidence",
        "budget_exceeded",
        "unsafe_request",
        "unknown_failure",
    }
    assert "success" not in {item.value for item in EvaluationClass}


def test_trace_evaluation_schema_contains_only_metadata_fields() -> None:
    from openjarvis.learning.evaluation import TraceEvaluation

    assert set(TraceEvaluation.model_fields) == {
        "schema_version",
        "evaluation_id",
        "evaluator_id",
        "evaluator_version",
        "task_id",
        "session_id",
        "correlation_id",
        "trace_id",
        "task_type",
        "requested_goal",
        "terminal_task_state",
        "task_outcome",
        "evaluation_class",
        "verification_state",
        "approval_state",
        "policy_result",
        "evidence_state",
        "tool_result_summary",
        "failure_category",
        "confidence",
        "confidence_basis",
        "evidence_references",
        "warnings",
        "created_at",
        "input_digest",
        "evaluation_hash",
    }


def test_legacy_success_is_not_a_canonical_task_outcome() -> None:
    with pytest.raises(ValidationError):
        EvaluationInput.model_validate(
            {
                "task_id": "task",
                "session_id": "session",
                "correlation_id": "correlation",
                "trace_id": "trace",
                "task_type": "synthetic",
                "requested_goal": "Synthetic goal",
                "terminal_task_state": "done",
                "task_outcome": "success",
                "verification_state": "passed",
                "approval_state": "not_required",
                "policy_result": "not_required",
                "browser_recovery_state": "not_applicable",
                "evidence_state": "sufficient",
                "budget_state": "within_limits",
                "external_effect_state": "none",
            }
        )
    assert CanonicalTaskOutcome.UNKNOWN.value == "unknown"


@pytest.mark.parametrize(
    "private_field",
    [
        "prompt",
        "response",
        "messages",
        "chat_history",
        "tool_output",
        "webpage_content",
        "note_content",
        "chain_of_thought",
        "reasoning_tokens",
        "secret",
    ],
)
def test_private_or_unknown_payload_fields_are_rejected(
    completed_snapshot: EvaluationInput,
    private_field: str,
) -> None:
    payload = completed_snapshot.model_dump(mode="python")
    payload[private_field] = "must not persist"

    with pytest.raises(ValidationError):
        EvaluationInput.model_validate(payload)


@pytest.mark.parametrize(
    "private_field",
    ["raw_output", "stdout", "stderr", "response_body", "cookies"],
)
def test_tool_snapshot_rejects_raw_payload_fields(private_field: str) -> None:
    payload = {
        "action_id": "action",
        "state": "completed",
        "verification_state": "passed",
        "effect_known": True,
        private_field: "private",
    }

    with pytest.raises(ValidationError):
        ToolActionSnapshot.model_validate(payload)


def test_secret_like_requested_goal_is_rejected(
    completed_snapshot: EvaluationInput,
) -> None:
    payload = completed_snapshot.model_dump(mode="python")
    payload["requested_goal"] = "Use " + "sk-" + "a" * 30

    with pytest.raises(ValidationError, match="secret-like"):
        EvaluationInput.model_validate(payload)


def test_trace_evaluation_is_immutable(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(completed_snapshot)

    with pytest.raises(ValidationError):
        evaluation.evaluation_class = EvaluationClass.UNKNOWN_FAILURE  # type: ignore[misc]


def test_evaluation_input_is_immutable(
    completed_snapshot: EvaluationInput,
) -> None:
    with pytest.raises(ValidationError):
        completed_snapshot.requested_goal = "Changed"  # type: ignore[misc]


def test_trace_evaluation_rejects_unknown_fields(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(completed_snapshot)
    payload = evaluation.model_dump(mode="python")
    payload["model_reasoning"] = "not allowed"

    with pytest.raises(ValidationError):
        type(evaluation).model_validate(payload)


def test_trace_evaluation_rejects_a_tampered_semantic_hash(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(completed_snapshot)
    payload = evaluation.model_dump(mode="python")
    payload["evaluation_class"] = EvaluationClass.UNKNOWN_FAILURE

    with pytest.raises(ValidationError, match="evaluation_hash"):
        type(evaluation).model_validate(payload)


def test_trace_evaluation_hash_is_self_verifiable(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(completed_snapshot)

    assert evaluation.recompute_hash() == evaluation.evaluation_hash


def test_serialization_is_utc_and_stably_sorted(
    completed_snapshot: EvaluationInput,
) -> None:
    evaluation = TraceClassifier().evaluate(completed_snapshot)
    serialized = canonical_json(evaluation)
    parsed = json.loads(serialized)

    assert parsed["created_at"].endswith("Z")
    assert serialized.startswith('{"approval_state":')
    assert [item["evidence_id"] for item in parsed["evidence_references"]] == [
        item.evidence_id for item in evaluation.evidence_references
    ]


def test_classifier_performs_no_network_access(
    completed_snapshot: EvaluationInput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)

    assert TraceClassifier().evaluate(completed_snapshot).evaluation_hash


def test_domain_has_no_model_network_codex_or_process_imports() -> None:
    root = Path(evaluation_package.__file__).parent
    forbidden_roots = {
        "anthropic",
        "dspy",
        "gepa",
        "httpx",
        "ollama",
        "openai",
        "requests",
        "socket",
        "subprocess",
    }
    forbidden_modules = {
        "openjarvis.codex",
        "openjarvis.engine",
        "openjarvis.learning.agents",
        "openjarvis.learning.routing",
        "openjarvis.learning.spec_search",
        "openjarvis.skills",
    }
    imports: set[str] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    assert not {name.split(".")[0] for name in imports} & forbidden_roots
    assert not {
        module
        for module in forbidden_modules
        if any(name == module or name.startswith(f"{module}.") for name in imports)
    }
    assert not any(name.endswith(".store") for name in imports)
