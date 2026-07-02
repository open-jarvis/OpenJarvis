"""MiniSWEAgent — vendored, ~330-line port of mini-SWE-agent v2.

Single-LLM agent loop with a ``bash`` tool, run inside a per-task git
clone. The model iterates: read files, grep, run tests, edit, retry —
the environment-interaction loop that turns SWE-bench from "predict the
patch blind" (~0.30) into "actually fix the bug" (~0.77 for frontier
models).

Two ways to use this module:

1. **Standalone agent** — :class:`MiniSWEAgent` registered as
   ``mini_swe_agent``. Use it directly as the agent for a cell.
2. **As a worker subroutine inside another paradigm** — call
   :func:`run_swe_agent_loop(task, ...)`. Returns a dict with the final
   patch, token totals, cost, etc. This is how Minions / Conductor /
   Advisors / SkillOrchestra / ToolOrchestra / Archon swap their
   one-shot worker call for a real agent loop when running SWE-bench.

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
- Trace events captured via the LocalCloudAgent thread-local trace
  buffer so every bash invocation + result lands in
  ``experiments/<cell>/logs/<task_id>.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import (
    LocalCloudAgent,
    _bump_cloud_calls,
    _bump_local_calls,
    _record_event,
)
from openjarvis.agents.hybrid._prices import (
    cost as estimate_cost,
)
from openjarvis.agents.hybrid._prices import (
    is_gpt5_family,
    supports_temperature,
)
from openjarvis.core.registry import AgentRegistry

# Gemini's FunctionDeclaration.parameters expects a Schema-shaped dict (or
# Schema object) with capitalized type strings ("OBJECT", "STRING"). The
# OpenAI/Anthropic JSON-Schema lower-case form is silently dropped — the
# model then can't call the tool. Build a fresh dict instead of reusing
# BASH_TOOL_OPENAI's parameters.
BASH_TOOL_GEMINI_PARAMETERS: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "command": {
            "type": "STRING",
            "description": "The bash command to run.",
        },
    },
    "required": ["command"],
}


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


# ---------- Workdir / bash plumbing ----------

# Models trained on SWE-bench Docker images (Qwen especially) reflexively
# prefix commands with ``cd /testbed`` — the standard container repo path.
# Our harness has no ``/testbed``; the repo is cloned into a per-task
# tempdir and bash already runs with ``cwd`` set to it. An un-rewritten
# ``cd /testbed`` errors with "No such file or directory" and, chained with
# ``&&``, aborts the whole command — so the agent burns every turn and
# never lands an edit. We rewrite ``/testbed`` references to the real
# workdir so those commands run as intended.
_TESTBED_CD_RE = re.compile(r"^\s*cd\s+/testbed(?:/\S*)?\s*(?:&&|;)\s*")


def _rewrite_testbed_paths(command: str, workdir: Path) -> str:
    """Neutralize hard-coded ``/testbed`` paths in a model-issued command.

    - A leading ``cd /testbed && ...`` (or ``;``) is stripped — bash already
      runs in the repo root, so the rest of the command is correct as-is.
    - Any remaining ``/testbed`` occurrences (e.g. ``cat /testbed/foo.py``)
      are rewritten to the real workdir.
    """
    wd = str(workdir)
    new = _TESTBED_CD_RE.sub("", command)
    # Bare ``cd /testbed`` with nothing after it → no-op into the workdir.
    if re.fullmatch(r"\s*cd\s+/testbed/?\s*", new):
        new = f"cd {wd}"
    # Replace any other /testbed path references (word-boundary so we don't
    # clobber e.g. /testbedrock).
    new = re.sub(r"/testbed(?=/|\b)", wd, new)
    return new


def _clone_repo(repo: str, base_commit: str, dest: Path) -> None:
    """Shallow-fetch the SWE-bench repo at the right commit into ``dest``."""
    url = f"https://github.com/{repo}.git"
    subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)],
        check=True,
        timeout=300,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "--quiet", base_commit],
        cwd=str(dest),
        check=True,
        timeout=120,
        capture_output=True,
    )


def _decode_bash_output(raw: bytes, exit_code: int) -> str:
    """Safely decode bash stdout/stderr bytes into a str the LLM can read.

    The model sometimes runs commands that produce binary output (``cat``
    on a ``.pyc`` / ``.png`` / packed extension, a ``find`` that pipes a
    binary blob, ``xxd`` on a libc, ...). Decoding those with strict UTF-8
    raises ``UnicodeDecodeError`` deep inside ``Popen.communicate()`` and
    crashes the whole agent loop (1 errored row in the n=100 sweep per
    such command). We:

    1. Decode with ``errors="replace"`` so partial / mixed output is
       always recoverable as a str.
    2. If the result looks predominantly binary — contains a NUL byte OR
       has more than ~5% U+FFFD replacement chars after decode — replace
       it with a one-line stub so the model can keep working without
       drowning in Mojibake. Threshold checked against the *bytes* length
       (no NUL byte ⇒ probably text-ish; LLMs handle the occasional
       replacement char fine).
    """
    if not raw:
        return ""
    decoded = raw.decode("utf-8", errors="replace")
    if b"\x00" in raw or decoded.count("�") * 20 > len(decoded):
        return f"[binary output: {len(raw)} bytes, exit={exit_code}]"
    return decoded


def _run_bash(
    command: str, workdir: Path, *, timeout: int = 120, output_cap: int = 10_000
) -> Dict[str, Any]:
    """Run one shell command in ``workdir``. Returns dict with stdout, stderr,
    exit_code, and a ``truncated`` flag if output was clamped.

    The command is launched in its own process group (``start_new_session``)
    so a model-issued command that backgrounds a long-lived child (a dev
    server, ``sleep``, a hung test runner) can be killed *as a tree* on
    timeout. Plain ``subprocess.run(..., capture_output=True, timeout=...)``
    only kills the direct child and then re-blocks on ``communicate()``
    draining the pipe — which a surviving grandchild holds open forever,
    silently wedging the whole agent loop.
    """
    t0 = time.time()
    command = _rewrite_testbed_paths(command, workdir)
    # Capture as bytes (no ``text=True``) so a tool invocation that emits
    # binary output (compiled artifact, image, PDF, gzipped tarball) can't
    # crash the loop on a strict UTF-8 decode mid-``communicate()``. We
    # decode below with ``errors="replace"`` and, if the result looks
    # binary (null byte or >5% replacement chars), substitute a stub so
    # the model doesn't waste tokens / context on Mojibake.
    proc = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_b, stderr_b = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        # Kill the whole process group so backgrounded grandchildren can't
        # keep the stdout/stderr pipe open and deadlock the drain below.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        try:
            stdout_b, stderr_b = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout_b, stderr_b = b"", b""
        stdout_b = stdout_b or b""
        stderr_b = stderr_b or b""
        exit_code = -1
        timed_out = True
    stdout = _decode_bash_output(stdout_b, exit_code)
    stderr = _decode_bash_output(stderr_b, exit_code)
    truncated = False
    if len(stdout) > output_cap:
        stdout = (
            stdout[:output_cap] + f"\n…[+{len(stdout) - output_cap} chars truncated]"
        )
        truncated = True
    if len(stderr) > output_cap:
        stderr = (
            stderr[:output_cap] + f"\n…[+{len(stderr) - output_cap} chars truncated]"
        )
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
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.stdout


def _anthropic_assistant_block(block: Any) -> Dict[str, Any]:
    """Convert an Anthropic content block back into the dict shape the API
    expects for assistant-role messages."""
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


# ---------- Reusable agent-loop entry point ----------


def run_swe_agent_loop(
    task: Dict[str, Any],
    *,
    backbone: str,  # "cloud" or "local"
    backbone_model: str,
    cloud_endpoint: str = "anthropic",
    local_endpoint: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    max_turns: int = 30,
    bash_timeout: int = 120,
    bash_timeout_s: Optional[int] = None,
    output_cap: int = 10_000,
    turn_max_tokens: int = 4096,
    trace_prefix: str = "mini_swe",
    workdir: Optional[Path] = None,
    compact_at_tokens: int = 24_000,
    compact_keep_last: int = 4,
) -> Dict[str, Any]:
    """Run a mini-SWE-agent loop for one SWE-bench task. Returns:

    .. code-block:: python

        {
          "answer":         str,   # final framed answer with ```diff fence
          "patch":          str,   # raw unified diff from git diff
          "final_summary":  str,   # the no-tool-call assistant text (may be empty)
          "tokens_in":      int,
          "tokens_out":     int,
          "tokens_local":   int,   # bookkeeping split for paradigms
          "tokens_cloud":   int,
          "cost_usd":       float,
          "turns":          int,
          "max_turns_hit":  bool,
          "workdir":        str,
        }

    Captures every bash invocation + LLM turn into the active trace buffer
    via :func:`_record_event` from the LocalCloudAgent base, so callers
    don't have to do their own per-call instrumentation.

    Args:
      task: SWE-bench-shaped dict with ``repo`` + ``base_commit`` + ``task_id``
        + (optional) ``problem_statement`` / ``hints_text``.
      backbone: ``"cloud"`` to drive the loop with the cloud model
        (Anthropic only today), ``"local"`` for vLLM.
      backbone_model: model id for the loop's backbone.
      cloud_endpoint / local_endpoint: SDK targets.
      initial_prompt: if set, used as the first user message (paradigms
        embed orchestrator context in here). If None, falls back to the
        task's problem_statement.
      workdir: pre-cloned repo path. If None, this function clones the
        repo into a tempdir and cleans it up at the end. Paradigms that
        want to chain multiple subloops over the same working tree can
        manage their own workdir.
    """
    if bash_timeout_s is not None:
        bash_timeout = int(bash_timeout_s)
    repo = task.get("repo") or ""
    base_commit = task.get("base_commit") or ""
    if not repo or not base_commit:
        raise ValueError(
            f"run_swe_agent_loop needs task['repo'] + task['base_commit']; "
            f"got repo={repo!r}, base_commit={base_commit!r}"
        )

    own_workdir = workdir is None
    if own_workdir:
        workdir = Path(tempfile.mkdtemp(prefix=f"mini-swe-{task.get('task_id', 'x')}-"))
        try:
            _clone_repo(repo, base_commit, workdir)
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

    _record_event(
        {
            "kind": f"{trace_prefix}_setup",
            "repo": repo,
            "base_commit": base_commit,
            "workdir": str(workdir),
            "owns_workdir": own_workdir,
            "backbone": backbone,
            "backbone_model": backbone_model,
            "ts": time.time(),
        }
    )

    user_prompt = initial_prompt or task.get("problem_statement") or ""

    try:
        if backbone == "cloud":
            result = _loop_cloud(
                user_prompt,
                workdir,
                model=backbone_model,
                cloud_endpoint=cloud_endpoint,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
                turn_max_tokens=turn_max_tokens,
                trace_prefix=trace_prefix,
            )
        elif backbone == "local":
            if not local_endpoint:
                raise ValueError(
                    "run_swe_agent_loop(backbone='local') needs local_endpoint"
                )
            result = _loop_local(
                user_prompt,
                workdir,
                model=backbone_model,
                endpoint=local_endpoint,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
                turn_max_tokens=turn_max_tokens,
                trace_prefix=trace_prefix,
                compact_at_tokens=compact_at_tokens,
                compact_keep_last=compact_keep_last,
            )
        else:
            raise ValueError(f"unsupported backbone: {backbone!r}")

        patch = _extract_diff(workdir)
        framed = result["final_summary"] or "[mini-swe-agent produced no summary text]"
        if patch.strip():
            framed = f"{framed}\n\n```diff\n{patch}```"

        return {
            "answer": framed,
            "patch": patch,
            "final_summary": result["final_summary"],
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
            "tokens_local": result["tokens_in"] + result["tokens_out"]
            if backbone == "local"
            else 0,
            "tokens_cloud": result["tokens_in"] + result["tokens_out"]
            if backbone == "cloud"
            else 0,
            "cost_usd": (
                estimate_cost(backbone_model, result["tokens_in"], result["tokens_out"])
                if backbone == "cloud"
                else 0.0
            ),
            "turns": result["turns"],
            "max_turns_hit": result["max_turns_hit"],
            "workdir": str(workdir),
        }
    finally:
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


# ---------- Cloud loop (dispatcher → per-endpoint multi-turn tool loops) ----------


def _loop_cloud(
    problem: str,
    workdir: Path,
    *,
    model: str,
    cloud_endpoint: str,
    max_turns: int,
    bash_timeout: int,
    output_cap: int,
    turn_max_tokens: int,
    trace_prefix: str,
) -> Dict[str, Any]:
    """Route to the right per-endpoint cloud loop. Anthropic path is the
    original byte-identical implementation (16 cells in the n=100 sweep
    depend on its exact behavior). OpenAI / Gemini paths added 2026-05-15
    to unblock the 8 SWE cells that were stuck on Anthropic-only support."""
    if cloud_endpoint == "anthropic":
        return _loop_cloud_anthropic(
            problem,
            workdir,
            model=model,
            max_turns=max_turns,
            bash_timeout=bash_timeout,
            output_cap=output_cap,
            turn_max_tokens=turn_max_tokens,
            trace_prefix=trace_prefix,
        )
    if cloud_endpoint == "openai":
        return _loop_cloud_openai(
            problem,
            workdir,
            model=model,
            max_turns=max_turns,
            bash_timeout=bash_timeout,
            output_cap=output_cap,
            turn_max_tokens=turn_max_tokens,
            trace_prefix=trace_prefix,
        )
    if cloud_endpoint == "gemini":
        return _loop_cloud_gemini(
            problem,
            workdir,
            model=model,
            max_turns=max_turns,
            bash_timeout=bash_timeout,
            output_cap=output_cap,
            turn_max_tokens=turn_max_tokens,
            trace_prefix=trace_prefix,
        )
    raise ValueError(
        f"mini-SWE-agent cloud backbone unsupported endpoint: {cloud_endpoint!r}"
    )


def _loop_cloud_anthropic(
    problem: str,
    workdir: Path,
    *,
    model: str,
    max_turns: int,
    bash_timeout: int,
    output_cap: int,
    turn_max_tokens: int,
    trace_prefix: str,
) -> Dict[str, Any]:
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
            "model": model,
            "system": SYSTEM_PROMPT,
            "max_tokens": turn_max_tokens,
            "tools": [BASH_TOOL_ANTHROPIC],
            "messages": messages,
        }
        if supports_temperature(model):
            kwargs["temperature"] = 0.0
        t0 = time.time()
        msg = client.messages.create(**kwargs)
        _bump_cloud_calls()
        latency = time.time() - t0
        tokens_in += msg.usage.input_tokens
        tokens_out += msg.usage.output_tokens

        content_blocks: List[Dict[str, Any]] = []
        tool_uses: List[Tuple[str, str, Dict[str, Any]]] = []
        text_parts: List[str] = []
        for block in msg.content:
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                tool_uses.append((block.id, block.name, dict(block.input or {})))
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(block.input or {}),
                    }
                )
            elif hasattr(block, "text"):
                text_parts.append(block.text)
                content_blocks.append({"type": "text", "text": block.text})
            else:
                content_blocks.append({"type": btype or "unknown"})

        _record_event(
            {
                "kind": f"{trace_prefix}_turn",
                "turn": turn,
                "stop_reason": msg.stop_reason,
                "tokens_in": msg.usage.input_tokens,
                "tokens_out": msg.usage.output_tokens,
                "latency_s": latency,
                "content_blocks": content_blocks,
                "ts": time.time(),
            }
        )

        messages.append(
            {
                "role": "assistant",
                "content": [_anthropic_assistant_block(b) for b in msg.content],
            }
        )

        if not tool_uses:
            final_text = "\n".join(text_parts).strip()
            break

        tool_result_blocks: List[Dict[str, Any]] = []
        for tu_id, tu_name, tu_input in tool_uses:
            if tu_name != "bash":
                obs = f"unknown tool: {tu_name!r}"
                _record_event(
                    {
                        "kind": f"{trace_prefix}_unknown_tool",
                        "turn": turn,
                        "name": tu_name,
                        "input": tu_input,
                        "ts": time.time(),
                    }
                )
            else:
                command = str(tu_input.get("command", ""))
                result = _run_bash(
                    command,
                    workdir,
                    timeout=bash_timeout,
                    output_cap=output_cap,
                )
                _record_event(
                    {
                        "kind": f"{trace_prefix}_bash",
                        "turn": turn,
                        "command": command,
                        **result,
                        "ts": time.time(),
                    }
                )
                obs = _format_observation(result)
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu_id,
                    "content": obs,
                }
            )
        messages.append({"role": "user", "content": tool_result_blocks})

    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "turns": turns,
        "final_summary": final_text,
        "max_turns_hit": turns == max_turns and not final_text,
    }


# ---------- Cloud loop (OpenAI multi-turn with function tools) ----------


def _loop_cloud_openai(
    problem: str,
    workdir: Path,
    *,
    model: str,
    max_turns: int,
    bash_timeout: int,
    output_cap: int,
    turn_max_tokens: int,
    trace_prefix: str,
) -> Dict[str, Any]:
    """OpenAI Chat Completions multi-turn loop. Mirrors the Anthropic
    branch: each turn the model either calls ``bash`` (one or more parallel
    tool_calls) or produces a no-tool-call final message that terminates
    the loop. The final message's text is returned as ``final_summary``;
    the patch comes from ``git diff`` on the workdir.

    Quirks:
    - GPT-5 family rejects ``temperature`` and uses ``max_completion_tokens``
      instead of ``max_tokens``. We branch on ``is_gpt5_family`` for both.
    - ``tool_calls`` arguments arrive as JSON-string blobs; we tolerate
      malformed JSON by treating it as an empty arg dict (matches the
      ``_loop_local`` behavior).
    """
    from openai import OpenAI

    client = OpenAI(timeout=600.0)

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
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": [BASH_TOOL_OPENAI],
            "tool_choice": "auto",
        }
        if is_gpt5_family(model):
            kwargs["max_completion_tokens"] = turn_max_tokens
        else:
            kwargs["max_tokens"] = turn_max_tokens
            kwargs["temperature"] = 0.0
        t0 = time.time()
        resp = client.chat.completions.create(**kwargs)
        _bump_cloud_calls()
        latency = time.time() - t0
        u = resp.usage
        tokens_in += getattr(u, "prompt_tokens", 0) if u else 0
        tokens_out += getattr(u, "completion_tokens", 0) if u else 0
        choice = resp.choices[0]
        message = choice.message
        tool_calls = list(getattr(message, "tool_calls", None) or [])
        text = message.content or ""

        _record_event(
            {
                "kind": f"{trace_prefix}_turn",
                "turn": turn,
                "endpoint": "openai",
                "finish_reason": choice.finish_reason,
                "tokens_in": getattr(u, "prompt_tokens", 0) if u else 0,
                "tokens_out": getattr(u, "completion_tokens", 0) if u else 0,
                "latency_s": latency,
                "text": text,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in tool_calls
                ],
                "ts": time.time(),
            }
        )

        # Append the assistant turn (including any tool_calls) so the
        # follow-up tool messages have the right call ids to reference.
        # OpenAI Chat Completions rejects ``content: null`` with a 400
        # ("expected a string, got null") on the next turn when this
        # message gets replayed. Use ``""`` — explicitly allowed by the
        # schema when ``tool_calls`` is present, and equivalent to
        # "assistant had no visible text, only tool calls".
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": text or "",
        }
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        if not tool_calls:
            # Silent-truncation recovery: ``finish_reason='length'`` means
            # the response was cut mid-generation. If a tool call was
            # forming when the cap hit, ``tool_calls`` is empty AND ``text``
            # is empty/short — treating that as "model done" exits the loop
            # with a useless empty final_summary (observed on gpt-5-mini SWE
            # cells, 2026-05-15). Inject a one-shot recovery nudge and let
            # the loop continue; only terminate naturally on ``stop``.
            if (
                choice.finish_reason == "length"
                and not text.strip()
                and turn < max_turns
            ):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was truncated by the token limit "
                            "before producing a tool call or final summary. Retry: "
                            "either issue ONE bash tool call (short command, no large "
                            "output) or send a brief one-line final summary with no "
                            "tool calls to end the loop."
                        ),
                    }
                )
                _record_event(
                    {
                        "kind": f"{trace_prefix}_recover",
                        "turn": turn,
                        "reason": "length_truncation_no_tool_call",
                        "ts": time.time(),
                    }
                )
                continue
            # No tool call → the model is done. Same termination rule as
            # the Anthropic branch.
            final_text = text.strip()
            break

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if tc.function.name != "bash":
                obs = f"unknown tool: {tc.function.name!r}"
                _record_event(
                    {
                        "kind": f"{trace_prefix}_unknown_tool",
                        "turn": turn,
                        "name": tc.function.name,
                        "input": args,
                        "ts": time.time(),
                    }
                )
            else:
                command = str(args.get("command", ""))
                result = _run_bash(
                    command,
                    workdir,
                    timeout=bash_timeout,
                    output_cap=output_cap,
                )
                _record_event(
                    {
                        "kind": f"{trace_prefix}_bash",
                        "turn": turn,
                        "command": command,
                        **result,
                        "ts": time.time(),
                    }
                )
                obs = _format_observation(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs,
                }
            )

    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "turns": turns,
        "final_summary": final_text,
        "max_turns_hit": turns == max_turns and not final_text,
    }


# ---------- Cloud loop (Gemini multi-turn with function tools) ----------


def _loop_cloud_gemini(
    problem: str,
    workdir: Path,
    *,
    model: str,
    max_turns: int,
    bash_timeout: int,
    output_cap: int,
    turn_max_tokens: int,
    trace_prefix: str,
) -> Dict[str, Any]:
    """google-genai multi-turn loop (Gemini Developer API, v1.64).

    Tool-use plumbing diverges from OpenAI/Anthropic enough to warrant a
    parallel branch:

    - Parameters must be a Schema-shaped dict with capitalized type names
      ("OBJECT", "STRING"). The lower-case JSON-Schema form is silently
      dropped — the model never produces a call.
    - We explicitly disable ``automatic_function_calling`` so the SDK
      stops at the FunctionCall part and we drive the loop ourselves.
    - Termination heuristic: stop when the model's response has zero
      function_call parts. Same intent as Anthropic ("no tool_use blocks")
      and OpenAI ("empty tool_calls"). Gemini occasionally emits a turn
      with both text and function_call parts; we still treat that as a
      tool turn (matches Anthropic's behavior with mixed content).
    - System prompt goes on the config, not the contents list (Gemini
      convention).
    - The function-response part body is a free-form dict; we wrap the
      bash observation in ``{"output": str}``.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(http_options=types.HttpOptions(timeout=600_000))
    bash_tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="bash",
                description=BASH_TOOL_ANTHROPIC["description"],
                parameters=BASH_TOOL_GEMINI_PARAMETERS,
            ),
        ]
    )

    contents: List[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=problem)]),
    ]
    tokens_in = 0
    tokens_out = 0
    final_text = ""
    turns = 0
    for turn in range(1, max_turns + 1):
        turns = turn
        cfg = types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=turn_max_tokens,
            system_instruction=SYSTEM_PROMPT,
            tools=[bash_tool],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )
        t0 = time.time()
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=cfg,
        )
        _bump_cloud_calls()
        latency = time.time() - t0
        um = getattr(resp, "usage_metadata", None)
        p = int(getattr(um, "prompt_token_count", 0) or 0) if um else 0
        c = int(getattr(um, "candidates_token_count", 0) or 0) if um else 0
        tokens_in += p
        tokens_out += c

        # Pull parts out of the first candidate. Defensive against the
        # zero-candidate / safety-filtered case (returns empty parts and
        # we'll terminate on the next branch).
        cand_parts: List[Any] = []
        try:
            cand_content = resp.candidates[0].content
            cand_parts = list(getattr(cand_content, "parts", None) or [])
        except Exception:
            cand_content = None
            cand_parts = []

        text_parts: List[str] = []
        function_calls: List[Tuple[str, Dict[str, Any]]] = []
        for part in cand_parts:
            fc = getattr(part, "function_call", None)
            if fc is not None:
                fc_args = dict(getattr(fc, "args", None) or {})
                function_calls.append((fc.name, fc_args))
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        finish_reason = None
        try:
            finish_reason = str(resp.candidates[0].finish_reason)
        except Exception:
            pass

        _record_event(
            {
                "kind": f"{trace_prefix}_turn",
                "turn": turn,
                "endpoint": "gemini",
                "finish_reason": finish_reason,
                "tokens_in": p,
                "tokens_out": c,
                "latency_s": latency,
                "text": "\n".join(text_parts),
                "tool_calls": [
                    {"name": name, "arguments": args} for name, args in function_calls
                ],
                "ts": time.time(),
            }
        )

        # Append the model's content as-is so the next turn sees its own
        # prior function_call parts (Gemini requires this for the
        # function_response to bind).
        if cand_content is not None:
            contents.append(cand_content)
        else:
            # Safety-filtered / empty — synthesize an empty model turn so
            # the conversation stays well-formed and exit the loop.
            contents.append(types.Content(role="model", parts=[]))

        if not function_calls:
            # Silent-failure recovery for Gemini's quirky finish reasons:
            #   MALFORMED_FUNCTION_CALL — model wanted to call bash but
            #     produced unparseable args (24/100 of broken n=100 SWE
            #     cells, 2026-05-15). Empty text + empty function_calls →
            #     loop would exit with no final summary.
            #   MAX_TOKENS — same shape as OpenAI's ``length``; truncated
            #     mid-generation, no tool call landed.
            # Inject a recovery nudge and let the loop continue; only
            # treat genuine ``STOP`` with text as a final answer.
            fr_str = str(finish_reason or "")
            empty_text = not any(t.strip() for t in text_parts)
            recoverable = (
                empty_text
                and turn < max_turns
                and ("MALFORMED_FUNCTION_CALL" in fr_str or "MAX_TOKENS" in fr_str)
            )
            if recoverable:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                text=(
                                    "Your previous response had no parsable function call "
                                    "and no final text (finish_reason="
                                    f"{fr_str}). Retry: either issue ONE well-formed "
                                    "`bash` function call (short command, valid JSON-ish "
                                    "args) or send a brief final text message with no "
                                    "function call to end the loop."
                                )
                            )
                        ],
                    )
                )
                _record_event(
                    {
                        "kind": f"{trace_prefix}_recover",
                        "turn": turn,
                        "reason": f"empty_response_{fr_str}",
                        "ts": time.time(),
                    }
                )
                continue
            final_text = "\n".join(text_parts).strip()
            break

        response_parts: List[Any] = []
        for name, args in function_calls:
            if name != "bash":
                obs = f"unknown tool: {name!r}"
                _record_event(
                    {
                        "kind": f"{trace_prefix}_unknown_tool",
                        "turn": turn,
                        "name": name,
                        "input": args,
                        "ts": time.time(),
                    }
                )
            else:
                command = str(args.get("command", ""))
                result = _run_bash(
                    command,
                    workdir,
                    timeout=bash_timeout,
                    output_cap=output_cap,
                )
                _record_event(
                    {
                        "kind": f"{trace_prefix}_bash",
                        "turn": turn,
                        "command": command,
                        **result,
                        "ts": time.time(),
                    }
                )
                obs = _format_observation(result)
            response_parts.append(
                types.Part.from_function_response(
                    name=name,
                    response={"output": obs},
                )
            )
        contents.append(types.Content(role="user", parts=response_parts))

    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "turns": turns,
        "final_summary": final_text,
        "max_turns_hit": turns == max_turns and not final_text,
    }


