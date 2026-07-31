"""Hermetic tests for canonical skill execution and legacy-path blocking."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openjarvis.core.events import EventBus
from openjarvis.learning.skills import (
    ApprovalDecision,
    CanonicalSkillExecutor,
    SkillApprovalRequired,
    SkillExecutionError,
    SkillExecutionOutcome,
    SkillExecutionPin,
    SkillExecutionRequest,
    SkillTaskBudget,
)
from openjarvis.learning.skills.manifest import (
    SkillIdempotencyPolicy,
    SkillManifest,
)
from openjarvis.learning.skills.registry import SkillRegistry
from openjarvis.skills.executor import LegacySkillExecutionBlocked, SkillExecutor
from openjarvis.skills.loader import LegacySkillLoadBlocked, load_skill
from openjarvis.skills.manager import SkillManager
from openjarvis.skills.types import SkillManifest as LegacySkillManifest
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools.actions import (
    ActionStatus,
    ToolAction,
    ToolProposal,
    VerificationStatus,
)
from openjarvis.workflow.engine import WorkflowEngine
from openjarvis.workflow.graph import WorkflowGraph

from .test_manifest_legacy import valid_draft
from .test_registry import _register, _registry, _seed_reviewed_skill


class _ActionServiceDouble:
    """Structured action boundary with no direct tool callable."""

    def __init__(
        self,
        *,
        waiting: bool = False,
        effect_known: bool = True,
        verification: VerificationStatus = VerificationStatus.PASSED,
        delay_seconds: float = 0,
    ) -> None:
        self.waiting = waiting
        self.effect_known = effect_known
        self.verification = verification
        self.delay_seconds = delay_seconds
        self.proposals: list[ToolProposal] = []
        self.actions: dict[str, ToolAction] = {}
        self.proposal_actions: dict[str, str] = {}
        self.execute_calls = 0
        self.approve_calls = 0
        self.deny_calls = 0
        self.retry_calls = 0

    def create(self, proposal: ToolProposal) -> ToolAction:
        previous = self.proposal_actions.get(proposal.proposal_id)
        if previous is not None:
            return self.actions[previous]
        self.proposals.append(proposal)
        action = ToolAction.from_proposal(
            proposal,
            manifest_version="1.0.0",
            effective_risk=proposal.risk_level,
        )
        update = {
            "status": (
                ActionStatus.WAITING_APPROVAL
                if self.waiting
                else ActionStatus.VALIDATED
            )
        }
        if self.waiting:
            update["approval_id"] = "approval_fixture"
        action = action.model_copy(update=update)
        self.actions[action.action_id] = action
        self.proposal_actions[proposal.proposal_id] = action.action_id
        return action

    async def execute(
        self, action_id: str, *, approved_once: bool = False
    ) -> ToolAction:
        self.execute_calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        action = self.actions[action_id].model_copy(
            update={
                "status": (
                    ActionStatus.COMPLETED if self.effect_known else ActionStatus.FAILED
                ),
                "verification_status": self.verification,
                "tool_run_id": "tool_run_fixture",
                "effect_known": self.effect_known,
            }
        )
        self.actions[action_id] = action
        return action

    async def approve(self, action_id: str, *, decision_id: str) -> ToolAction:
        assert decision_id
        self.approve_calls += 1
        return await self.execute(action_id, approved_once=True)

    def deny(self, action_id: str, *, decision_id: str) -> ToolAction:
        assert decision_id
        self.deny_calls += 1
        action = self.actions[action_id].model_copy(
            update={"status": ActionStatus.DENIED}
        )
        self.actions[action_id] = action
        return action

    async def retry(self, action_id: str) -> ToolAction:
        self.retry_calls += 1
        return await self.execute(action_id)


def _request(**updates) -> SkillExecutionRequest:
    values = {
        "task_id": "task_execution_fixture",
        "session_id": "session_execution_fixture",
        "correlation_id": "correlation_execution_fixture",
        "thread_id": "thread_execution_fixture",
        "turn_id": "turn_execution_fixture",
        "item_id": "item_execution_fixture",
        "scope_key": "project_fixture",
        "inputs": {"path": "fixtures/example.txt"},
        "execution_lane": ExecutionLane.MODEL,
        "task_risk_level": RiskLevel.READ_ONLY,
        "budget": SkillTaskBudget(maximum_steps=1, maximum_runtime_seconds=10),
        "idempotency_key": "execute_skill_fixture",
    }
    values.update(updates)
    return SkillExecutionRequest.model_validate(values)


def _registered_pin(
    tmp_path: Path,
    *,
    draft_updates: dict | None = None,
) -> tuple[SkillRegistry, SkillExecutionPin]:
    learning, registry = _registry((tmp_path / "execution.sqlite3").resolve())
    candidate_id = _seed_reviewed_skill(learning, suffix="execution")
    manifest = SkillManifest.create(
        valid_draft(
            origin_candidate_id=candidate_id,
            origin_candidate_revision=2,
            **(draft_updates or {}),
        )
    )
    _register(registry, manifest, key="register_execution_fixture")
    request = _request()
    pin = SkillExecutionPin.create(
        {
            "pin_id": "skill_pin_fixture",
            "task_id": request.task_id,
            "session_id": request.session_id,
            "correlation_id": request.correlation_id,
            "scope_key": request.scope_key,
            "scope_revision": 1,
            "skill_id": manifest.skill_id,
            "semantic_version": manifest.semantic_version,
            "manifest_hash": manifest.content_hash,
            "created_at": "2026-07-31T12:00:00Z",
        }
    )
    with registry.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO skill_execution_pins(
                pin_id, task_id, session_id, correlation_id, scope_key,
                scope_revision, skill_id, semantic_version, manifest_hash,
                pin_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pin.pin_id,
                pin.task_id,
                pin.session_id,
                pin.correlation_id,
                pin.scope_key,
                pin.scope_revision,
                pin.skill_id,
                pin.semantic_version,
                pin.manifest_hash,
                pin.pin_hash,
                pin.model_dump_json(),
                pin.created_at.isoformat(),
            ),
        )
    return registry, pin


@pytest.mark.asyncio
async def test_execution_uses_only_action_service_and_persists_restart_safe_record(
    tmp_path: Path,
) -> None:
    registry, pin = _registered_pin(tmp_path)
    service = _ActionServiceDouble()
    executor = CanonicalSkillExecutor(registry, action_service=service)

    first = await executor.execute_pinned(pin.pin_id, _request())
    replay = await CanonicalSkillExecutor(
        registry, action_service=service
    ).execute_pinned(pin.pin_id, _request())

    assert first.outcome is SkillExecutionOutcome.COMPLETED
    assert replay == first
    assert service.execute_calls == 1
    assert len(service.proposals) == 1
    assert service.proposals[0].tool_id == "file.read"
    assert service.proposals[0].arguments == {"path": "fixtures/example.txt"}
    assert executor.get_execution(first.execution_id) == first
    assert first.steps[0].verification_status is VerificationStatus.PASSED


@pytest.mark.asyncio
async def test_missing_action_service_and_unsafe_inputs_fail_closed(
    tmp_path: Path,
) -> None:
    registry, pin = _registered_pin(tmp_path)
    request = _request()
    with pytest.raises(SkillExecutionError, match="ToolActionService"):
        await CanonicalSkillExecutor(registry, action_service=None).execute_pinned(
            pin.pin_id, request
        )
    with pytest.raises(SkillExecutionError, match="secret-like"):
        await CanonicalSkillExecutor(
            registry, action_service=_ActionServiceDouble()
        ).execute_pinned(
            pin.pin_id,
            _request(inputs={"path": "sk-abcdefghijklmnopqrstuvwxyz012345"}),
        )


@pytest.mark.asyncio
async def test_effective_risk_level_four_is_denied_before_action_creation(
    tmp_path: Path,
) -> None:
    registry, pin = _registered_pin(tmp_path)
    service = _ActionServiceDouble()

    record = await CanonicalSkillExecutor(
        registry, action_service=service
    ).execute_pinned(
        pin.pin_id,
        _request(task_risk_level=RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL),
    )

    assert record.outcome is SkillExecutionOutcome.POLICY_DENIED
    assert record.steps == ()
    assert service.proposals == []


@pytest.mark.asyncio
async def test_allow_once_and_deny_are_exactly_delegated(tmp_path: Path) -> None:
    registry, pin = _registered_pin(tmp_path)
    approved = _ActionServiceDouble(waiting=True)
    with pytest.raises(SkillApprovalRequired):
        await CanonicalSkillExecutor(registry, action_service=approved).execute_pinned(
            pin.pin_id, _request()
        )
    approved_record = await CanonicalSkillExecutor(
        registry, action_service=approved
    ).execute_pinned(
        pin.pin_id,
        _request(
            approval_decisions={
                "read_fixture": ApprovalDecision(
                    allow_once=True, decision_id="decision_allow_once"
                )
            }
        ),
    )
    assert approved_record.outcome is SkillExecutionOutcome.COMPLETED
    assert approved.approve_calls == 1
    assert len(approved.proposals) == 1

    registry_two, pin_two = _registered_pin(tmp_path / "denied")
    denied = _ActionServiceDouble(waiting=True)
    denied_record = await CanonicalSkillExecutor(
        registry_two, action_service=denied
    ).execute_pinned(
        pin_two.pin_id,
        _request(
            approval_decisions={
                "read_fixture": ApprovalDecision(
                    allow_once=False, decision_id="decision_deny_once"
                )
            }
        ),
    )
    assert denied_record.outcome is SkillExecutionOutcome.APPROVAL_DENIED
    assert denied.deny_calls == 1


@pytest.mark.asyncio
async def test_budget_timeout_is_unknown_and_never_retried(tmp_path: Path) -> None:
    registry, pin = _registered_pin(
        tmp_path,
        draft_updates={
            "retry_policy": {"maximum_retries": 1},
            "idempotency_policy": SkillIdempotencyPolicy.SAFE_RETRY,
        },
    )
    service = _ActionServiceDouble(delay_seconds=0.05)
    record = await CanonicalSkillExecutor(
        registry, action_service=service
    ).execute_pinned(
        pin.pin_id,
        _request(
            budget=SkillTaskBudget(maximum_steps=1, maximum_runtime_seconds=0.005)
        ),
    )
    assert record.outcome is SkillExecutionOutcome.UNKNOWN
    assert record.effect_known is False
    assert service.retry_calls == 0


@pytest.mark.asyncio
async def test_unknown_effect_is_never_retried_and_verification_is_required(
    tmp_path: Path,
) -> None:
    registry, pin = _registered_pin(
        tmp_path,
        draft_updates={
            "retry_policy": {"maximum_retries": 1},
            "idempotency_policy": SkillIdempotencyPolicy.SAFE_RETRY,
        },
    )
    unknown = _ActionServiceDouble(effect_known=False)
    record = await CanonicalSkillExecutor(
        registry, action_service=unknown
    ).execute_pinned(pin.pin_id, _request())
    assert record.outcome is SkillExecutionOutcome.UNKNOWN
    assert unknown.retry_calls == 0

    registry_two, pin_two = _registered_pin(tmp_path / "unverified")
    unverified = _ActionServiceDouble(verification=VerificationStatus.PENDING)
    unverified_record = await CanonicalSkillExecutor(
        registry_two, action_service=unverified
    ).execute_pinned(pin_two.pin_id, _request())
    assert unverified_record.outcome is SkillExecutionOutcome.FAILED


@pytest.mark.asyncio
async def test_cycle_depth_lane_and_pin_mismatch_fail_before_actions(
    tmp_path: Path,
) -> None:
    registry, pin = _registered_pin(tmp_path)
    service = _ActionServiceDouble()
    executor = CanonicalSkillExecutor(registry, action_service=service)
    with pytest.raises(SkillExecutionError, match="cycle"):
        await executor.execute_pinned(
            pin.pin_id,
            _request(call_stack=("skill.synthetic-read@1.0.0",)),
        )
    with pytest.raises(SkillExecutionError, match="execution request differs"):
        await executor.execute_pinned(
            pin.pin_id,
            _request(task_id="different_task"),
        )
    with pytest.raises(SkillExecutionError, match="maximum call depth"):
        await executor.execute_pinned(
            pin.pin_id,
            _request(call_stack=("skill.other@1.0.0",)),
        )
    assert service.proposals == []


def test_legacy_load_discovery_execution_and_workflow_paths_are_blocked(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "skill.toml"
    fixture.write_text("[skill]\nname = 'legacy-fixture'\n", encoding="utf-8")
    with pytest.raises(LegacySkillLoadBlocked):
        load_skill(fixture, canonical_mode=True)

    legacy_manifest = LegacySkillManifest(name="legacy-fixture")
    with pytest.raises(LegacySkillExecutionBlocked):
        SkillExecutor(object(), canonical_mode=True).run(legacy_manifest)  # type: ignore[arg-type]

    manager = SkillManager(EventBus(), overlay_dir=tmp_path, canonical_mode=True)
    with pytest.raises(LegacySkillExecutionBlocked):
        manager.discover([tmp_path])
    with pytest.raises(LegacySkillExecutionBlocked):
        manager.execute("legacy-fixture")
    assert manager.get_skill_tools() == []
    assert manager.get_catalog_xml() == "<available_skills>\n</available_skills>"

    blocked = WorkflowEngine(canonical_mode=True).run(WorkflowGraph("legacy-workflow"))
    assert blocked.success is False
    assert "blocked in canonical mode" in blocked.final_output
