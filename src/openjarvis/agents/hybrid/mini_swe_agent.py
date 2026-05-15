"""MiniSWEAgent — vendored, ~150-line port of mini-SWE-agent v2.

Single-LLM agent loop with a ``bash`` tool, run inside a per-task git
clone. The model iterates: read files, grep, run tests, edit, retry —
exactly the environment-interaction loop that turns SWE-bench from
"predict the patch blind" (~0.30) into "actually fix the bug" (~0.77 for
frontier models).

Differences vs. the upstream
(https://github.com/swe-agent/mini-swe-agent):

- No Docker sandbox. We clone the SWE-bench repo into a tempdir and
  exec bash there. Network is available (pip etc.). Treat outputs as
  untrusted — model can run ``rm -rf`` against its own workdir, but the
  workdir is disposable. Don't run this on a host with secrets in the
  CWD.
- One tool, ``bash``. No separate ``submit`` — the loop ends when the
  model produces a turn with no tool calls. We extract the patch from
  ``git diff`` in the workdir at that point.
- Trace events captured via :func:`LocalCloudAgent.record_trace_event`
  so every bash invocation + result lands in
  ``experiments/<cell>/logs/<task_id>.json``.

Use as a standalone agent (default cell config), or wire as the worker
inside Minions/Conductor (see task #13 in branch TODOs).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent
from openjarvis.agents.hybrid._prices import (
    is_gpt5_family,
    supports_temperature,
)
from openjarvis.core.registry import AgentRegistry


SYSTEM_PROMPT = """\
You are an expert software engineer fixing a bug in a Python repository. \
You have one tool, `bash`, that runs a shell command and returns stdout, \
stderr, and the exit code.

Your task:
1. Read the issue.
2. Use `bash` to explore the repo, read relevant files, and understand the bug.
3. Edit files to fix the bug. You can use `bash` for that too (sed, python -c '...', cat > file <<EOF, etc.).
4. Run the relevant tests with `bash` to confirm your fix.
5. When you are confident the bug is fixed, send one final assistant message \
WITH NO TOOL CALLS containing a brief one-line summary of what you changed. \
That ends the loop; the harness will read your changes via `git diff` against \
the base commit.

Rules:
- Each `bash` call already runs INSIDE the repository's working tree as cwd. \
You do NOT need to `cd` anywhere — just run `ls`, `cat path/to/file`, etc. \
relative to the repo root.
- Each `bash` call is a fresh shell — there's no persistent cwd, env, or \
shell state carried between calls (but cwd is reset to the repo root each \
call, so this is fine for normal exploration).
- Don't run `git commit`, `git stash`, or anything that mutates git state — \
your edits should live in the working tree so `git diff` picks them up.
- Keep individual command outputs under ~10K chars (use `head`, `tail`, \
`grep -n`, `wc`). Long outputs will be truncated.
- Don't ``exit``, ``logout``, or kill the shell.
"""

BASH_TOOL_ANTHROPIC = {
    "name": "bash",
    "description": (
        "Run a bash command in the repository root and return stdout, stderr, "
        "and the exit code. Each call is a fresh shell — no persistent state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to run.",
            },
        },
        "required": ["command"],
    },
}

BASH_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": BASH_TOOL_ANTHROPIC["description"],
        "parameters": BASH_TOOL_ANTHROPIC["input_schema"],
    },
}


def _clone_repo(repo: str, base_commit: str, dest: Path) -> None:
    """Shallow-fetch the SWE-bench repo at the right commit into ``dest``."""
    url = f"https://github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)],
        check=True, timeout=300, capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", base_commit],
        cwd=str(dest), check=True, timeout=120, capture_output=True,
    )


def _run_bash(
    command: str, workdir: Path, *, timeout: int = 120, output_cap: int = 10_000
) -> Dict[str, Any]:
    """Run one shell command in ``workdir``. Returns dict with stdout, stderr,
    exit_code, and a ``truncated`` flag if output was clamped."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(workdir),
            capture_output=True, text=True, timeout=timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
        stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
        exit_code = -1
        timed_out = True
    truncated = False
    if len(stdout) > output_cap:
        stdout = stdout[:output_cap] + f"\n…[+{len(stdout) - output_cap} chars truncated]"
        truncated = True
    if len(stderr) > output_cap:
        stderr = stderr[:output_cap] + f"\n…[+{len(stderr) - output_cap} chars truncated]"
        truncated = True
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "truncated": truncated,
        "latency_s": time.time() - t0,
    }


def _format_observation(result: Dict[str, Any]) -> str:
    parts = [f"exit_code: {result['exit_code']}"]
    if result.get("timed_out"):
        parts.append("[TIMED OUT]")
    if result.get("truncated"):
        parts.append("[output truncated]")
    if result["stdout"]:
        parts.append(f"--- stdout ---\n{result['stdout']}")
    if result["stderr"]:
        parts.append(f"--- stderr ---\n{result['stderr']}")
    return "\n".join(parts)