# ---------- Local loop (vLLM, OpenAI-compatible multi-turn with tools) ----------

_COMPACT_PROMPT = (
    "Summarize the SWE-bench agent trajectory so far in under 2000 characters. "
    "Preserve: filenames touched, hypotheses tested, what worked, what failed, "
    "and the current plan. Be terse — no preamble, no quoted output, just facts."
)

_TIKTOKEN_ENC = None
_TIKTOKEN_WARNED = False


def _get_tiktoken_enc() -> Any:
    global _TIKTOKEN_ENC, _TIKTOKEN_WARNED
    if _TIKTOKEN_ENC is not None:
        return _TIKTOKEN_ENC
    try:
        import tiktoken

        _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        if not _TIKTOKEN_WARNED:
            print(
                f"[mini_swe_agent] tiktoken unavailable ({exc!r}); falling back to len(s)//4",
                flush=True,
            )
            _TIKTOKEN_WARNED = True
        _TIKTOKEN_ENC = False
    return _TIKTOKEN_ENC


def _estimate_prompt_tokens(messages: List[Dict[str, Any]]) -> int:
    enc = _get_tiktoken_enc()
    total = 0
    for m in messages:
        total += 4  # per-message overhead
        c = m.get("content")
        if isinstance(c, str):
            s = c
        elif isinstance(c, list):
            parts = []
            for block in c:
                if isinstance(block, dict):
                    parts.append(str(block.get("content") or block.get("text") or ""))
            s = "\n".join(parts)
        else:
            s = ""
        for tc in m.get("tool_calls") or []:
            try:
                s += "\n" + (tc["function"]["arguments"] or "")
                s += "\n" + (tc["function"].get("name") or "")
            except (KeyError, TypeError):
                pass
        tcid = m.get("tool_call_id")
        if tcid:
            s += "\n" + str(tcid)
        if enc:
            total += len(enc.encode(s, disallowed_special=()))
        else:
            total += len(s) // 4
    return total


