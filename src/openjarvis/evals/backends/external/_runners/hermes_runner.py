"""Subprocess bridge: runs one task through real Hermes Agent and emits JSON.

Invoked as:
    python hermes_runner.py \\
        --task <prompt> --model <m> --base-url <url> --api-key <k> \\
        --api-mode <mode> --output-json <path> [--workspace <path>] \\
        [--max-iterations 90] [--system-prompt <s>]

Imports `AIAgent` from `run_agent` (the top-level module Hermes ships
at the path indicated by `HERMES_AGENT_PATH`, set by the calling
backend). Writes a JSON dict matching the `_RunnerOutput` schema in
`_subprocess_runner.py` to `--output-json` before exiting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--api-mode", default="chat_completions")
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--workspace", default="")
    parser.add_argument("--max-iterations", type=int, default=90)
    parser.add_argument("--system-prompt", default="")
    args = parser.parse_args()

    output: dict = {
        "content": "",
        "usage": {},
        "trajectory": [],
        "tool_calls": 0,
        "turn_count": 0,
        "error": None,
    }

    hermes_path = os.environ.get("HERMES_AGENT_PATH")
    if not hermes_path:
        output["error"] = "HERMES_AGENT_PATH not set"
        args.output_json.write_text(json.dumps(output))
        return 2

    sys.path.insert(0, hermes_path)
    if args.workspace:
        os.chdir(args.workspace)

    try:
        from run_agent import AIAgent  # type: ignore[import-not-found]
    except ImportError as e:
        output["error"] = f"hermes_import_failed: {e}"
        args.output_json.write_text(json.dumps(output))
        return 3

    try:
        agent = AIAgent(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            api_mode=args.api_mode,
            max_iterations=args.max_iterations,
            quiet_mode=True,
            save_trajectories=True,
            platform="openjarvis-eval",
        )
        kwargs = {}
        if args.system_prompt:
            kwargs["system_message"] = args.system_prompt
        result = agent.run_conversation(args.task, **kwargs)

        # Validate that Hermes returned the expected keys; if not, capture
        # what we actually got so debugging isn't a guessing game.
        if not isinstance(result, dict):
            output["error"] = (
                f"hermes_returned_non_dict: type={type(result).__name__}, "
                f"value={str(result)[:200]}"
            )
            args.output_json.write_text(json.dumps(output))
            return 0
        expected_keys = {"final_response", "messages"}
        if not (expected_keys & set(result.keys())):
            output["error"] = (
                f"hermes_returned_unexpected_shape: keys={list(result.keys())}"
            )
            args.output_json.write_text(json.dumps(output))
            return 0

        # Hermes returns {"final_response": str, "messages": [dict, ...]}.
        # Extract usage by summing per-turn assistant message usage if
        # present.
        messages = result.get("messages", [])
        prompt_tokens = sum(
            m.get("usage", {}).get("prompt_tokens", 0) for m in messages
        )
        completion_tokens = sum(
            m.get("usage", {}).get("completion_tokens", 0) for m in messages
        )
        tool_calls = sum(len(m.get("tool_calls", []) or []) for m in messages)
        turn_count = sum(1 for m in messages if m.get("role") == "assistant")

        output.update(
            {
                "content": result.get("final_response", ""),
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                "trajectory": messages,
                "tool_calls": tool_calls,
                "turn_count": turn_count,
                "error": None,
            }
        )
    except Exception as e:
        output["error"] = f"hermes_runtime_error: {e}"
        output["trajectory"] = [{"traceback": traceback.format_exc()}]

    args.output_json.write_text(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
