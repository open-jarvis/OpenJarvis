"""Run GEPA evolutionary optimization for OpenJarvis agent configs.

Evolves the full seed_candidate dict (system_prompt, temperature, agent_type,
tool_set, max_turns, etc.) using GEPA's population-based search with a
reflection LM that analyzes failures and proposes targeted mutations.

Usage:
    python scripts/optimization/run_gepa.py \
        --model Qwen/Qwen3.5-9B \
        --benchmark pinchbench \
        --data-config C2 \
        --engine-key vllm \
        --max-metric-calls 100 \
        --output-dir results/neurips-2026/agent-optimization/gepa/qwen-9b/pinchbench/C2/
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("gepa_optimization")

# ---- Default seed candidate ----

DEFAULT_SEED = {
    # Intelligence
    "system_prompt": (
        "You are a precise AI agent that completes tasks by executing tools "
        "and verifying results.\n\n"
        "CORE PRINCIPLES:\n"
        "1. EXECUTE, DON'T ASSUME: Always use tools to get ground truth. "
        "Never hallucinate file contents, command outputs, or API responses.\n"
        "2. PLAN FIRST: Use the 'think' tool to plan before acting. "
        "Break complex tasks into sequential tool calls.\n"
        "3. VERIFY: After each tool call, check the output. If a call fails "
        "or returns unexpected results, diagnose and retry.\n"
        "4. ARGUMENT PRECISION: For tool-call tasks, treat argument formatting "
        "as the primary success criterion. Copy argument names and values "
        "PRECISELY as specified.\n"
        "5. NEVER SKIP TOOLS: If a task involves files, shell commands, or "
        "external data — the tool call is mandatory, not optional."
    ),
    "temperature": "0.1",
    "max_tokens": "4096",
    "top_p": "0.9",
    "repetition_penalty": "1.0",
    # Agent
    "agent_type": "monitor_operative",
    "max_turns": "25",
    # Tools
    "tool_set": (
        "think, calculator, code_interpreter, web_search, "
        "file_read, file_write, shell_exec, http_request, apply_patch, llm"
    ),
    "tool_choice": "auto",
    # Context
    "context_top_k": "5",
    "context_max_tokens": "2048",
    # Loop guard
    "max_identical_calls": "3",
    "ping_pong_window": "6",
}


def build_dataset_for_config(
    data_config: str,
    benchmark: str,
    max_samples: int,
) -> tuple[list[dict], list[dict]]:
    """Build train/val datasets based on data access configuration.

    Returns (trainset, valset) where each element is a dict that GEPA
    passes to the evaluator.
    """
    from evaluator import load_benchmark_queries, load_external_data

    if data_config == "C1":
        # Zero test data — external data only
        logger.info("C1: Loading external data (no benchmark queries)")
        external = load_external_data("general_thought", max_samples=200)
        external += load_external_data("agent_data", max_samples=200)
        dataset = [{"query": ex["query"]} for ex in external if ex["query"]]
    elif data_config == "C2":
        # Queries only — benchmark queries, no answers
        logger.info("C2: Loading benchmark queries (no answers)")
        queries = load_benchmark_queries(benchmark, max_samples=max_samples)
        dataset = [{"query": q} for q in queries]
    elif data_config == "C3":
        # Queries + external
        logger.info("C3: Loading benchmark queries + external data")
        queries = load_benchmark_queries(benchmark, max_samples=max_samples)
        external = load_external_data("general_thought", max_samples=100)
        external += load_external_data("agent_data", max_samples=100)
        dataset = [{"query": q} for q in queries]
        dataset += [{"query": ex["query"]} for ex in external if ex["query"]]
    else:
        raise ValueError(f"Unknown data config: {data_config}")

    # Split: first 20% as valset
    split = max(1, len(dataset) // 5)
    valset = dataset[:split]
    trainset = dataset[split:]

    logger.info(
        "Dataset: %d train, %d val (data_config=%s)",
        len(trainset), len(valset), data_config,
    )
    return trainset, valset


def run_gepa(
    model: str,
    benchmark: str,
    data_config: str,
    engine_key: str,
    max_metric_calls: int,
    population_size: int,
    reflection_lm: str,
    max_eval_samples: int,
    output_dir: str,
    seed_candidate: dict | None = None,
) -> dict:
    """Run GEPA optimization and return results."""
    from gepa.optimize_anything import GEPAConfig, optimize_anything

    from evaluator import LiveEvaluator

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    seed = seed_candidate or dict(DEFAULT_SEED)

    # Build dataset
    trainset, valset = build_dataset_for_config(
        data_config, benchmark, max_eval_samples,
    )

    # Build live evaluator
    live_eval = LiveEvaluator(
        model=model,
        benchmark=benchmark,
        engine_key=engine_key,
        max_samples=max_eval_samples,
    )

    # Track all evaluations for analysis
    eval_log: list[dict] = []

    def gepa_evaluator(candidate: dict | str, example: dict) -> float:
        """GEPA evaluator — runs agent with candidate config, returns score."""
        if isinstance(candidate, str):
            # GEPA may pass just the text being evolved; wrap it
            config = dict(seed)
            config["system_prompt"] = candidate
        else:
            config = candidate

        score = live_eval.evaluate_single(config, example.get("query", ""))

        eval_log.append({
            "timestamp": time.time(),
            "query": example.get("query", "")[:100],
            "score": score,
            "candidate_hash": hash(str(candidate)) % 100000,
        })
        return score

    # Configure GEPA
    config = GEPAConfig()
    config.engine.max_metric_calls = max_metric_calls
    config.engine.population_size = population_size
    config.engine.display_progress_bar = True
    config.reflection.reflection_lm = reflection_lm

    # Describe the optimization objective with full context
    objective = (
        f"Maximize agent accuracy on the '{benchmark}' benchmark. "
        f"The agent uses model '{model}' (frozen weights) and executes tools "
        f"to complete tasks. Config fields control:\n"
        f"- system_prompt: The agent's core instructions\n"
        f"- temperature/top_p: Sampling parameters (lower = more deterministic)\n"
        f"- agent_type: Architecture (monitor_operative, native_react, native_openhands)\n"
        f"- max_turns: Reasoning budget (more turns = more tool calls allowed)\n"
        f"- tool_set: Comma-separated list of available tools\n"
        f"- tool_choice: auto (model decides) vs required (must use tools) vs none\n"
        f"- context_top_k/context_max_tokens: Memory retrieval parameters\n"
        f"- max_identical_calls/ping_pong_window: Loop detection thresholds"
    )

    background = (
        "OpenJarvis is a local-first AI agent framework. Agents complete tasks "
        "by calling tools (think, calculator, code_interpreter, web_search, "
        "file_read, file_write, shell_exec, http_request, apply_patch, llm). "
        "Scores are 0 (wrong) or 1 (correct). Higher accuracy is better. "
        "The system_prompt is the most impactful field — it controls the "
        "agent's behavior, tool usage patterns, and error handling."
    )

    logger.info(
        "Starting GEPA: model=%s, benchmark=%s, data_config=%s, "
        "max_calls=%d, population=%d",
        model, benchmark, data_config, max_metric_calls, population_size,
    )

    t0 = time.time()

    try:
        result = optimize_anything(
            seed_candidate=seed,
            evaluator=gepa_evaluator,
            dataset=trainset,
            valset=valset,
            objective=objective,
            background=background,
            config=config,
        )
    except Exception as exc:
        logger.error("GEPA failed: %s", exc, exc_info=True)
        live_eval.close()
        return {"status": "error", "reason": str(exc)}
    finally:
        live_eval.close()

    elapsed = time.time() - t0

    # Extract best candidate
    if hasattr(result, "best_candidate"):
        best = result.best_candidate
    elif isinstance(result, dict):
        best = result
    else:
        best = str(result)

    # Save results
    output = {
        "status": "completed",
        "optimizer": "GEPA",
        "model": model,
        "benchmark": benchmark,
        "data_config": data_config,
        "max_metric_calls": max_metric_calls,
        "population_size": population_size,
        "reflection_lm": reflection_lm,
        "elapsed_seconds": elapsed,
        "total_evals": len(eval_log),
        "best_candidate": best if isinstance(best, (dict, str)) else str(best),
        "seed_candidate": seed,
    }

    result_path = output_path / "result.json"
    with open(result_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Results saved to %s", result_path)

    # Save eval log
    log_path = output_path / "eval_log.jsonl"
    with open(log_path, "w") as f:
        for entry in eval_log:
            f.write(json.dumps(entry) + "\n")
    logger.info("Eval log saved to %s (%d entries)", log_path, len(eval_log))

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GEPA agent optimization")
    parser.add_argument("--model", required=True, help="Model identifier")
    parser.add_argument("--benchmark", required=True, help="Benchmark name")
    parser.add_argument(
        "--data-config", required=True, choices=["C1", "C2", "C3"],
        help="Data access config: C1=external only, C2=queries only, C3=queries+external",
    )
    parser.add_argument("--engine-key", default="vllm", help="Engine backend")
    parser.add_argument("--max-metric-calls", type=int, default=100)
    parser.add_argument("--population-size", type=int, default=5)
    parser.add_argument(
        "--reflection-lm", default="anthropic/claude-sonnet-4-6",
        help="LM for GEPA reflection step",
    )
    parser.add_argument("--max-eval-samples", type=int, default=15)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    result = run_gepa(
        model=args.model,
        benchmark=args.benchmark,
        data_config=args.data_config,
        engine_key=args.engine_key,
        max_metric_calls=args.max_metric_calls,
        population_size=args.population_size,
        reflection_lm=args.reflection_lm,
        max_eval_samples=args.max_eval_samples,
        output_dir=args.output_dir,
    )

    if result["status"] == "completed":
        logger.info("GEPA optimization completed in %.1fs", result["elapsed_seconds"])
    else:
        logger.error("GEPA optimization failed: %s", result.get("reason"))
        sys.exit(1)


if __name__ == "__main__":
    main()
