#!/usr/bin/env python3
"""M2 Test 3: Rich-context spec-level distillation.

Unlike M1 which ran the teacher against a mocked student and judge, this runs
a real distillation session with:

1. A real `student_runner` that invokes vLLM (so the teacher can verify its
   proposals empirically before committing them).
2. A real LLM judge (gpt-5-mini) scoring student output against reference
   answers.
3. Real benchmark samples loaded from the target benchmark (e.g., PinchBench).
4. Benchmark-specific context injected into the teacher's session prompt
   (benchmark name, scorer, agent, sample queries).

Hypothesis: when the teacher can observe actual student behavior at proposed
settings, it will AVOID the edits that caused M2's regression (e.g., the
temperature=0.2 tool-call format collapse).

Usage:
  python scripts/experiments/m2_test3_rich_context.py \\
    --teacher opus --student 9b --benchmark pinchbench --n-samples 8
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

import httpx

from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine
from openjarvis.learning.distillation.checkpoint.store import CheckpointStore
from openjarvis.learning.distillation.models import AutonomyMode
from openjarvis.learning.distillation.orchestrator import DistillationOrchestrator
from openjarvis.learning.distillation.storage.session_store import SessionStore
from openjarvis.learning.distillation.triggers import OnDemandTrigger
from openjarvis.traces.store import TraceStore


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark sample wrapper (matches what the orchestrator's tools expect)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class BenchmarkSample:
    """Duck-typed `PersonalBenchmarkSample` for diagnose tools."""
    trace_id: str
    query: str
    reference_answer: str
    category: str = "agentic"


# ═══════════════════════════════════════════════════════════════════════════
# Real student runner — invokes vLLM
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class StudentResult:
    content: str
    score: float
    trace_id: str
    latency_seconds: float
    tokens_used: int


class RealStudentRunner:
    """Calls vLLM and returns a duck-typed result for the diagnose tool."""

    def __init__(self, host: str, model: str, judge: Any, samples: List[BenchmarkSample]):
        self._host = host.rstrip("/")
        self._model = model
        self._judge = judge
        self._samples = {s.trace_id: s for s in samples}
        self._client = httpx.Client(base_url=self._host, timeout=600.0)

    def __call__(self, query: str, session_id: str = "") -> StudentResult:
        # Find the sample matching this query so we can score against reference
        sample = next(
            (s for s in self._samples.values() if s.query.strip()[:200] == query.strip()[:200]),
            None,
        )
        t0 = time.monotonic()
        try:
            resp = self._client.post(
                "/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": query}],
                    "temperature": 0.6,  # use benchmark's default, not the teacher's proposed value
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            tokens = (data.get("usage") or {}).get("total_tokens", 0)
        except Exception as e:
            return StudentResult(content=f"ERROR: {e}", score=0.0, trace_id="",
                                 latency_seconds=time.monotonic() - t0, tokens_used=0)
        elapsed = time.monotonic() - t0

        # Score via judge if we have a reference
        score = 0.0
        if sample is not None and sample.reference_answer:
            score, _ = self._judge.score_trace(
                type("TraceShim", (), {
                    "query": query,
                    "result": content,
                    "reference": sample.reference_answer,
                })()
            )

        return StudentResult(
            content=content,
            score=score,
            trace_id=f"test3-student-{session_id[:8]}",
            latency_seconds=elapsed,
            tokens_used=tokens,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Real LLM-as-judge
# ═══════════════════════════════════════════════════════════════════════════


class RealJudge:
    """Scores student output against a reference answer using Sonnet."""

    JUDGE_PROMPT = (
        "You are evaluating whether a student model's response correctly addresses the user's task.\n\n"
        "TASK:\n{query}\n\n"
        "REFERENCE ANSWER (expected behavior/outcome):\n{reference}\n\n"
        "STUDENT RESPONSE:\n{response}\n\n"
        "Score the student response from 0.0 to 1.0 on how well it accomplishes the task.\n"
        "Respond EXACTLY in this format:\n"
        "SCORE=<0.0 to 1.0>\n"
        "REASON=<one sentence>"
    )

    def __init__(self, engine: CloudEngine, model: str = "claude-sonnet-4-6"):
        self._engine = engine
        self._model = model

    def score_trace(self, trace: Any) -> tuple[float, str]:
        query = getattr(trace, "query", "") or ""
        response = getattr(trace, "result", "") or ""
        reference = getattr(trace, "reference", "") or ""
        if not reference:
            return 0.5, "no reference"
        prompt = self.JUDGE_PROMPT.format(
            query=query[:1000], reference=reference[:1000], response=response[:3000]
        )
        try:
            resp = self._engine.generate(
                messages=[Message(role=Role.USER, content=prompt)],
                model=self._model, max_tokens=100, temperature=0.0,
            )
            content = resp.get("content", "") or ""
            import re
            m = re.search(r"SCORE\s*=\s*(0?\.\d+|1\.0|1|0)", content)
            score = float(m.group(1)) if m else 0.5
            mr = re.search(r"REASON\s*=\s*(.+)$", content, re.DOTALL)
            reason = mr.group(1).strip()[:200] if mr else "(unparsed)"
            return score, reason
        except Exception as e:
            return 0.0, f"judge error: {e}"


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark sample loading
# ═══════════════════════════════════════════════════════════════════════════


def load_benchmark_samples(bench: str, n: int) -> tuple[List[BenchmarkSample], str]:
    """Load n samples for the given benchmark. Returns (samples, agent_name)."""
    if bench == "pinchbench":
        from openjarvis.evals.datasets.pinchbench import PinchBenchDataset
        ds = PinchBenchDataset()
        agent_name = "native_openhands"
    elif bench == "liveresearch":
        from openjarvis.evals.datasets.liveresearch import LiveResearchBenchDataset
        ds = LiveResearchBenchDataset()
        ds.load(max_samples=n)  # Explicit load required
        agent_name = "monitor_operative"
    elif bench == "gaia":
        from openjarvis.evals.datasets.gaia import GAIADataset
        ds = GAIADataset()
        if hasattr(ds, "load"):
            ds.load(max_samples=n)
        agent_name = "monitor_operative"
    else:
        raise ValueError(f"unknown benchmark: {bench}")
    records = list(ds.iter_records())[:n]
    samples = [
        BenchmarkSample(
            trace_id=r.record_id,
            query=r.problem,
            reference_answer=r.reference,
            category=getattr(r, "category", "agentic"),
        )
        for r in records
    ]
    return samples, agent_name


def benchmark_context_prompt(
    bench_name: str, agent_name: str, samples: List[BenchmarkSample]
) -> str:
    """Neutral benchmark-context prefix (no leading warnings about specific edits)."""
    sample_preview = "\n".join(
        f"- TASK {s.trace_id}: {s.query[:200]}..."
        for s in samples[:5]
    )
    return (
        f"# BENCHMARK CONTEXT\n\n"
        f"You are optimizing the OpenJarvis config for the **{bench_name}** benchmark.\n\n"
        f"## Target deployment\n"
        f"- Benchmark: `{bench_name}`\n"
        f"- Agent: `{agent_name}` (uses OpenAI-format structured tool calls)\n"
        f"- Student model: Qwen3.5 (served via vLLM)\n"
        f"- Scoring: an LLM judge compares the student's final output against the expected behavior\n\n"
        f"## Sample tasks from this benchmark\n{sample_preview}\n\n"
        f"## Empirical verification tools\n"
        f"You have `run_student_on_task` and `compare_outputs` — these actually execute the student "
        f"and score its output. Use them to empirically verify that any edit you propose "
        f"improves (or at least does not degrade) the student's performance on representative "
        f"tasks BEFORE committing the edit. A proposed edit without empirical verification is "
        f"higher risk than one that has been tested."
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


TEACHER_MODELS = {
    "opus": "claude-opus-4-6",
    "gpt54": "gpt-5.4",
    "gemini": "gemini-3.1-pro-preview",
}

STUDENT_PORTS = {"2b": 8000, "9b": 8001, "27b": 8002}
STUDENT_MODELS = {
    "2b": "Qwen/Qwen3.5-2B",
    "9b": "Qwen/Qwen3.5-9B",
    "27b": "Qwen/Qwen3.5-27B-FP8",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", default="opus", choices=list(TEACHER_MODELS))
    ap.add_argument("--student", default="9b", choices=list(STUDENT_PORTS))
    ap.add_argument("--benchmark", default="pinchbench",
                    choices=["pinchbench", "liveresearch", "gaia"])
    ap.add_argument("--n-samples", type=int, default=8)
    ap.add_argument("--max-cost", type=float, default=4.0)
    ap.add_argument("--out-dir",
                    default="results/neurips-2026/distillation-m2/test3")
    args = ap.parse_args()

    teacher_model = TEACHER_MODELS[args.teacher]
    student_model = STUDENT_MODELS[args.student]
    student_host = f"http://localhost:{STUDENT_PORTS[args.student]}"

    print(f"=== M2 Test 3: Rich-context distillation ===")
    print(f"teacher: {teacher_model}")
    print(f"student: {student_model} @ {student_host}")
    print(f"benchmark: {args.benchmark} ({args.n_samples} samples)")
    print(f"max_cost: ${args.max_cost}")

    # 1. Load real benchmark samples
    print(f"\nLoading {args.benchmark} samples...")
    samples, agent_name = load_benchmark_samples(args.benchmark, args.n_samples)
    print(f"  loaded {len(samples)} samples, agent={agent_name}")

    # 2. Real judge + real student runner
    teacher_engine = CloudEngine()
    judge = RealJudge(teacher_engine, model="claude-sonnet-4-6")
    student_runner = RealStudentRunner(student_host, student_model, judge, samples)

    # 3. Point at an isolated home for this test
    home = Path("/scratch/user/jonsaadfalcon/openjarvis-m2/test3-home")
    home.mkdir(parents=True, exist_ok=True)

    # Copy the M1 traces.db as input (so the teacher has trace data to analyze)
    src_db = Path("/scratch/user/jonsaadfalcon/openjarvis-m1/traces.db")
    dst_db = home / "traces.db"
    if not dst_db.exists() and src_db.exists():
        print(f"\nCopying traces.db from M1 home...")
        shutil.copy2(src_db, dst_db)
    (home / "learning").mkdir(exist_ok=True)

    trace_store = TraceStore(dst_db)
    session_store = SessionStore(home / "learning" / "learning.db")
    checkpoint_store = CheckpointStore(home)

    # 4. Write benchmark context as a file the teacher can read
    # (injected via system prompt; diagnose phase has a fixed prompt template we'd
    # need to modify, but we can also inject by using `get_current_config` override)
    bench_ctx = benchmark_context_prompt(args.benchmark, agent_name, samples)
    (home / "BENCHMARK_CONTEXT.md").write_text(bench_ctx)
    print(f"  wrote benchmark context to {home}/BENCHMARK_CONTEXT.md")

    # 5. Run the orchestrator with REAL components
    print(f"\nRunning distillation session...")
    t0 = time.time()
    orch = DistillationOrchestrator(
        teacher_engine=teacher_engine,
        teacher_model=teacher_model,
        trace_store=trace_store,
        benchmark_samples=samples,
        student_runner=student_runner,
        judge=judge,
        session_store=session_store,
        checkpoint_store=checkpoint_store,
        openjarvis_home=home,
        autonomy_mode=AutonomyMode.AUTO,
        scorer=None,
        min_traces=5,
        max_cost_usd=args.max_cost,
        max_tool_calls=30,
    )
    session = orch.run(OnDemandTrigger())
    elapsed = time.time() - t0

    # 6. Save results
    result = {
        "test": "m2_test3_rich_context",
        "teacher": teacher_model, "student": student_model, "benchmark": args.benchmark,
        "n_samples": len(samples), "elapsed_seconds": elapsed,
        "session_id": session.id, "status": session.status.value,
        "cost_usd": session.teacher_cost_usd,
        "edits_total": len(session.edit_outcomes),
        "edits_applied": len([o for o in session.edit_outcomes if o.status == "applied"]),
        "edits_rejected": len([o for o in session.edit_outcomes if o.status == "rejected_by_gate"]),
        "error": session.error,
    }

    out_dir = Path(args.out_dir) / f"{args.teacher}-{args.student}-{args.benchmark}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2))

    # Copy session artifacts
    sd = home / "learning" / "sessions" / session.id
    if sd.exists():
        shutil.copytree(sd, out_dir / "artifacts", dirs_exist_ok=True)

    print(f"\n=== Test 3 complete in {elapsed:.1f}s ===")
    print(json.dumps(result, indent=2))
    return 0 if session.status.value == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
