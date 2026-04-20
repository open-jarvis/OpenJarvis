#!/usr/bin/env python3
"""M2: Create distilled eval configs from M1 consensus edits.

Generates 24 distilled configs (3 models × 8 benchmarks) by cloning
baseline configs and applying the consensus edits from M1. Also creates
4 missing baseline configs (livecodebench-qwen-9b, liveresearchbench-*).

Usage: python scripts/experiments/m2_create_distilled_configs.py
"""

from __future__ import annotations

from pathlib import Path

CONFIGS_DIR = Path("src/openjarvis/evals/configs")
M2_DIR = CONFIGS_DIR / "distillation" / "m2"

# ── Consensus values from M1 (1,131 edits) ──────────────────────────────
DISTILLED_TEMP = 0.2         # 84/134 votes (agent benchmarks only)
DISTILLED_MAX_TURNS = 15     # 56/125 votes (close: 25 had 49)
REMOVE_TOOLS = {"shell_exec", "http_request"}  # 13 + 6 votes

# ── Model specs ──────────────────────────────────────────────────────────
MODELS = {
    "2b":  {"name": "Qwen/Qwen3.5-2B",      "num_gpus": 1, "port": 8000},
    "9b":  {"name": "Qwen/Qwen3.5-9B",      "num_gpus": 1, "port": 8001},
    "27b": {"name": "Qwen/Qwen3.5-27B-FP8", "num_gpus": 1, "port": 8002},
}

# ── Benchmark specs ──────────────────────────────────────────────────────
# Each benchmark defines its baseline config and what changes in distilled.
BENCHMARKS = {
    "toolcall15": {
        "backend": "jarvis-direct",
        "baseline_temp": 0.0,
        "distilled_temp": 0.0,  # CONTROL: no change for coding
        "max_tokens": 4096,
        "max_samples": None,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "extra_benchmark_fields": {},
    },
    "pinchbench": {
        "backend": "jarvis-agent",
        "agent": "native_openhands",
        "baseline_temp": 0.6,
        "distilled_temp": DISTILLED_TEMP,
        "max_tokens": 8192,
        "max_samples": None,
        "judge_model": "claude-opus-4-5",
        "judge_engine": "cloud",
        "baseline_tools": [
            "think", "file_read", "file_write", "web_search", "shell_exec",
            "code_interpreter", "browser_navigate", "image_generate",
            "calculator", "http_request", "pdf_extract",
        ],
        "extra_benchmark_fields": {},
    },
    "taubench": {
        "backend": "jarvis-direct",
        "baseline_temp": 0.7,
        "distilled_temp": DISTILLED_TEMP,
        "max_tokens": 4096,
        "max_samples": 20,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "extra_benchmark_fields": {"split": "airline,retail"},
    },
    "taubench-telecom": {
        "benchmark_name": "taubench",  # same benchmark, different split
        "backend": "jarvis-direct",
        "baseline_temp": 0.7,
        "distilled_temp": DISTILLED_TEMP,
        "max_tokens": 4096,
        "max_samples": 20,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "extra_benchmark_fields": {"split": "telecom"},
    },
    "gaia": {
        "backend": "jarvis-agent",
        "agent": "monitor_operative",
        "baseline_temp": 0.6,
        "distilled_temp": DISTILLED_TEMP,
        "max_tokens": 8192,
        "max_samples": 50,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "baseline_tools": [
            "think", "calculator", "code_interpreter", "web_search", "file_read",
        ],
        "extra_benchmark_fields": {},
    },
    "liveresearch": {
        "backend": "jarvis-agent",
        "agent": "monitor_operative",
        "baseline_temp": 0.6,
        "distilled_temp": DISTILLED_TEMP,
        "max_tokens": 16384,
        "max_samples": 50,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "baseline_tools": [
            "web_search", "file_read", "file_write", "code_interpreter", "think",
        ],
        "extra_benchmark_fields": {},
    },
    "liveresearchbench": {
        "backend": "jarvis-direct",
        "baseline_temp": 0.0,
        "distilled_temp": 0.0,  # CONTROL: reasoning benchmark
        "max_tokens": 8192,
        "max_samples": 50,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "extra_benchmark_fields": {},
    },
    "livecodebench": {
        "backend": "jarvis-direct",
        "baseline_temp": 0.0,
        "distilled_temp": 0.0,  # CONTROL: coding benchmark
        "max_tokens": 4096,
        "max_samples": 20,
        "judge_model": "gpt-5-mini-2025-08-07",
        "judge_engine": "cloud",
        "extra_benchmark_fields": {},
    },
}