_EXIT_PATTERNS = (
    re.compile(r"exit_code\s*[=:]\s*(-?\d+)"),
    re.compile(r"returncode\s*[=:]\s*(-?\d+)"),
    re.compile(r"\bexit\s+(-?\d+)\b"),
)


def _parse_exit_code(content: Any) -> str:
    if not isinstance(content, str):
        return "?"
    for pat in _EXIT_PATTERNS:
        m = pat.search(content)
        if m:
            return m.group(1)
    return "?"


def _identify_turns(messages: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    """Return list of (start_idx, end_idx_exclusive) for each assistant+tools turn.

    A turn = one assistant message (with or without tool_calls) plus any
    immediately-following tool messages. System + initial user are skipped.
    """
    turns: List[Tuple[int, int]] = []
    i = 0
    n = len(messages)
    while i < n:
        role = messages[i].get("role")
        if role == "assistant":
            j = i + 1
            while j < n and messages[j].get("role") == "tool":
                j += 1
            turns.append((i, j))
            i = j
        else:
            i += 1
    return turns


def _compact_local_messages(
    messages: List[Dict[str, Any]],
    *,
    client: Any,
    model: str,
    keep_last: int,
    trace_prefix: str,
    compact_at_tokens: int = 24_000,
) -> List[Dict[str, Any]]:
    if len(messages) < 2:
        return messages
    system_msg = messages[0]
    initial_user = messages[1]

    turns = _identify_turns(messages)
    if len(turns) <= keep_last:
        return messages

    keep_turns = turns[-keep_last:]
    old_turns = turns[:-keep_last]
    keep_start = keep_turns[0][0]

    # Stage 1: elide tool observations in old turns.
    before_tokens = _estimate_prompt_tokens(messages)
    new_messages: List[Dict[str, Any]] = list(messages)
    n_tool_elided = 0
    for s, e in old_turns:
        for k in range(s, e):
            m = new_messages[k]
            if m.get("role") != "tool":
                continue
            orig = m.get("content")
            if not isinstance(orig, str):
                continue
            n_chars = len(orig)
            if n_chars <= 200:
                continue
            exit_code = _parse_exit_code(orig)
            stub = f"[tool output elided: {n_chars} chars, exit={exit_code}]"
            new_messages[k] = {
                "role": "tool",
                "tool_call_id": m.get("tool_call_id"),
                "content": stub,
            }
            n_tool_elided += 1

    after_stage1_tokens = _estimate_prompt_tokens(new_messages)
    _record_event(
        {
            "kind": f"{trace_prefix}_compact",
            "stage": "1",
            "msgs_before": len(messages),
            "msgs_after": len(new_messages),
            "before_tokens": before_tokens,
            "after_tokens": after_stage1_tokens,
            "n_tool_elided": n_tool_elided,
            "n_turns_folded": 0,
            "ts": time.time(),
        }
    )

    if after_stage1_tokens <= compact_at_tokens:
        return new_messages

    # Stage 2: fold old turns into a single synthetic system summary.
    middle = new_messages[2:keep_start]
    tail = new_messages[keep_start:]
    if not middle:
        return new_messages

    summary_input = [
        {"role": "system", "content": _COMPACT_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                [
                    {
                        "role": m.get("role"),
                        "content": m.get("content")
                        if isinstance(m.get("content"), str)
                        else str(m.get("content"))[:4000],
                    }
                    for m in middle
                ],
                default=str,
            )[:60_000],
        },
    ]
    summary = ""
    try:
        if client is not None:
            resp = client.chat.completions.create(
                model=model,
                messages=summary_input,
                temperature=0.0,
                max_tokens=1024,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            _bump_local_calls()
            summary = (resp.choices[0].message.content or "").strip()[:2000]
    except Exception as exc:
        summary = f"[compaction summary failed: {exc!r}; older turns dropped]"
    if not summary:
        summary = "[no summary produced; older turns dropped]"

    n_turns_folded = len(old_turns)
    synthetic = {
        "role": "system",
        "content": f"[turns 1–{n_turns_folded} elided: {summary}]",
    }
    folded = [system_msg, initial_user, synthetic, *tail]
    after_stage2_tokens = _estimate_prompt_tokens(folded)
    _record_event(
        {
            "kind": f"{trace_prefix}_compact",
            "stage": "2",
            "msgs_before": len(new_messages),
            "msgs_after": len(folded),
            "before_tokens": after_stage1_tokens,
            "after_tokens": after_stage2_tokens,
            "n_tool_elided": n_tool_elided,
            "n_turns_folded": n_turns_folded,
            "summary_chars": len(summary),
            "ts": time.time(),
        }
    )
    return folded


def _loop_local(
    problem: str,
    workdir: Path,
    *,
    model: str,
    endpoint: str,
    max_turns: int,
    bash_timeout: int,
    output_cap: int,
    turn_max_tokens: int,
    trace_prefix: str,
    compact_at_tokens: int = 22_000,
    compact_keep_last: int = 3,
) -> Dict[str, Any]:
    # Qwen-27B has a 32k context. With ``max_tokens=turn_max_tokens`` reserved
    # for output (default 4096) plus ~1k for the bash tool schema + system
    # prompt + format overhead, the practical input ceiling is ~27k. We
    # compact at 22k so there's slack for one more tool result before the
    # next turn's pre-call check fires again. Earlier we used 24k + keep=4
    # but still saw 28k-input 400s on the n=100 SWE sweep (the keep window
    # alone routinely exceeded the budget once bash outputs piled up).
    from openai import OpenAI

    client = OpenAI(base_url=endpoint, api_key="EMPTY", timeout=600.0)

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
        if (
            compact_at_tokens > 0
            and _estimate_prompt_tokens(messages) > compact_at_tokens
        ):
            messages = _compact_local_messages(
                messages,
                client=client,
                model=model,
                keep_last=compact_keep_last,
                trace_prefix=trace_prefix,
                compact_at_tokens=compact_at_tokens,
            )
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=turn_max_tokens,
                tools=[BASH_TOOL_OPENAI],
                tool_choice="auto",
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except Exception as exc:
            # Emergency compaction on a context-length 400 from vLLM /
            # OpenAI ("maximum context length is N tokens"). Our pre-call
            # estimator can undercount when tool args / tool_call_ids /
            # template overhead spike, so the budget check missed and the
            # server walled the call. Compact aggressively (keep_last=1)
            # and retry once. Re-raise on anything else or on a second
            # failure — the runner records the row as errored.
            msg = str(exc)
            is_ctx = (
                "maximum context length" in msg
                or "context length" in msg.lower()
                and "exceed" in msg.lower()
            )
            if not is_ctx:
                raise
            _record_event(
                {
                    "kind": f"{trace_prefix}_emergency_compact",
                    "turn": turn,
                    "error": msg[:300],
                    "tokens_before": _estimate_prompt_tokens(messages),
                    "ts": time.time(),
                }
            )
            messages = _compact_local_messages(
                messages,
                client=client,
                model=model,
                keep_last=1,
                trace_prefix=trace_prefix,
                compact_at_tokens=max(8_000, compact_at_tokens // 2),
            )
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                max_tokens=turn_max_tokens,
                tools=[BASH_TOOL_OPENAI],
                tool_choice="auto",
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        _bump_local_calls()
        latency = time.time() - t0
        u = resp.usage
        tokens_in += getattr(u, "prompt_tokens", 0) if u else 0
        tokens_out += getattr(u, "completion_tokens", 0) if u else 0
        choice = resp.choices[0]
        message = choice.message
        tool_calls = list(getattr(message, "tool_calls", None) or [])
        text = message.content or ""

        _record_event(
            {
                "kind": f"{trace_prefix}_turn",
                "turn": turn,
                "finish_reason": choice.finish_reason,
                "tokens_in": getattr(u, "prompt_tokens", 0) if u else 0,
                "tokens_out": getattr(u, "completion_tokens", 0) if u else 0,
                "latency_s": latency,
                "text": text,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                    for tc in tool_calls
                ],
                "ts": time.time(),
            }
        )

        # Match the OpenAI cloud branch: content="" (not None) when only
        # tool_calls are present; omit ``tool_calls`` entirely when there
        # are none (vs. setting it to None) so the message validates
        # against the strict OpenAI schema if it ever gets replayed by
        # the compactor's summarizer call.
        assistant_local_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": text or "",
        }
        if tool_calls:
            assistant_local_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_local_msg)

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
                    command,
                    workdir,
                    timeout=bash_timeout,
                    output_cap=output_cap,
                )
                _record_event(
                    {
                        "kind": f"{trace_prefix}_bash",
                        "turn": turn,
                        "command": command,
                        **result,
                        "ts": time.time(),
                    }
                )
                obs = _format_observation(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": obs,
                }
            )

    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "turns": turns,
        "final_summary": final_text,
        "max_turns_hit": turns == max_turns and not final_text,
    }


