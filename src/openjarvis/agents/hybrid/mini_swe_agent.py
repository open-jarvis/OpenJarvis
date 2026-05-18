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
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent, _record_event
from openjarvis.agents.hybrid._prices import (
    cost as estimate_cost,
)
from openjarvis.agents.hybrid._prices import (
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


# ---------- Workdir / bash plumbing ----------

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
    backbone: str,                          # "cloud" or "local"
    backbone_model: str,
    cloud_endpoint: str = "anthropic",
    local_endpoint: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    max_turns: int = 30,
    bash_timeout: int = 120,
    output_cap: int = 10_000,
    turn_max_tokens: int = 4096,
    trace_prefix: str = "mini_swe",
    workdir: Optional[Path] = None,
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
    repo = task.get("repo") or ""
    base_commit = task.get("base_commit") or ""
    if not repo or not base_commit:
        raise ValueError(
            f"run_swe_agent_loop needs task['repo'] + task['base_commit']; "
            f"got repo={repo!r}, base_commit={base_commit!r}"
        )

    own_workdir = workdir is None
    if own_workdir:
        workdir = Path(tempfile.mkdtemp(
            prefix=f"mini-swe-{task.get('task_id','x')}-"
        ))
        try:
            _clone_repo(repo, base_commit, workdir)
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

    _record_event({
        "kind": f"{trace_prefix}_setup",
        "repo": repo,
        "base_commit": base_commit,
        "workdir": str(workdir),
        "owns_workdir": own_workdir,
        "backbone": backbone,
        "backbone_model": backbone_model,
        "ts": time.time(),
    })

    user_prompt = initial_prompt or task.get("problem_statement") or ""

    try:
        if backbone == "cloud":
            result = _loop_cloud(
                user_prompt, workdir,
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
                raise ValueError("run_swe_agent_loop(backbone='local') needs local_endpoint")
            result = _loop_local(
                user_prompt, workdir,
                model=backbone_model,
                endpoint=local_endpoint,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
                turn_max_tokens=turn_max_tokens,
                trace_prefix=trace_prefix,
            )
        else:
            raise ValueError(f"unsupported backbone: {backbone!r}")

        patch = _extract_diff(workdir)
        framed = (result["final_summary"] or "[mini-swe-agent produced no summary text]")
        if patch.strip():
            framed = f"{framed}\n\n```diff\n{patch}```"

        return {
            "answer": framed,
            "patch": patch,
            "final_summary": result["final_summary"],
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
            "tokens_local": result["tokens_in"] + result["tokens_out"] if backbone == "local" else 0,
            "tokens_cloud": result["tokens_in"] + result["tokens_out"] if backbone == "cloud" else 0,
            "cost_usd": (
                estimate_cost(backbone_model, result["tokens_in"], result["tokens_out"])
                if backbone == "cloud" else 0.0
            ),
            "turns": result["turns"],
            "max_turns_hit": result["max_turns_hit"],
            "workdir": str(workdir),
        }
    finally:
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


# ---------- Cloud loop (Anthropic multi-turn with tools) ----------

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
    if cloud_endpoint != "anthropic":
        raise ValueError(
            f"mini-SWE-agent cloud backbone currently supports anthropic only; "
            f"got {cloud_endpoint!r}"
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
                content_blocks.append({
                    "type": "tool_use", "id": block.id, "name": block.name,
                    "input": dict(block.input or {}),
                })
            elif hasattr(block, "text"):
                text_parts.append(block.text)
                content_blocks.append({"type": "text", "text": block.text})
            else:
                content_blocks.append({"type": btype or "unknown"})

        _record_event({
            "kind": f"{trace_prefix}_turn",
            "turn": turn,
            "stop_reason": msg.stop_reason,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "latency_s": latency,
            "content_blocks": content_blocks,
            "ts": time.time(),
        })

        messages.append({"role": "assistant", "content": [
            _anthropic_assistant_block(b) for b in msg.content
        ]})

        if not tool_uses:
            final_text = "\n".join(text_parts).strip()
            break

        tool_result_blocks: List[Dict[str, Any]] = []
        for tu_id, tu_name, tu_input in tool_uses:
            if tu_name != "bash":
                obs = f"unknown tool: {tu_name!r}"
                _record_event({
                    "kind": f"{trace_prefix}_unknown_tool",
                    "turn": turn, "name": tu_name, "input": tu_input,
                    "ts": time.time(),
                })
            else:
                command = str(tu_input.get("command", ""))
                result = _run_bash(
                    command, workdir,
                    timeout=bash_timeout, output_cap=output_cap,
                )
                _record_event({
                    "kind": f"{trace_prefix}_bash",
                    "turn": turn, "command": command,
                    **result, "ts": time.time(),
                })
                obs = _format_observation(result)
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": obs,
            })
        messages.append({"role": "user", "content": tool_result_blocks})

    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "turns": turns,
        "final_summary": final_text,
        "max_turns_hit": turns == max_turns and not final_text,
    }


# ---------- Local loop (vLLM, OpenAI-compatible multi-turn with tools) ----------

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
) -> Dict[str, Any]:
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
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=turn_max_tokens,
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

        _record_event({
            "kind": f"{trace_prefix}_turn",
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
            "ts": time.time(),
        })

        messages.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": [
                {
                    "id": tc.id, "type": "function",
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
                _record_event({
                    "kind": f"{trace_prefix}_bash",
                    "turn": turn, "command": command,
                    **result, "ts": time.time(),
                })
                obs = _format_observation(result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": obs,
            })

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
        model = (
            self._cloud_model if backbone == "cloud"
            else (self._local_model or "")
        )

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
