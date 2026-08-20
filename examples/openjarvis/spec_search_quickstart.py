"""LLM-Guided Spec Search — runnable quickstart.

This script wires up every primitive ``SpecSearchOrchestrator`` needs and runs
one full session, then a multi-session loop with the paper's stagnation rule
(Algorithm 1, k=5, epsilon=1%).

It is *self-contained*: by default the teacher engine and the student runner
are local fakes, so you can ``python examples/openjarvis/spec_search_quickstart.py``
with no API keys and no Ollama / vLLM running. Every "swap this for production"
hookpoint is called out inline.

Configuration is read from ``configs/openjarvis/examples/spec-search-quickstart.toml``
via the regular ``openjarvis.core.config.load_config`` machinery — you can copy
that TOML to ``~/.openjarvis/config.toml`` and tune the gate / stagnation /
reward knobs without editing this file.

Run:

    OPENJARVIS_HOME=/tmp/openjarvis-spec-search-demo \\
        python examples/openjarvis/spec_search_quickstart.py
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from openjarvis.core.config import SpecSearchLearningConfig
from openjarvis.learning.spec_search.composite_reward import (
    RewardWeights,
    TrainingSample,
    score_batch,
)
from openjarvis.learning.spec_search.models import (
    BenchmarkSnapshot,
    FailureCluster,
)
from openjarvis.learning.spec_search.multi_session import SpecSearchLoop
from openjarvis.learning.spec_search.orchestrator import SpecSearchOrchestrator
from openjarvis.learning.spec_search.triggers import OnDemandTrigger

# ---------------------------------------------------------------------------
# Fakes — replace these with real production components.
# ---------------------------------------------------------------------------


@dataclass
class FakeTeacherEngine:
    """Stand-in for ``CloudEngine``.

    For production, use the registry::

        from openjarvis.core.registry import EngineRegistry
        engine_cls = EngineRegistry.get(cfg.teacher_engine)  # "cloud"
        engine = engine_cls(model=cfg.teacher_model)         # set ANTHROPIC_API_KEY

    The orchestrator only calls ``engine.generate(...)`` so any object with
    that method will work.
    """

    call_count: int = 0

    def generate(self, **_: Any) -> dict[str, Any]:
        self.call_count += 1
        # Propose one auto-tier Tools edit so the gate has something to score.
        return {
            "content": json.dumps(
                {
                    "edits": [
                        {
                            "id": f"edit-{self.call_count:03d}",
                            "pillar": "tools",
                            "op": "edit_tool_description",
                            "target": "tools.web_search",
                            "payload": {
                                "tool_name": "web_search",
                                "new_description": (
                                    "Search the web for recent information. "
                                    "Prefer this for time-sensitive queries."
                                ),
                            },
                            "rationale": (
                                "Student under-invokes web_search on multi-hop queries."
                            ),
                            "expected_improvement": "c1",
                            "risk_tier": "auto",
                            "references": ["t-001"],
                        }
                    ]
                }
            ),
            "usage": {"total_tokens": 1200},
            "cost_usd": 0.04,
            "finish_reason": "stop",
        }


def _fake_diagnosis() -> Any:
    """A canned DiagnosisResult so the demo doesn't need a real teacher loop."""
    from openjarvis.learning.spec_search.diagnose.runner import DiagnosisResult

    return DiagnosisResult(
        diagnosis_md=(
            "## Diagnosis\n\n"
            "Cluster `c1` (multi-hop research): student fails to invoke "
            "`web_search` on time-sensitive queries; teacher invokes it "
            "consistently. Likely cause: tool description does not signal "
            "freshness."
        ),
        clusters=[
            FailureCluster(
                id="c1",
                description="Multi-hop research; web_search under-invocation",
                sample_trace_ids=["t-001", "t-002", "t-003"],
                student_failure_rate=0.7,
                teacher_success_rate=0.95,
                skill_gap="Student does not invoke web_search on multi-hop research.",
            )
        ],
        cost_usd=0.05,
        tool_call_records=[],
    )


def _fake_scorer_factory(start_score: float = 0.60, step: float = 0.06):
    """Return a scorer whose overall score climbs by ``step`` on each call.

    Mimics the loop the paper describes: each accepted edit lifts the gate
    score, and the multi-session loop stops once gains plateau.
    """
    state = {"score": start_score - step, "calls": 0}

    def scorer(**_: Any) -> BenchmarkSnapshot:
        state["calls"] += 1
        # Every other call (the "after" snapshot) bumps the score; gain
        # tapers after 3 sessions so the stagnation rule fires.
        if state["calls"] % 2 == 0:
            bump = step if state["calls"] // 2 <= 3 else 0.0
            state["score"] = min(1.0, state["score"] + bump)
        return BenchmarkSnapshot(
            benchmark_version="personal_v1",
            overall_score=state["score"],
            cluster_scores={"c1": state["score"]},
            task_count=10,
            elapsed_seconds=5.0,
        )

    return scorer


# ---------------------------------------------------------------------------
# Wire-up
# ---------------------------------------------------------------------------


