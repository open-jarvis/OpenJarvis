"""Offline smoke test for the v1 orchestrator-SFT driver (base self-sampling).

No network / no GPU: we feed fake ``datasets.Task`` objects, a canned
``UnifiedRollout`` (via a fake ``rollout_fn``), and an accept-all verifier, then
assert ``generate_sft_dataset`` writes a JSONL record in the expected
``conversations`` shape that the SFT trainer consumes.
"""

from __future__ import annotations

import json

from openjarvis.agents.hybrid.expert_registry import orchestrator_catalog
from openjarvis.agents.hybrid.toolorchestra.rollout import UnifiedRollout, UnifiedTurn
from openjarvis.learning.intelligence.orchestrator.sft_data.datasets import Task
from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    generate_sft_dataset,
)


def _fake_tasks() -> list[Task]:
    return [
        Task(task_id="t-math-1", question="What is 6 * 7?", answer="42", domain="math"),
        Task(task_id="t-code-1", question="Reverse 'ab'.", answer="ba", domain="code"),
    ]


def _canned_rollout(task: Task) -> UnifiedRollout:
    # One tool turn + a final-answer turn that echoes the gold answer.
    return UnifiedRollout(
        turns=[
            UnifiedTurn(reasoning="let me compute", tool_name="code_interpreter",
                        arguments={"code": "print(6*7)"}, observation="42"),
            UnifiedTurn(reasoning="that's the result", tool_name=None),
        ],
        final_answer=task.answer, cost_usd=0.01, tokens=20, num_tool_calls=1,
    )


def test_build_v1_writes_expected_conversations_shape(tmp_path, monkeypatch):
    tools = orchestrator_catalog()  # specialists unwired (math/coder endpoints None)

    # Accept-all verifier (the real make_verifier may hit Gemini / math checkers).
    monkeypatch.setattr(
        "openjarvis.learning.intelligence.orchestrator.sft_data.verify.make_verifier",
        lambda: (lambda task, rollout: True),
    )
    from openjarvis.learning.intelligence.orchestrator.sft_data.verify import (
        make_verifier,
    )

    out = tmp_path / "orchestrator_sft_v1.jsonl"
    stats = generate_sft_dataset(
        str(out),
        tasks=_fake_tasks(),
        tools=tools,
        rollout_fn=_canned_rollout,
        verify_fn=make_verifier(),
        samples_per_task=2,
        max_keep_per_task=1,
        reward_fn=lambda r: -r.cost_usd,
    )

    assert stats["tasks_seen"] == 2
    assert stats["records_written"] == 2
    assert stats["tasks_dropped"] == 0

    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2

    rec = json.loads(lines[0])
    assert rec["task_id"] == "t-math-1"
    assert rec["domain"] == "math"

    roles = [m["role"] for m in rec["conversations"]]
    assert roles[0] == "system" and roles[1] == "user"
    assert "tool" in roles
    assert roles[-1] == "assistant"
    # Tool call emitted as a <tool_call> tag the parser reads back.
    assert any(
        "<tool_call>" in m["content"] and "code_interpreter" in m["content"]
        for m in rec["conversations"]
        if m["role"] == "assistant"
    )
    assert "FINAL_ANSWER: 42" in rec["conversations"][-1]["content"]
    assert (tmp_path / "orchestrator_sft_v1.jsonl.stats.json").exists()


def _load_driver():
    """Load the (non-package) CLI driver module by path."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "orchestrator" / "build_orchestrator_sft.py"
    spec = importlib.util.spec_from_file_location("build_orchestrator_sft", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_driver_runs_end_to_end_with_fakes(tmp_path, monkeypatch):
    """Drive ``main`` with no network: fake task loader, rollout, and verifier."""
    drv = _load_driver()

    monkeypatch.setattr(drv, "load_sft_tasks", _fake_tasks)
    monkeypatch.setattr(drv, "run_unified_rollout",
                        lambda question, tools, **kw: _canned_rollout(_fake_tasks()[0]))
    monkeypatch.setattr(drv, "make_verifier", lambda: (lambda task, rollout: True))
    # make_call_orchestrator builds an OpenAI client lazily, so it never connects
    # here (run_unified_rollout is stubbed out).

    out = tmp_path / "v1.jsonl"
    rc = drv.main([
        "--out", str(out),
        "--samples-per-task", "1",
        "--max-tasks", "2",
    ])
    assert rc == 0
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["conversations"][0]["role"] == "system"
    assert "FINAL_ANSWER" in rec["conversations"][-1]["content"]
