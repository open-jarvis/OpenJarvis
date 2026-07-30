"""Model-reachable legacy tools must enter the canonical action loop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openjarvis.server.agent_manager_routes import (
    _execute_exposed_tool_via_action_service,
)
from openjarvis.tasks import ExecutionLane, TaskService, TaskStore
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tools.action_service import RegisteredToolRuntime, ToolActionService
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.actions import VerificationResult
from openjarvis.tools.manifest import (
    IdempotencyPolicy,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
    ToolManifestCatalog,
)


def _service(tmp_path: Path, calls: list[str]) -> tuple[ToolActionService, TaskStore]:
    manifest = ToolManifest(
        tool_id="test.observe",
        name="test.observe",
        description="Read one synthetic value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        output_schema={"type": "object"},
        capability="test:observe",
        risk_level=RiskLevel.READ_ONLY,
        allowed_lanes=(ExecutionLane.MODEL,),
        supported_platforms=("windows", "linux", "darwin"),
        timeout=2,
        max_retries=0,
        idempotency_policy=IdempotencyPolicy.SAFE_RETRY,
        side_effect_class=SideEffectClass.LOCAL_READ,
        verification_strategy="compare the synthetic value",
        undo_strategy="no mutation",
        required_approval=False,
        network_policy=NetworkPolicy.DENY,
        secret_policy=SecretPolicy.REDACT,
        log_redaction_policy="redact all credentials",
    )
    task_store = TaskStore(tmp_path / "tasks.db")
    tasks = TaskService(task_store)
    context = ToolPolicyContext(
        granted_capabilities=frozenset({manifest.capability}),
        execution_lane=ExecutionLane.MODEL,
        requested_risk=RiskLevel.READ_ONLY,
        proposal_capability=manifest.capability,
        allowed_roots=(tmp_path,),
    )

    def handler(arguments):
        calls.append(arguments["value"])
        return {"value": arguments["value"]}

    service = ToolActionService(
        catalog=ToolManifestCatalog((manifest,)),
        store=ActionStore(tmp_path / "actions.db"),
        context_factory=lambda _proposal: context,
        runtimes={
            manifest.tool_id: RegisteredToolRuntime(
                handler=handler,
                verifier=lambda proposal, output: VerificationResult(
                    passed=output["value"] == proposal.arguments["value"],
                    observed_state=output["value"],
                    expected_state=proposal.arguments["value"],
                ),
            )
        },
        artifact_root=tmp_path / "artifacts",
        task_service=tasks,
    )
    return service, task_store


@pytest.mark.asyncio
async def test_managed_tool_routes_through_policy_verification_and_idempotency(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    service, task_store = _service(tmp_path, calls)
    state = SimpleNamespace(
        tool_action_service=service,
        task_service=service._tasks,
    )
    kwargs = {
        "app_state": state,
        "agent_id": "agent-test",
        "message_id": "message-test",
        "tool_call_id": "call-test",
        "tool_name": "test.observe",
        "tool_arguments": '{"value":"synthetic"}',
    }
    first = await _execute_exposed_tool_via_action_service(**kwargs)
    second = await _execute_exposed_tool_via_action_service(**kwargs)
    assert first.success is True
    assert second.success is True
    assert calls == ["synthetic"]
    task_id = state.task_service.list()[0].task_id
    action = service.store.list_actions(task_id)[0]
    assert action.verification_status.value == "passed"
    event_names = [
        event.event_type for event in service.store.list_events(action.action_id)
    ]
    assert event_names[-3:] == [
        "tool.verification_started",
        "tool.verified",
        "tool.completed",
    ]
    service.store.close()
    task_store.close()


@pytest.mark.asyncio
async def test_managed_tool_fails_closed_without_action_service() -> None:
    result = await _execute_exposed_tool_via_action_service(
        app_state=SimpleNamespace(),
        agent_id="agent-test",
        message_id="message-test",
        tool_call_id="call-test",
        tool_name="test.observe",
        tool_arguments="{}",
    )
    assert result.success is False
    assert "canonical action service" in result.content
