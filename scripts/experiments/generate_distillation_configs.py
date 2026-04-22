#!/usr/bin/env python3
"""Generate all distillation experiment TOML configs.

Produces configs for 7 experiment axes × multiple settings.
Run: python scripts/experiments/generate_distillation_configs.py
"""

from __future__ import annotations

import itertools
from pathlib import Path

CONFIGS_DIR = Path("src/openjarvis/evals/configs/distillation")

# ── Teacher models ──────────────────────────────────────────────────────────
TEACHERS = {
    "opus": {
        "model": "claude-opus-4-6",
        "engine": "cloud",
        "provider": "anthropic",
    },
    "gpt54": {
        "model": "gpt-5.4",
        "engine": "cloud",
        "provider": "openai",
    },
    "gemini": {
        "model": "gemini-3.1-pro-preview",
        "engine": "cloud",
        "provider": "google",
    },
    "qwen397b": {
        "model": "Qwen/Qwen3.5-397B-A17B-FP8",
        "engine": "vllm",
        "provider": "local",
        "note": "# Requires 8×H100, vLLM serve on port 8010",
    },
}

# ── Student models ──────────────────────────────────────────────────────────
# Served via vLLM on this H100 node. 27B uses the FP8 weights that fit on a
# single H100; 2B and 9B use standard FP16.
STUDENTS = {
    "2b":  {"model": "Qwen/Qwen3.5-2B",      "engine": "vllm", "port": 8000},
    "9b":  {"model": "Qwen/Qwen3.5-9B",      "engine": "vllm", "port": 8001},
    "27b": {"model": "Qwen/Qwen3.5-27B-FP8", "engine": "vllm", "port": 8002},
}

# ── Benchmarks ──────────────────────────────────────────────────────────────
BENCHMARKS = {
    "pb": "pinchbench",
    "tc15": "toolcall15",
    "tb": "taubench",
}

# ── Data configs ────────────────────────────────────────────────────────────
DATA_CONFIGS = {
    "C1": {
        "desc": "Zero test data — external traces only (GeneralThought + ADP)",
        "trace_source": "external",
        "benchmark_queries_visible": False,
    },
    "C2": {
        "desc": "Test queries only — benchmark traces visible, answers hidden",
        "trace_source": "benchmark",
        "benchmark_queries_visible": True,
    },
    "C3": {
        "desc": "Test queries + external — both benchmark and external traces",
        "trace_source": "both",
        "benchmark_queries_visible": True,
    },
}

# ── Budget presets ──────────────────────────────────────────────────────────
BUDGETS = {
    "minimal": {"max_tool_calls": 5, "max_cost": 0.50},
    "standard": {"max_tool_calls": 15, "max_cost": 2.00},
    "thorough": {"max_tool_calls": 30, "max_cost": 5.00},
    "exhaustive": {"max_tool_calls": 50, "max_cost": 10.00},
}

# ── Gate presets ────────────────────────────────────────────────────────────
GATES = {
    "permissive": {"min_improvement": 0.0, "max_regression": 0.10},
    "standard": {"min_improvement": 0.0, "max_regression": 0.05},
    "strict": {"min_improvement": 0.02, "max_regression": 0.02},
    "none": {"min_improvement": -1.0, "max_regression": 1.0},
}

# ── Autonomy presets ────────────────────────────────────────────────────────
AUTONOMY_MODES = ["auto", "tiered", "manual"]


def render_config(
    *,
    experiment: str,
    teacher_key: str,
    student_key: str,
    benchmark_key: str,
    data_config_key: str = "C2",
    budget_key: str = "standard",
    gate_key: str = "standard",
    autonomy: str = "auto",
    iterative_sessions: int = 1,
) -> str:
    """Render a TOML config string."""
    teacher = TEACHERS[teacher_key]
    student = STUDENTS[student_key]
    benchmark = BENCHMARKS[benchmark_key]
    data_cfg = DATA_CONFIGS[data_config_key]
    budget = BUDGETS[budget_key]
    gate = GATES[gate_key]

    note = teacher.get("note", "")
    note_line = f"\n{note}" if note else ""

    return f"""\
# Distillation Experiment Config
# Experiment: {experiment}
# Teacher: {teacher["model"]} ({teacher["provider"]})
# Student: {student["model"]} ({student["engine"]})
# Benchmark: {benchmark}
# Data config: {data_config_key} — {data_cfg["desc"]}
# Budget: {budget_key} ({budget["max_tool_calls"]} tool calls, ${budget["max_cost"]:.2f})
# Gate: {gate_key} (min_improvement={gate["min_improvement"]}, max_regression={gate["max_regression"]})
# Autonomy: {autonomy}
# Iterative sessions: {iterative_sessions}
{note_line}

[intelligence]
default_model = "{student["model"]}"

[engine]
default = "{student["engine"]}"

[engine.vllm]
host = "http://localhost:{student.get("port", 8000)}"

[learning.distillation]
enabled = true
autonomy_mode = "{autonomy}"
teacher_model = "{teacher["model"]}"
max_cost_per_session_usd = {budget["max_cost"]}
max_tool_calls_per_diagnosis = {budget["max_tool_calls"]}

[learning.distillation.gate]
min_improvement = {gate["min_improvement"]}
max_regression = {gate["max_regression"]}
benchmark_subsample_size = 50

[learning.distillation.benchmark]
synthesis_feedback_threshold = 0.7
max_benchmark_size = 200

[learning.distillation.experiment]
# Metadata for the experiment runner (not read by distillation itself)
experiment_id = "{experiment}"
teacher_key = "{teacher_key}"
student_key = "{student_key}"
benchmark = "{benchmark}"
data_config = "{data_config_key}"
trace_source = "{data_cfg["trace_source"]}"
benchmark_queries_visible = {str(data_cfg["benchmark_queries_visible"]).lower()}
budget_key = "{budget_key}"
gate_key = "{gate_key}"
iterative_sessions = {iterative_sessions}
"""