def render_config(
    *,
    comment: str,
    meta_name: str,
    description: str,
    temperature: float,
    max_tokens: int,
    judge_model: str,
    judge_engine: str,
    output_dir: str,
    model_name: str,
    model_engine: str,
    num_gpus: int,
    benchmark_name: str,
    backend: str,
    agent: str | None = None,
    tools: list[str] | None = None,
    max_samples: int | None = None,
    extra_benchmark: dict | None = None,
    seed: int = 42,
) -> str:
    lines = [f"# {comment}"]
    lines.append(f'[meta]\nname = "{meta_name}"\ndescription = "{description}"\n')
    lines.append(f"[defaults]\ntemperature = {temperature}\nmax_tokens = {max_tokens}\n")
    lines.append(f'[judge]\nmodel = "{judge_model}"\ntemperature = 0.0')
    if judge_engine:
        lines.append(f'engine = "{judge_engine}"')
    lines.append(f"max_tokens = 4096\n")
    lines.append(f'[run]\nmax_workers = 1\noutput_dir = "{output_dir}"\nseed = {seed}\n')
    lines.append(f'[[models]]\nname = "{model_name}"\nengine = "{model_engine}"\nnum_gpus = {num_gpus}\n')
    lines.append(f'[[benchmarks]]\nname = "{benchmark_name}"\nbackend = "{backend}"')
    if agent:
        lines.append(f'agent = "{agent}"')
    if max_samples:
        lines.append(f"max_samples = {max_samples}")
    if tools:
        tools_str = ", ".join(f'"{t}"' for t in tools)
        lines.append(f"tools = [{tools_str}]")
    if extra_benchmark:
        for k, v in extra_benchmark.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            else:
                lines.append(f"{k} = {v}")
    lines.append("")
    return "\n".join(lines)


def make_size_label(size: str) -> str:
    return {"2b": "qwen-2b", "9b": "qwen-9b", "27b": "qwen-27b"}[size]


def generate_missing_baselines() -> int:
    """Create baseline configs that don't exist yet."""
    count = 0

    # livecodebench-qwen-9b (missing)
    p = CONFIGS_DIR / "livecodebench-qwen-9b.toml"
    if not p.exists():
        b = BENCHMARKS["livecodebench"]
        m = MODELS["9b"]
        p.write_text(render_config(
            comment="LiveCodeBench eval: Qwen3.5-9B (vLLM, 1 GPU)",
            meta_name="livecodebench-qwen-9b",
            description="LiveCodeBench on Qwen/Qwen3.5-9B (vLLM, 1 GPU)",
            temperature=b["baseline_temp"],
            max_tokens=b["max_tokens"],
            judge_model=b["judge_model"],
            judge_engine=b["judge_engine"],
            output_dir="results/neurips-2026/baselines/qwen-9b/livecodebench/",
            model_name=m["name"], model_engine="vllm", num_gpus=m["num_gpus"],
            benchmark_name="livecodebench", backend=b["backend"],
            max_samples=b["max_samples"],
        ))
        count += 1
        print(f"  created {p}")

    # liveresearchbench-qwen-{2b,9b,27b}
    for size, m in MODELS.items():
        sl = make_size_label(size)
        p = CONFIGS_DIR / f"liveresearchbench-{sl}.toml"
        if not p.exists():
            b = BENCHMARKS["liveresearchbench"]
            p.write_text(render_config(
                comment=f"LiveResearchBench (Salesforce): Qwen3.5-{size.upper()} (vLLM)",
                meta_name=f"liveresearchbench-{sl}",
                description=f"LiveResearchBench on {m['name']} (vLLM)",
                temperature=b["baseline_temp"],
                max_tokens=b["max_tokens"],
                judge_model=b["judge_model"],
                judge_engine=b["judge_engine"],
                output_dir=f"results/neurips-2026/baselines/{sl}/liveresearchbench/",
                model_name=m["name"], model_engine="vllm", num_gpus=m["num_gpus"],
                benchmark_name="liveresearchbench", backend=b["backend"],
                max_samples=b["max_samples"],
            ))
            count += 1
            print(f"  created {p}")

    return count


