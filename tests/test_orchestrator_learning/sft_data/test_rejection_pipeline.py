"""Offline tests for the rejection-sampling SFT pipeline (unified tools)."""

from __future__ import annotations

import json

from openjarvis.agents.hybrid.expert_registry import orchestrator_catalog, tools_by_name
from openjarvis.agents.hybrid.toolorchestra.rollout import (
    UnifiedRollout,
    UnifiedTurn,
    run_unified_rollout,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.datasets import Task
from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.unified_serialize import (
    trajectory_to_record,
)


def test_run_unified_rollout_terminates_on_no_tool_call():
    tools = orchestrator_catalog()
    by = tools_by_name(tools)
    name = tools[0].name  # any real expert tool from the live catalog
    assert name in by

    scripted = [
        ("reason 1\n", [(name, {"input": "do step 1"})], 5, 5),
        ("here is the answer", [], 3, 3),  # no tool call -> terminate
    ]
    calls = iter(scripted)

    def call_orch(messages, specs):
        # Signature is now (messages, specs): the rollout drives a running
        # system/user/assistant/tool conversation, not a flattened (system, user).
        return next(calls)

    def dispatch(tool, args):
        return (f"OBS for {tool.name}", 0.01, 10, False)

    roll = run_unified_rollout(
        "What is X?",
        tools,
        call_orchestrator=call_orch,
        dispatch=dispatch,
        max_turns=5,
    )
    assert roll.final_answer == "here is the answer"
    assert roll.num_tool_calls == 1
    assert roll.tool_calls() == [(name, {"input": "do step 1"})]
    assert abs(roll.cost_usd - 0.01) < 1e-9


def test_serialize_record_shape_and_tool_call_tags():
    tools = orchestrator_catalog()
    roll = UnifiedRollout(
        turns=[
            UnifiedTurn(
                reasoning="think",
                tool_name="qwen3_32b",
                arguments={"input": "q"},
                observation="obs",
            ),
            # The final turn's reasoning IS the model's real final output (it
            # already contains the answer). The serializer now renders this turn
            # via _final_answer_block(turn.reasoning), not rollout.final_answer.
            UnifiedTurn(
                reasoning="The result is 42.\nFINAL_ANSWER: 42", tool_name=None
            ),
        ],
        final_answer="42",
        cost_usd=0.02,
        tokens=30,
        num_tool_calls=1,
    )
    rec = trajectory_to_record("t1", "Q?", tools, roll, reward=0.5, domain="math")
    roles = [m["role"] for m in rec["conversations"]]
    assert roles[0] == "system" and roles[1] == "user"
    assert "tool" in roles and roles[-1] == "assistant"
    # Tool call is emitted as a <tool_call> tag (what the parser reads back).
    assert any(
        "<tool_call>" in m["content"] and "qwen3_32b" in m["content"]
        for m in rec["conversations"]
        if m["role"] == "assistant"
    )
    assert "FINAL_ANSWER: 42" in rec["conversations"][-1]["content"]
    assert rec["reward"] == 0.5 and rec["domain"] == "math"


def test_generate_sft_dataset_end_to_end(tmp_path):
    tools = orchestrator_catalog()
    tasks = [
        Task(
            task_id="movie-001",
            question="Cancel ticket A03 and refund the user.",
            answer="refunded $20.90",
            domain="entertainment",
        ),
        Task(
            task_id="unsolvable",
            question="Cancel ticket A03 and refund the user.",
            answer="refunded $20.90",
            domain="entertainment",
        ),
    ]

    def rollout_fn(task):
        # Solve the first task; the second answers wrongly and never routes.
        if task.task_id == "movie-001":
            return UnifiedRollout(
                turns=[
                    UnifiedTurn("", "cancel", {"booking": "A03"}, "ok"),
                    UnifiedTurn("", "refund", {"user": "8612"}, "ok"),
                    UnifiedTurn("done", None),
                ],
                # num_tool_calls must reflect the two routed calls: the structural
                # _target_is_clean gate drops a trajectory with num_tool_calls < 1.
                final_answer="refunded $20.90",
                cost_usd=0.03,
                num_tool_calls=2,
            )
        return UnifiedRollout(
            turns=[UnifiedTurn("x", "cancel", {}, "ok")],
            final_answer="nope",
            cost_usd=0.05,
        )

    # Simple, meaningful verifier: the final answer must mention the refund.
    def verify_fn(task, rollout):
        return "refund" in (rollout.final_answer or "").lower()

    out = tmp_path / "sft.jsonl"
    stats = generate_sft_dataset(
        str(out),
        tasks=tasks,
        tools=tools,
        rollout_fn=rollout_fn,
        verify_fn=verify_fn,
        samples_per_task=2,
    )
    assert stats["tasks_seen"] == 2
    assert stats["records_written"] == 1  # only the solvable task
    assert stats["tasks_dropped"] == 1
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["task_id"] == "movie-001"
    assert rec["domain"] == "entertainment"
    assert (tmp_path / "sft.jsonl.stats.json").exists()
