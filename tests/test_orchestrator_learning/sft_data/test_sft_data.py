"""Offline tests for the orchestrator SFT cold-start pipeline (no network/GPU).

Covers: ADP transcription -> canonical Episode, difficulty/tier heuristics,
paradigm rendering, reward-ranked selection, serialization round-trip, and the
end-to-end builder via an injected fixture source.
"""

from __future__ import annotations

import json
from pathlib import Path

from openjarvis.learning.intelligence.orchestrator.sft_data.adp_loader import (
    trajectory_rows_to_episode,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.build import (
    build_sft_dataset,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.paradigms import (
    PARADIGMS,
    render_all,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.select import select_best
from openjarvis.learning.intelligence.orchestrator.sft_data.serialize import to_record
from openjarvis.learning.intelligence.orchestrator.sft_data.tiers import (
    Difficulty,
    Tier,
    covers,
    min_covering_tier,
    step_difficulty,
    tier_telemetry,
)
from openjarvis.learning.intelligence.orchestrator.types import Episode

# --- fixtures ---------------------------------------------------------------

_EASY_TURNS = [
    {"source": "user", "class_": "message_action", "content": "What is 2 + 2?"},
    {"source": "agent", "class_": "message_action", "content": "The answer is 4."},
]

_CODE_TURNS = [
    {
        "source": "user",
        "class_": "message_action",
        "content": "Sort this list in Python.",
    },
    {"source": "agent", "class_": "code_action", "content": "sorted([3, 1, 2])"},
    {"source": "user", "class_": "message_action", "content": "[1, 2, 3]"},
    {"source": "agent", "class_": "message_action", "content": "Sorted: [1, 2, 3]"},
]


def _easy_episode() -> Episode:
    ep = trajectory_rows_to_episode("easy-1", _EASY_TURNS)
    assert ep is not None
    return ep


def _code_episode() -> Episode:
    ep = trajectory_rows_to_episode("code-1", _CODE_TURNS)
    assert ep is not None
    return ep


# --- adp_loader -------------------------------------------------------------


def test_transcribe_keeps_all_steps_and_problem():
    ep = _code_episode()
    assert ep.initial_prompt == "Sort this list in Python."
    assert ep.num_turns() == 2  # two agent turns
    assert ep.steps[0].action.tool_name == "code"
    assert ep.steps[-1].action.is_final_answer is True
    assert ep.correct is True  # ADP rows are demonstrated solutions


def test_transcribe_rejects_empty():
    assert trajectory_rows_to_episode("x", []) is None
    assert trajectory_rows_to_episode("x", [{"source": "user", "content": ""}]) is None


# --- tiers ------------------------------------------------------------------


def test_difficulty_heuristic():
    assert step_difficulty("message", "short") == Difficulty.EASY
    assert step_difficulty("code", "sorted([])") == Difficulty.MED
    assert step_difficulty("message", "x", retry_signal=True) == Difficulty.HARD


def test_min_covering_tier_and_covers():
    assert min_covering_tier(Difficulty.EASY) == Tier.LOCAL
    assert min_covering_tier(Difficulty.MED) == Tier.MID
    assert covers(Tier.FRONTIER, Difficulty.HARD)
    assert not covers(Tier.LOCAL, Difficulty.HARD)


def test_tier_telemetry_local_is_free_cloud_costs():
    assert tier_telemetry("local")["cost_usd"] == 0.0
    assert tier_telemetry("frontier")["cost_usd"] > 0.0
    local_e = tier_telemetry("local")["energy_joules"]
    mid_e = tier_telemetry("mid")["energy_joules"]
    assert local_e > mid_e


# --- paradigms --------------------------------------------------------------


def test_render_all_covers_every_paradigm():
    rendered = render_all(_code_episode())
    assert {r.paradigm for r in rendered} == set(PARADIGMS)


def test_baseline_local_incorrect_on_code_task():
    rendered = {r.paradigm: r for r in render_all(_code_episode())}
    # code step is MED -> local can't cover it
    assert rendered["baseline_local"].predicted_correct is False
    assert rendered["baseline_cloud"].predicted_correct is True
    assert rendered["toolorchestra"].predicted_correct is True


def test_toolorchestra_escalates_code_step():
    rendered = {r.paradigm: r for r in render_all(_code_episode())}
    tiers = rendered["toolorchestra"].step_tiers
    assert tiers[0] == "mid"  # code step escalated off local
    assert rendered["baseline_local"].step_tiers[0] == "local"


# --- select -----------------------------------------------------------------


def test_select_prefers_local_on_easy_task():
    best = select_best(render_all(_easy_episode()))
    assert best is not None
    # all-easy -> baseline_local is cheapest-correct
    assert best.paradigm == "baseline_local"


def test_select_drops_unsolved_task():
    ep = _easy_episode()
    # force every paradigm to be predicted-incorrect
    renderings = render_all(ep)
    for r in renderings:
        r.predicted_correct = False
    assert select_best(renderings) is None


# --- serialize --------------------------------------------------------------


def test_serialize_schema_and_final_answer():
    best = select_best(render_all(_code_episode()))
    assert best is not None
    rec = to_record(best, reward=0.5)
    convo = rec["conversations"]
    assert convo[0]["role"] == "system"
    assert convo[1]["role"] == "user"
    assert any(
        c["role"] == "assistant" and "FINAL_ANSWER:" in c["content"] for c in convo
    )
    assert rec["paradigm"] == best.paradigm
    assert rec["metrics"]["num_steps"] == best.episode.num_turns()


# --- build (end-to-end, injected source) ------------------------------------


def test_build_sft_dataset_end_to_end(tmp_path: Path):
    def fake_source(*, max_tasks=None, configs=None):
        yield _easy_episode()
        yield _code_episode()

    out = tmp_path / "traces.jsonl"
    stats = build_sft_dataset(str(out), max_tasks=10, source=fake_source)

    assert stats["records_written"] == 2
    assert stats["tasks_seen"] == 2
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert rec["conversations"][0]["role"] == "system"

    stats_file = out.with_suffix(out.suffix + ".stats.json")
    assert stats_file.exists()
    assert sum(stats["paradigm_distribution"].values()) == 2