def generate_distilled_configs() -> int:
    """Create distilled configs for all 24 model × benchmark combos."""
    M2_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    for size, model in MODELS.items():
        sl = make_size_label(size)
        for bench_key, bench in BENCHMARKS.items():
            bench_name = bench.get("benchmark_name", bench_key)
            is_agent = bench["backend"] == "jarvis-agent"
            temp = bench["distilled_temp"]

            # Tool list: remove broken tools for agent benchmarks
            tools = None
            if is_agent and "baseline_tools" in bench:
                tools = [t for t in bench["baseline_tools"]
                         if t not in REMOVE_TOOLS]

            fname = f"{bench_key}-{sl}-distilled.toml"
            out_path = M2_DIR / fname

            # Determine what changed for the comment
            changes = []
            if temp != bench["baseline_temp"]:
                changes.append(f"temp {bench['baseline_temp']}→{temp}")
            if tools and set(tools) != set(bench.get("baseline_tools", [])):
                removed = set(bench.get("baseline_tools", [])) - set(tools)
                changes.append(f"removed {removed}")
            if is_agent:
                changes.append(f"max_turns 10→{DISTILLED_MAX_TURNS} (via OPENJARVIS_CONFIG)")
            change_str = "; ".join(changes) if changes else "CONTROL (no change)"

            out_path.write_text(render_config(
                comment=f"M2 DISTILLED: {bench_key} × {model['name']} — {change_str}",
                meta_name=f"{bench_key}-{sl}-distilled",
                description=f"Distilled {bench_key} on {model['name']}",
                temperature=temp,
                max_tokens=bench["max_tokens"],
                judge_model=bench["judge_model"],
                judge_engine=bench["judge_engine"],
                output_dir=f"results/neurips-2026/distilled/{sl}/{bench_key}/",
                model_name=model["name"], model_engine="vllm", num_gpus=model["num_gpus"],
                benchmark_name=bench_name, backend=bench["backend"],
                agent=bench.get("agent"),
                tools=tools,
                max_samples=bench.get("max_samples"),
                extra_benchmark=bench.get("extra_benchmark_fields"),
            ))
            count += 1

    return count


if __name__ == "__main__":
    print("=== Creating missing baseline configs ===")
    n_base = generate_missing_baselines()
    print(f"Created {n_base} missing baseline configs\n")

    print("=== Creating distilled M2 configs ===")
    n_dist = generate_distilled_configs()
    print(f"Created {n_dist} distilled configs in {M2_DIR}/\n")

    # Summary
    print("=== Change matrix ===")
    print(f"{'Benchmark':20} {'Backend':14} {'Temp Δ':12} {'Tool Δ':20} {'max_turns Δ':12}")
    print("-" * 80)
    for bk, b in BENCHMARKS.items():
        is_agent = b["backend"] == "jarvis-agent"
        temp_change = f"{b['baseline_temp']}→{b['distilled_temp']}" if b["baseline_temp"] != b["distilled_temp"] else "—"
        tool_change = "—"
        if is_agent and "baseline_tools" in b:
            removed = REMOVE_TOOLS & set(b.get("baseline_tools", []))
            tool_change = f"-{removed}" if removed else "—"
        mt_change = f"10→{DISTILLED_MAX_TURNS}" if is_agent else "—"
        print(f"{bk:20} {b['backend']:14} {temp_change:12} {str(tool_change):20} {mt_change:12}")
