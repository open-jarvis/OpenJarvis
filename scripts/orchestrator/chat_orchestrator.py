#!/usr/bin/env python
"""Interactive REPL to chat with a trained orchestrator checkpoint.

Reuses the SAME routing loop the eval uses (OrchestratorBackend.generate_full),
so what you see here is exactly how it behaves on the benchmarks: it reads your
question, decides whether to answer itself / call a tool / delegate to an expert
model, runs that rollout, and prints the final answer + a routing summary.

Prereqs:
  1. Serve the checkpoint you want on a vLLM port (see --endpoint). e.g. 8k:
       PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True CUDA_VISIBLE_DEVICES=0 \
       .venv/bin/python -m vllm.entrypoints.openai.api_server \
           --model "$OJ_WORK/qwen_eval_ckpts/8k_served" \
           --served-model-name sft-qwen-8k --port 8020 \
           --gpu-memory-utilization 0.88 --trust-remote-code --max-model-len 32768 \
           --enforce-eager --enable-auto-tool-choice --tool-call-parser qwen3_xml
  2. source .env         (cloud experts GPT-5.5 / Opus need the API keys)

Usage:
  .venv/bin/python scripts/orchestrator/chat_orchestrator.py \
      --endpoint http://localhost:8020/v1 --model sft-qwen-8k

  # point local expert tiers at their own vLLMs if you have them up (optional):
  #   --local-endpoint Qwen/Qwen3.6-27B=http://localhost:8002/v1
"""

import argparse
import sys
import time


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--endpoint",
        default="http://localhost:8020/v1",
        help="vLLM endpoint serving the orchestrator checkpoint.",
    )
    p.add_argument(
        "--model", default="sft-qwen-8k", help="Served-model-name of the checkpoint."
    )
    p.add_argument(
        "--api-key",
        default="EMPTY",
        help="API key for the endpoint (local vLLM = EMPTY).",
    )
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-turns", type=int, default=8, help="Same default as the eval.")
    p.add_argument(
        "--max-tokens",
        type=int,
        default=3000,
        help="Keep high: the model reasons a lot before it emits the delegation.",
    )
    p.add_argument(
        "--local-endpoint",
        action="append",
        default=[],
        help="MODEL_ID=URL for a local expert tier. Repeatable.",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    local_endpoints = {}
    for pair in args.local_endpoint:
        if "=" not in pair:
            raise SystemExit(f"--local-endpoint expects MODEL_ID=URL, got: {pair!r}")
        mid, url = pair.split("=", 1)
        local_endpoints[mid.strip()] = url.strip()

    from openjarvis.learning.intelligence.orchestrator.eval_backend import (
        OrchestratorBackend,
    )

    backend = OrchestratorBackend(
        orchestrator_endpoint=args.endpoint,
        orchestrator_model=args.model,
        api_key=args.api_key,
        local_endpoints=local_endpoints,
        max_turns=args.max_turns,
        temperature=args.temperature,
    )

    print(
        f"orchestrator: {args.model} @ {args.endpoint}  "
        f"(temp={args.temperature}, max_turns={args.max_turns})"
    )
    print("type a question and hit enter. Ctrl-D or 'quit' to exit.\n")

    try:
        while True:
            try:
                prompt = input("you> ").strip()
            except EOFError:
                print()
                break
            if not prompt:
                continue
            if prompt.lower() in {"quit", "exit"}:
                break

            started = time.time()
            full = backend.generate_full(
                prompt,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            elapsed = time.time() - started

            if full.get("error"):
                print(f"\n[ERROR] {full['error']}\n", file=sys.stderr)
                continue

            print(f"\norch> {full.get('content', '').strip()}\n")
            print(
                f"  [turns={full.get('turn_count', '?')} "
                f"tool_calls={full.get('tool_calls', '?')} "
                f"cost=${full.get('cost_usd', 0.0):.4f} "
                f"{elapsed:.1f}s]\n"
            )
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
