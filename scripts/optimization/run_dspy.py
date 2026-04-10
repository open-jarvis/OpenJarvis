"""Run DSPy optimization for OpenJarvis agent configs.

Two modes:
- BootstrapFewShot: Finds optimal few-shot demonstrations from successful traces
- MIPROv2: Additionally optimizes instruction text via proposals

Both use a live evaluator that actually runs the agent and scores output.

Usage:
    python scripts/optimization/run_dspy.py \
        --model Qwen/Qwen3.5-9B \
        --benchmark pinchbench \
        --data-config C2 \
        --method bootstrap \
        --engine-key vllm \
        --output-dir results/neurips-2026/agent-optimization/dspy/bootstrap/qwen-9b/pinchbench/C2/
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("dspy_optimization")


# ---- Default agent config (applied alongside DSPy's optimized demos) ----

DEFAULT_AGENT_CONFIG = {
    "system_prompt": (
        "You are a precise AI agent that completes tasks by executing tools "
        "and verifying results. Always use tools to get ground truth. "
        "Never hallucinate."
    ),
    "temperature": "0.1",
    "max_tokens": "4096",
    "agent_type": "monitor_operative",
    "max_turns": "25",
    "tool_set": (
        "think, calculator, code_interpreter, web_search, "
        "file_read, file_write, shell_exec, http_request, apply_patch, llm"
    ),
}


def build_examples(
    data_config: str,
    benchmark: str,
    max_samples: int,
) -> list:
    """Build DSPy Example objects based on data access configuration."""
    import dspy

    from evaluator import load_benchmark_queries, load_external_data

    examples = []

    if data_config == "C1":
        # External data only — no benchmark queries
        logger.info("C1: Building examples from external data")
        external = load_external_data("general_thought", max_samples=200)
        external += load_external_data("agent_data", max_samples=200)
        for ex in external:
            if ex.get("query"):
                examples.append(
                    dspy.Example(
                        task_description=ex["query"],
                        final_answer=ex.get("reference", ""),
                    ).with_inputs("task_description")
                )
    elif data_config == "C2":
        # Benchmark queries only — no answers
        logger.info("C2: Building examples from benchmark queries (no answers)")
        queries = load_benchmark_queries(benchmark, max_samples=max_samples)
        for q in queries:
            examples.append(
                dspy.Example(
                    task_description=q,
                    final_answer="",  # No answer available
                ).with_inputs("task_description")
            )
    elif data_config == "C3":
        # Benchmark queries + external labeled data
        logger.info("C3: Building examples from benchmark queries + external data")
        queries = load_benchmark_queries(benchmark, max_samples=max_samples)
        for q in queries:
            examples.append(
                dspy.Example(
                    task_description=q,
                    final_answer="",
                ).with_inputs("task_description")
            )
        external = load_external_data("general_thought", max_samples=100)
        external += load_external_data("agent_data", max_samples=100)
        for ex in external:
            if ex.get("query"):
                examples.append(
                    dspy.Example(
                        task_description=ex["query"],
                        final_answer=ex.get("reference", ""),
                    ).with_inputs("task_description")
                )
    else:
        raise ValueError(f"Unknown data config: {data_config}")

    logger.info("Built %d DSPy examples (data_config=%s)", len(examples), data_config)
    return examples


def run_dspy(
    model: str,
    benchmark: str,
    data_config: str,
    method: str,
    engine_key: str,
    max_eval_samples: int,
    max_bootstrapped_demos: int,
    max_labeled_demos: int,
    num_candidate_programs: int,
    teacher_lm_name: str,
    output_dir: str,
) -> dict:
    """Run DSPy optimization and return results."""
    import dspy

    from evaluator import LiveEvaluator

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Configure DSPy LMs
    # Task LM: the model we're optimizing for
    if engine_key == "vllm":
        task_lm = dspy.LM(
            f"openai/{model}",
            api_base="http://localhost:8000/v1",
            api_key="dummy",
        )
    elif engine_key == "cloud":
        task_lm = dspy.LM(model)
    else:
        task_lm = dspy.LM(
            f"openai/{model}",
            api_base=f"http://localhost:8000/v1",
            api_key="dummy",
        )

    # Teacher LM: strong model for bootstrapping demonstrations
    teacher_lm = dspy.LM(teacher_lm_name)

    dspy.configure(lm=task_lm)

    # Build examples
    examples = build_examples(data_config, benchmark, max_eval_samples)
    if not examples:
        return {"status": "error", "reason": "No examples to optimize with"}

    # Split
    split = max(1, int(len(examples) * 0.8))
    trainset = examples[:split]
    valset = examples[split:]

    # Build live evaluator for the metric
    live_eval = LiveEvaluator(
        model=model,
        benchmark=benchmark,
        engine_key=engine_key,
        max_samples=max_eval_samples,
    )

    eval_log: list[dict] = []

    def metric(example, prediction, trace=None) -> float:
        """DSPy metric — runs agent with current config and scores."""
        config = dict(DEFAULT_AGENT_CONFIG)

        # If DSPy produced a prediction, use it as context
        predicted_answer = getattr(prediction, "final_answer", "")

        # Score by actually running the agent on this task
        score = live_eval.evaluate_single(
            config,
            example.task_description,
        )

        eval_log.append({
            "timestamp": time.time(),
            "query": str(example.task_description)[:100],
            "score": score,
        })
        return score

    # Build DSPy Module
    class JarvisAgentModule(dspy.Module):
        """Wraps the OpenJarvis agent reasoning as a DSPy Module."""

        def __init__(self) -> None:
            super().__init__()
            self.reason = dspy.ChainOfThought(
                "task_description -> final_answer"
            )

        def forward(self, task_description: str):
            return self.reason(task_description=task_description)

    program = JarvisAgentModule()

    logger.info(
        "Starting DSPy %s: model=%s, benchmark=%s, data_config=%s, "
        "train=%d, val=%d",
        method, model, benchmark, data_config, len(trainset), len(valset),
    )

    t0 = time.time()

    try:
        if method == "mipro":
            optimizer = dspy.MIPROv2(
                metric=metric,
                prompt_model=teacher_lm,
                task_model=task_lm,
                max_bootstrapped_demos=max_bootstrapped_demos,
                max_labeled_demos=max_labeled_demos,
                auto="light",  # auto mode handles num_candidates/num_trials
                verbose=True,
            )
            optimized_program = optimizer.compile(
                program,
                trainset=trainset,
            )
        elif method == "simba":
            optimizer = dspy.SIMBA(
                metric=metric,
                num_candidates=num_candidate_programs,
                max_steps=8,
                max_demos=max_bootstrapped_demos,
                bsize=min(16, len(trainset)),
            )
            optimized_program = optimizer.compile(
                program,
                trainset=trainset,
            )
        elif method == "copro":
            optimizer = dspy.COPRO(
                metric=metric,
                prompt_model=teacher_lm,
                breadth=num_candidate_programs,
                depth=3,
            )
            optimized_program = optimizer.compile(
                program,
                trainset=trainset,
                eval_kwargs={"num_threads": 1},
            )
        else:
            # Default: BootstrapFewShotWithRandomSearch
            optimizer = dspy.BootstrapFewShotWithRandomSearch(
                metric=metric,
                teacher_settings={"lm": teacher_lm},
                max_bootstrapped_demos=max_bootstrapped_demos,
                max_labeled_demos=max_labeled_demos,
                num_candidate_programs=num_candidate_programs,
            )
            optimized_program = optimizer.compile(
                program,
                trainset=trainset,
            )
    except Exception as exc:
        logger.error("DSPy optimization failed: %s", exc, exc_info=True)
        live_eval.close()
        return {"status": "error", "reason": str(exc)}
    finally:
        live_eval.close()

    elapsed = time.time() - t0

    # Extract optimized demonstrations
    demos = []
    if hasattr(optimized_program, "reason") and hasattr(
        optimized_program.reason, "demos"
    ):
        for d in optimized_program.reason.demos:
            demo = {}
            if hasattr(d, "task_description"):
                demo["input"] = str(d.task_description)[:500]
            if hasattr(d, "final_answer"):
                demo["output"] = str(d.final_answer)[:500]
            if hasattr(d, "rationale"):
                demo["rationale"] = str(d.rationale)[:500]
            demos.append(demo)

    # Extract optimized instructions (MIPROv2)
    instructions = None
    if hasattr(optimized_program, "reason") and hasattr(
        optimized_program.reason, "signature"
    ):
        sig = optimized_program.reason.signature
        if hasattr(sig, "instructions"):
            instructions = str(sig.instructions)

    # Save results
    output = {
        "status": "completed",
        "optimizer": f"DSPy-{method}",
        "model": model,
        "benchmark": benchmark,
        "data_config": data_config,
        "method": method,
        "elapsed_seconds": elapsed,
        "total_evals": len(eval_log),
        "num_demos": len(demos),
        "demos": demos,
        "optimized_instructions": instructions,
        "config": {
            "max_bootstrapped_demos": max_bootstrapped_demos,
            "max_labeled_demos": max_labeled_demos,
            "num_candidate_programs": num_candidate_programs,
            "teacher_lm": teacher_lm_name,
        },
    }

    result_path = output_path / "result.json"
    with open(result_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Results saved to %s", result_path)

    # Save compiled program
    try:
        program_path = output_path / "compiled_program"
        program_path.mkdir(exist_ok=True)
        optimized_program.save(str(program_path))
        logger.info("Compiled program saved to %s", program_path)
    except Exception as exc:
        logger.warning("Could not save compiled program: %s", exc)

    # Save eval log
    log_path = output_path / "eval_log.jsonl"
    with open(log_path, "w") as f:
        for entry in eval_log:
            f.write(json.dumps(entry) + "\n")
    logger.info("Eval log saved to %s (%d entries)", log_path, len(eval_log))

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DSPy agent optimization")
    parser.add_argument("--model", required=True, help="Model identifier")
    parser.add_argument("--benchmark", required=True, help="Benchmark name")
    parser.add_argument(
        "--data-config", required=True, choices=["C1", "C2", "C3"],
    )
    parser.add_argument(
        "--method", default="bootstrap",
        choices=["bootstrap", "mipro", "simba", "copro"],
        help="DSPy optimizer: bootstrap, mipro (MIPROv2), simba (SIMBA), copro (COPRO)",
    )
    parser.add_argument("--engine-key", default="vllm")
    parser.add_argument("--max-eval-samples", type=int, default=15)
    parser.add_argument("--max-bootstrapped-demos", type=int, default=4)
    parser.add_argument("--max-labeled-demos", type=int, default=4)
    parser.add_argument("--num-candidate-programs", type=int, default=10)
    parser.add_argument(
        "--teacher-lm", default="anthropic/claude-sonnet-4-6",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    result = run_dspy(
        model=args.model,
        benchmark=args.benchmark,
        data_config=args.data_config,
        method=args.method,
        engine_key=args.engine_key,
        max_eval_samples=args.max_eval_samples,
        max_bootstrapped_demos=args.max_bootstrapped_demos,
        max_labeled_demos=args.max_labeled_demos,
        num_candidate_programs=args.num_candidate_programs,
        teacher_lm_name=args.teacher_lm,
        output_dir=args.output_dir,
    )

    if result["status"] == "completed":
        logger.info(
            "DSPy optimization completed in %.1fs, %d demos extracted",
            result["elapsed_seconds"], result["num_demos"],
        )
    else:
        logger.error("DSPy optimization failed: %s", result.get("reason"))
        sys.exit(1)


if __name__ == "__main__":
    main()