def _extract_diff(workdir: Path) -> str:
    """``git diff`` against the base commit — the final SWE-bench patch."""
    proc = subprocess.run(
        ["git", "diff", "--no-color"],
        cwd=str(workdir), capture_output=True, text=True, timeout=60,
    )
    return proc.stdout


@AgentRegistry.register("mini_swe_agent")
class MiniSWEAgent(LocalCloudAgent):
    """Single-model bash-loop agent for SWE-bench-shaped tasks.

    Configurable knobs via ``cfg``:

    - ``backbone`` (str, default ``"cloud"``): ``"cloud"`` to drive the
      loop with the cloud model, ``"local"`` for the vLLM-served local
      model. Tool-calling on vLLM requires ``--enable-auto-tool-choice``
      with a parser (e.g. ``qwen3_xml`` for Qwen3.5).
    - ``max_turns`` (int, default 50): hard cap on tool turns.
    - ``bash_timeout_s`` (int, default 120): per-command timeout.
    - ``output_cap`` (int, default 10_000): per-command stdout/stderr cap.
    """

    agent_id = "mini_swe_agent"

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        task: Dict[str, Any] = {}
        if context is not None:
            task = context.metadata.get("task") or {}
        repo = task.get("repo") or ""
        base_commit = task.get("base_commit") or ""
        if not repo or not base_commit:
            raise ValueError(
                "MiniSWEAgent needs task['repo'] and task['base_commit'] in "
                "context.metadata. Got: "
                f"repo={repo!r}, base_commit={base_commit!r}"
            )

        max_turns = int(cfg.get("max_turns", 50))
        bash_timeout = int(cfg.get("bash_timeout_s", 120))
        output_cap = int(cfg.get("output_cap", 10_000))
        backbone = cfg.get("backbone", "cloud")

        workdir = Path(tempfile.mkdtemp(prefix=f"mini-swe-{task.get('task_id','x')}-"))
        try:
            _clone_repo(repo, base_commit, workdir)
            self.record_trace_event({
                "kind": "mini_swe_setup",
                "repo": repo,
                "base_commit": base_commit,
                "workdir": str(workdir),
            })
            answer, meta = self._loop(
                input, workdir, backbone,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
            )
            # Final patch from git diff (this is what the harness scores).
            patch = _extract_diff(workdir)
            meta["traces"] = {
                **(meta.get("traces") or {}),
                "workdir": str(workdir),
                "final_assistant_summary": answer,
                "patch_chars": len(patch),
            }
            # Wrap the diff in a ```diff fence so the existing
            # extract_patch helpers in the swebench scorer pick it up.
            if patch.strip():
                framed = f"{answer}\n\n```diff\n{patch}```"
            else:
                framed = answer or "[mini-swe-agent produced no diff]"
            return framed, meta
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ------------------------------------------------------------------

    def _loop(
        self,
        problem: str,
        workdir: Path,
        backbone: str,
        *,
        max_turns: int,
        bash_timeout: int,
        output_cap: int,
    ) -> Tuple[str, Dict[str, Any]]:
        if backbone == "cloud":
            return self._loop_cloud(
                problem, workdir,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
            )
        if backbone == "local":
            return self._loop_local(
                problem, workdir,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
            )
        raise ValueError(f"unsupported backbone: {backbone!r}")

    # ------------------------------------------------------------------
    # Cloud (Anthropic) multi-turn loop
    # ------------------------------------------------------------------

    def _loop_cloud(
        self,
        problem: str,
        workdir: Path,
        *,
        max_turns: int,
        bash_timeout: int,
        output_cap: int,
    ) -> Tuple[str, Dict[str, Any]]:
        if self._cloud_endpoint != "anthropic":
            raise ValueError(
                "MiniSWEAgent cloud backbone currently supports anthropic only; "
                f"got {self._cloud_endpoint!r}"
            )
        import anthropic
        client = anthropic.Anthropic(timeout=600.0, max_retries=5)
        messages: List[Dict[str, Any]] = [{"role": "user", "content": problem}]

        tokens_in = 0
        tokens_out = 0
        final_text = ""
        turns = 0
        for turn in range(1, max_turns + 1):
            turns = turn
            kwargs: Dict[str, Any] = {
                "model": self._cloud_model,
                "system": SYSTEM_PROMPT,
                "max_tokens": int(self._cfg.get("turn_max_tokens", 4096)),
                "tools": [BASH_TOOL_ANTHROPIC],
                "messages": messages,
            }
            if supports_temperature(self._cloud_model):
                kwargs["temperature"] = 0.0
            t0 = time.time()
            msg = client.messages.create(**kwargs)
            latency = time.time() - t0
            tokens_in += msg.usage.input_tokens
            tokens_out += msg.usage.output_tokens

            # Serialize the assistant's content blocks for trace.
            content_blocks: List[Dict[str, Any]] = []
            tool_uses: List[Tuple[str, str, Dict[str, Any]]] = []  # (id, name, input)
            text_parts: List[str] = []
            for block in msg.content:
                btype = getattr(block, "type", None)
                if btype == "tool_use":
                    tool_uses.append((block.id, block.name, dict(block.input or {})))
                    content_blocks.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(block.input or {}),
                    })
                elif hasattr(block, "text"):
                    text_parts.append(block.text)
                    content_blocks.append({"type": "text", "text": block.text})
                else:
                    content_blocks.append({"type": btype or "unknown"})

            self.record_trace_event({
                "kind": "mini_swe_turn",
                "turn": turn,
                "stop_reason": msg.stop_reason,
                "tokens_in": msg.usage.input_tokens,
                "tokens_out": msg.usage.output_tokens,
                "latency_s": latency,
                "content_blocks": content_blocks,
            })

            messages.append({"role": "assistant", "content": [
                _anthropic_assistant_block(b) for b in msg.content
            ]})

            if not tool_uses:
                # No tool calls → loop ends.
                final_text = "\n".join(text_parts).strip()
                break

            # Run each tool use, append a tool_result for each.
            tool_result_blocks: List[Dict[str, Any]] = []
            for tu_id, tu_name, tu_input in tool_uses:
                if tu_name != "bash":
                    obs = f"unknown tool: {tu_name!r}"
                    self.record_trace_event({
                        "kind": "mini_swe_unknown_tool",
                        "turn": turn,
                        "name": tu_name,
                        "input": tu_input,
                    })
                else:
                    command = str(tu_input.get("command", ""))
                    result = _run_bash(
                        command, workdir,
                        timeout=bash_timeout, output_cap=output_cap,
                    )
                    self.record_trace_event({
                        "kind": "mini_swe_bash",
                        "turn": turn,
                        "command": command,
                        **result,
                    })
                    obs = _format_observation(result)
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": obs,
                })
            messages.append({"role": "user", "content": tool_result_blocks})

        meta = {
            "tokens_local": 0,
            "tokens_cloud": tokens_in + tokens_out,
            "cost_usd": self.cost_usd(self._cloud_model, tokens_in, tokens_out),
            "turns": turns,
            "traces": {"backbone": "cloud", "max_turns_reached": turns == max_turns and not final_text},
        }
        return final_text, meta

    # ------------------------------------------------------------------
    # Local (vLLM, OpenAI-compatible) multi-turn loop
    # ------------------------------------------------------------------

    def _loop_local(
        self,
        problem: str,
        workdir: Path,
        *,
        max_turns: int,
        bash_timeout: int,
        output_cap: int,
    ) -> Tuple[str, Dict[str, Any]]:
        if not self._local_endpoint or not self._local_model:
            raise ValueError(
                "MiniSWEAgent local backbone needs local_model + local_endpoint"
            )
        from openai import OpenAI
        client = OpenAI(
            base_url=self._local_endpoint, api_key="EMPTY", timeout=600.0,
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": problem},
        ]
        tokens_in = 0
        tokens_out = 0
        final_text = ""
        turns = 0
        for turn in range(1, max_turns + 1):
            turns = turn
            t0 = time.time()
            resp = client.chat.completions.create(
                model=self._local_model,
                messages=messages,
                temperature=0.0,
                max_tokens=int(self._cfg.get("turn_max_tokens", 4096)),
                tools=[BASH_TOOL_OPENAI],
                tool_choice="auto",
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            latency = time.time() - t0
            u = resp.usage
            tokens_in += getattr(u, "prompt_tokens", 0) if u else 0
            tokens_out += getattr(u, "completion_tokens", 0) if u else 0
            choice = resp.choices[0]
            message = choice.message
            tool_calls = list(getattr(message, "tool_calls", None) or [])
            text = message.content or ""

            self.record_trace_event({
                "kind": "mini_swe_turn",
                "turn": turn,
                "finish_reason": choice.finish_reason,
                "tokens_in": getattr(u, "prompt_tokens", 0) if u else 0,
                "tokens_out": getattr(u, "completion_tokens", 0) if u else 0,
                "latency_s": latency,
                "text": text,
                "tool_calls": [
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in tool_calls
                ],
            })

            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ] if tool_calls else None,
            })

            if not tool_calls:
                final_text = text.strip()
                break

            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if tc.function.name != "bash":
                    obs = f"unknown tool: {tc.function.name!r}"
                else:
                    command = str(args.get("command", ""))
                    result = _run_bash(
                        command, workdir,
                        timeout=bash_timeout, output_cap=output_cap,
                    )
                    self.record_trace_event({
                        "kind": "mini_swe_bash",
                        "turn": turn,
                        "command": command,
                        **result,
                    })
                    obs = _format_observation(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs,
                })

        meta = {
            "tokens_local": tokens_in + tokens_out,
            "tokens_cloud": 0,
            "cost_usd": 0.0,
            "turns": turns,
            "traces": {"backbone": "local", "max_turns_reached": turns == max_turns and not final_text},
        }
        return final_text, meta


def _anthropic_assistant_block(block: Any) -> Dict[str, Any]:
    """Convert an Anthropic content block back into the dict shape the API
    expects for assistant-role messages (so we can echo the turn into the
    conversation history)."""
    btype = getattr(block, "type", None)
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if hasattr(block, "text"):
        return {"type": "text", "text": block.text}
    return {"type": btype or "unknown"}


__all__ = ["MiniSWEAgent"]