def write_config(subdir: str, filename: str, content: str) -> Path:
    path = CONFIGS_DIR / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def generate_all() -> int:
    count = 0

    # ── Exp 1a: Teacher Model Ablation ────────────────────────────────────
    # Fix: S-9b, B-standard, A-auto, G-standard, I-single
    # Vary: teacher × benchmark × data_config
    for teacher_key, bench_key, dc_key in itertools.product(
        TEACHERS, BENCHMARKS, DATA_CONFIGS
    ):
        filename = f"{teacher_key}-9b-{bench_key}-{dc_key}.toml"
        content = render_config(
            experiment=f"exp1a-teacher/{teacher_key}-{bench_key}-{dc_key}",
            teacher_key=teacher_key,
            student_key="9b",
            benchmark_key=bench_key,
            data_config_key=dc_key,
        )
        write_config("exp1a-teacher", filename, content)
        count += 1

    # ── Exp 1b: Budget Ablation ───────────────────────────────────────────
    # Fix: S-9b, T-sonnet(opus for quality), A-auto, G-standard, I-single
    # Vary: budget × benchmark × data_config
    for budget_key, bench_key, dc_key in itertools.product(
        BUDGETS, BENCHMARKS, DATA_CONFIGS
    ):
        filename = f"{budget_key}-9b-{bench_key}-{dc_key}.toml"
        content = render_config(
            experiment=f"exp1b-budget/{budget_key}-{bench_key}-{dc_key}",
            teacher_key="opus",
            student_key="9b",
            benchmark_key=bench_key,
            data_config_key=dc_key,
            budget_key=budget_key,
        )
        write_config("exp1b-budget", filename, content)
        count += 1

    # ── Exp 1c: Student Model Scaling ─────────────────────────────────────
    # Fix: T-opus, B-standard, A-auto, G-standard, I-single
    # Vary: student × benchmark × data_config
    for student_key, bench_key, dc_key in itertools.product(
        STUDENTS, BENCHMARKS, DATA_CONFIGS
    ):
        filename = f"opus-{student_key}-{bench_key}-{dc_key}.toml"
        content = render_config(
            experiment=f"exp1c-student/opus-{student_key}-{bench_key}-{dc_key}",
            teacher_key="opus",
            student_key=student_key,
            benchmark_key=bench_key,
            data_config_key=dc_key,
        )
        write_config("exp1c-student", filename, content)
        count += 1

    # ── Exp 2a: Gate Strictness ───────────────────────────────────────────
    # Fix: S-9b, T-opus, B-standard, A-auto, I-single
    # Vary: gate × benchmark
    for gate_key, bench_key in itertools.product(GATES, BENCHMARKS):
        filename = f"{gate_key}-9b-{bench_key}.toml"
        content = render_config(
            experiment=f"exp2a-gate/{gate_key}-{bench_key}",
            teacher_key="opus",
            student_key="9b",
            benchmark_key=bench_key,
            gate_key=gate_key,
        )
        write_config("exp2a-gate", filename, content)
        count += 1

    # ── Exp 2b: Autonomy Mode ────────────────────────────────────────────
    # Fix: S-9b, T-opus, B-standard, G-standard, I-single
    # Vary: autonomy × benchmark
    for autonomy, bench_key in itertools.product(AUTONOMY_MODES, BENCHMARKS):
        filename = f"{autonomy}-9b-{bench_key}.toml"
        content = render_config(
            experiment=f"exp2b-autonomy/{autonomy}-{bench_key}",
            teacher_key="opus",
            student_key="9b",
            benchmark_key=bench_key,
            autonomy=autonomy,
        )
        write_config("exp2b-autonomy", filename, content)
        count += 1

    # ── Exp 3a: Iterative Sessions ───────────────────────────────────────
    # Fix: S-9b, T-opus, B-standard, A-auto, G-standard
    # Vary: number of chained sessions × benchmark
    for n_sessions, bench_key in itertools.product([1, 3, 5], BENCHMARKS):
        filename = f"iter{n_sessions}-9b-{bench_key}.toml"
        content = render_config(
            experiment=f"exp3a-iterative/iter{n_sessions}-{bench_key}",
            teacher_key="opus",
            student_key="9b",
            benchmark_key=bench_key,
            iterative_sessions=n_sessions,
        )
        write_config("exp3a-iterative", filename, content)
        count += 1

    # ── Exp 3b: Cross-Benchmark Transfer ─────────────────────────────────
    # Optimize using traces from benchmark X, eval on benchmark Y
    for opt_bench, eval_bench in itertools.permutations(BENCHMARKS, 2):
        filename = f"opt-{opt_bench}-eval-{eval_bench}-9b.toml"
        content = render_config(
            experiment=f"exp3b-transfer/opt-{opt_bench}-eval-{eval_bench}",
            teacher_key="opus",
            student_key="9b",
            benchmark_key=opt_bench,  # Traces from this benchmark
        )
        # Add eval benchmark as metadata
        content += f'\neval_benchmark = "{BENCHMARKS[eval_bench]}"\n'
        write_config("exp3b-transfer", filename, content)
        count += 1

    return count


if __name__ == "__main__":
    n = generate_all()
    print(f"Generated {n} config files in {CONFIGS_DIR}/")

    # Print summary
    for subdir in sorted(CONFIGS_DIR.iterdir()):
        if subdir.is_dir():
            files = list(subdir.glob("*.toml"))
            print(f"  {subdir.name}/: {len(files)} configs")