# ---------- Standalone agent ----------


@AgentRegistry.register("mini_swe_agent")
class MiniSWEAgent(LocalCloudAgent):
    """Single-model bash-loop agent for SWE-bench-shaped tasks.

    Configurable knobs via ``cfg``:

    - ``backbone`` (str, default ``"cloud"``): ``"cloud"`` or ``"local"``.
    - ``max_turns`` (int, default 30): hard cap on tool turns.
    - ``bash_timeout_s`` (int, default 120): per-command timeout.
    - ``output_cap`` (int, default 10_000): per-command stdout/stderr cap.
    - ``turn_max_tokens`` (int, default 4096): max_tokens per LLM turn.
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

        backbone = cfg.get("backbone", "cloud")
        model = self._cloud_model if backbone == "cloud" else (self._local_model or "")

        out = run_swe_agent_loop(
            task,
            backbone=backbone,
            backbone_model=model,
            cloud_endpoint=self._cloud_endpoint,
            local_endpoint=self._local_endpoint,
            initial_prompt=input,
            max_turns=int(cfg.get("max_turns", 30)),
            bash_timeout=int(cfg.get("bash_timeout_s", 120)),
            output_cap=int(cfg.get("output_cap", 10_000)),
            turn_max_tokens=int(cfg.get("turn_max_tokens", 4096)),
        )
        meta = {
            "tokens_local": out["tokens_local"],
            "tokens_cloud": out["tokens_cloud"],
            "cost_usd": out["cost_usd"],
            "turns": out["turns"],
            "traces": {
                "backbone": backbone,
                "max_turns_hit": out["max_turns_hit"],
                "patch_chars": len(out["patch"]),
                "final_summary": out["final_summary"],
            },
        }
        return out["answer"], meta


__all__ = ["MiniSWEAgent", "run_swe_agent_loop", "SYSTEM_PROMPT"]