def build_orchestrator(
    config: SpecSearchLearningConfig,
    home: Path,
) -> SpecSearchOrchestrator:
    """Construct a SpecSearchOrchestrator from a SpecSearchLearningConfig.

    All five injected primitives below are demo fakes; the comments next to
    each one show the production replacement.
    """
    return SpecSearchOrchestrator.from_config(
        config,
        # Teacher: replace with EngineRegistry.get("cloud")(model=cfg.teacher_model)
        teacher_engine=FakeTeacherEngine(),
        # TraceStore: production = TraceStore(home / "traces.db")
        trace_store=MagicMock(count=MagicMock(return_value=config.min_traces + 10)),
        benchmark_samples=[],
        # StudentRunner: production = VLLMStudentRunner(host=..., model=...)
        student_runner=MagicMock(),
        # Judge: production = openjarvis.evals.core.scorer.LLMJudgeScorer(...)
        judge=MagicMock(),
        # SessionStore + CheckpointStore: production = real on-disk stores
        session_store=MagicMock(),
        checkpoint_store=MagicMock(
            current_sha=MagicMock(return_value="demo-sha"),
            begin_stage=MagicMock(
                return_value=MagicMock(pre_stage_sha="demo-sha"),
            ),
        ),
        openjarvis_home=home,
        scorer=_fake_scorer_factory(),
    )


def demo_composite_reward(weights: RewardWeights) -> None:
    """Show how the paper Eq. 1 reward ranks Intelligence-edit candidates."""
    candidates = [
        TrainingSample(
            accuracy=1.0, energy_joules=200, latency_seconds=5.0, cost_usd=0.0
        ),
        TrainingSample(
            accuracy=1.0, energy_joules=400, latency_seconds=8.0, cost_usd=0.0
        ),
        TrainingSample(
            accuracy=0.0, energy_joules=100, latency_seconds=2.0, cost_usd=0.0
        ),
    ]
    rewards = score_batch(candidates, weights=weights)
    print("\nComposite reward (paper Eq. 1) — ranking 3 candidates:")
    print(
        f"  weights = (alpha={weights.alpha}, beta={weights.beta}, "
        f"gamma={weights.gamma}, delta={weights.delta})"
    )
    for i, (c, r) in enumerate(zip(candidates, rewards)):
        print(
            f"  candidate {i}: acc={c.accuracy} energy={c.energy_joules}J "
            f"latency={c.latency_seconds}s -> reward={r:+.3f}"
        )


def main() -> None:
    # In a real deployment, ``load_config()`` reads from ``~/.openjarvis/config.toml``.
    # For a self-contained demo we synthesize the spec-search config inline so the
    # script is runnable without copying any files. To use the prebuilt TOML:
    #
    #     from openjarvis.core.config import load_config
    #     cfg = load_config().learning.spec_search
    #
    # (after copying ``configs/openjarvis/examples/spec-search-quickstart.toml``
    # to ``~/.openjarvis/config.toml``)

    cfg = SpecSearchLearningConfig(
        enabled=True,
        teacher_model="claude-opus-4-6",
        teacher_engine="cloud",
        autonomy_mode="auto",
        min_traces=20,
        max_cost_per_session_usd=5.0,
        max_tool_calls_per_diagnosis=30,
        stagnation_k=5,  # paper default
        stagnation_eps=0.001,
        max_total_cost_usd=50.0,
        max_regression=0.01,  # paper default: epsilon = 1%
        min_improvement=0.0,
        benchmark_subsample_size=10,
    )

    home = Path(
        os.environ.get("OPENJARVIS_HOME")
        or tempfile.mkdtemp(prefix="openjarvis-spec-search-")
    )
    print(f"OPENJARVIS_HOME = {home}")

    # ----- Single session ---------------------------------------------------
    orch = build_orchestrator(cfg, home)

    # The orchestrator's diagnose phase calls a real DiagnosisRunner that
    # invokes the teacher. We swap it out for the canned diagnosis above so
    # the demo does not need an API key.
    from unittest.mock import patch

    print("\n=== Single session (one diagnose / plan / execute / record) ===")
    with patch(
        "openjarvis.learning.spec_search.orchestrator.DiagnosisRunner"
    ) as MockDiag:
        MockDiag.return_value.run.return_value = _fake_diagnosis()
        session = orch.run(OnDemandTrigger())

    print(f"  status = {session.status.value}")
    print(f"  teacher_cost_usd = ${session.teacher_cost_usd:.4f}")
    print(f"  edit_outcomes = {[(o.edit_id, o.status) for o in session.edit_outcomes]}")
    if session.benchmark_after is not None:
        print(
            f"  before -> after = "
            f"{session.benchmark_before.overall_score:.3f} -> "
            f"{session.benchmark_after.overall_score:.3f}"
        )

    # ----- Multi-session loop (paper Algorithm 1) ---------------------------
    orch = build_orchestrator(cfg, home)  # fresh fakes for clean state
    loop = SpecSearchLoop(
        orch,
        stagnation_k=cfg.stagnation_k,
        stagnation_eps=cfg.stagnation_eps,
        max_total_cost_usd=cfg.max_total_cost_usd,
    )

    print(
        "\n=== Multi-session loop (stagnation_k = "
        f"{cfg.stagnation_k}, max_total_cost = ${cfg.max_total_cost_usd}) ==="
    )
    with patch(
        "openjarvis.learning.spec_search.orchestrator.DiagnosisRunner"
    ) as MockDiag:
        MockDiag.return_value.run.return_value = _fake_diagnosis()
        result = loop.run()

    print(f"  sessions       = {len(result.sessions)}")
    print(f"  stop_reason    = {result.stop_reason}")
    print(f"  total cost     = ${result.total_cost_usd:.4f}")
    print(f"  best score     = {result.best_overall_score:.3f}")

    demo_composite_reward(RewardWeights())


if __name__ == "__main__":
    main()
