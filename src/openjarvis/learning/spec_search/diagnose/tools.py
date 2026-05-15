"""Diagnostic tools exposed to the teacher in the diagnose phase.

All tools are **read-only** relative to the user's config. They do not mutate
``~/.openjarvis/config.toml``, agent prompts, or tool descriptions.

Tools that execute code (``run_student_on_task``, ``run_self_on_task``) append
new traces to ``TraceStore`` as a side effect. These traces are tagged with
``source=spec_search_session:<id>`` so they can be excluded from future
learning input.

See spec §5.2.
"""

from __future__ import annotations

import json
from typing import Any

from openjarvis.learning.spec_search.diagnose.types import DiagnosticTool


def build_diagnostic_tools(
    *,
    trace_store: Any,
    config: dict[str, Any],
    benchmark_samples: list,
    student_runner: Any,
    teacher_engine: Any,
    teacher_model: str,
    judge: Any,
    session_id: str,
) -> list[DiagnosticTool]:
    """Build all diagnostic tools as closures over shared dependencies.

    Parameters
    ----------
    trace_store :
        A ``TraceStore`` instance for trace queries.
    config :
        Dict with ``config_path`` (Path) and ``openjarvis_home`` (Path).
    benchmark_samples :
        List of ``PersonalBenchmarkSample`` objects.
    student_runner :
        Callable that re-executes the student on a task.
    teacher_engine :
        The ``CloudEngine`` instance used by the teacher.
    teacher_model :
        Model id for teacher inference (e.g. "claude-opus-4-6").
    judge :
        A ``TraceJudge`` instance for comparing outputs.
    session_id :
        Current session id for tagging traces.
    """
    openjarvis_home = config["openjarvis_home"]

    # ------------------------------------------------------------------
    # list_traces
    # ------------------------------------------------------------------
    def _list_traces(
        limit: int = 20,
        agent: str | None = None,
        outcome: str | None = None,
        min_feedback: float | None = None,
        max_feedback: float | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {"limit": limit}
        if agent:
            kwargs["agent"] = agent
        if outcome:
            kwargs["outcome"] = outcome
        traces = trace_store.list_traces(**kwargs)
        metas = []
        for t in traces:
            fb = getattr(t, "feedback", None)
            if min_feedback is not None and (fb is None or fb < min_feedback):
                continue
            if max_feedback is not None and (fb is None or fb > max_feedback):
                continue
            metas.append(
                {
                    "trace_id": t.trace_id,
                    "query": t.query[:200],
                    "agent": t.agent,
                    "model": t.model,
                    "outcome": t.outcome,
                    "feedback": fb,
                    "started_at": t.started_at,
                }
            )
        return json.dumps(metas, default=str)

    # ------------------------------------------------------------------
    # get_trace
    # ------------------------------------------------------------------
    def _get_trace(trace_id: str) -> str:
        trace = trace_store.get(trace_id)
        if trace is None:
            return json.dumps({"error": f"Trace {trace_id} not found"})
        # Truncate large free-text fields so a single get_trace call can't
        # blow out the teacher's context window. monitor_operative traces
        # can have 50-95K tokens of result text each.
        query = trace.query or ""
        result = trace.result or ""
        max_query, max_result = 2000, 6000
        query_display = query[:max_query] + (
            f"...[query truncated from {len(query)} chars]"
            if len(query) > max_query
            else ""
        )
        result_display = result[:max_result] + (
            f"...[result truncated from {len(result)} chars]"
            if len(result) > max_result
            else ""
        )
        return json.dumps(
            {
                "trace_id": trace.trace_id,
                "query": query_display,
                "agent": trace.agent,
                "model": trace.model,
                "outcome": trace.outcome,
                "feedback": getattr(trace, "feedback", None),
                "result": result_display,
                "total_tokens": trace.total_tokens,
                "total_latency_seconds": trace.total_latency_seconds,
                "steps": [str(s)[:200] for s in getattr(trace, "steps", [])[:20]],
            },
            default=str,
        )

    # ------------------------------------------------------------------
    # search_traces
    # ------------------------------------------------------------------
    def _search_traces(query: str, limit: int = 20) -> str:
        # Cap limit to avoid pathological calls that would OOM the context.
        # 20 x 95K-token traces = ~1.9M tokens, well over Opus's 1M window.
        limit = max(1, min(limit, 20))
        try:
            results = trace_store.search(query, limit=limit)
        except Exception as e:
            # SQLite FTS5 raises "unknown special query" for patterns with
            # unescaped special chars (- / . etc). Return a structured error
            # so the teacher can retry with a cleaner query instead of the
            # call being swallowed and context still growing.
            return json.dumps(
                {
                    "error": f"search_traces failed: {e}",
                    "hint": (
                        "FTS5 special chars (- / . : etc) need escaping. "
                        "Try a simpler keyword query."
                    ),
                }
            )
        # Truncate per-trace text fields. Each trace's `result` column can be
        # 50-95K tokens; returning raw content would blow the context window.
        max_query_per_trace = 300
        max_result_per_trace = 1500
        for r in results:
            q = r.get("query") or ""
            if len(q) > max_query_per_trace:
                r["query"] = q[:max_query_per_trace] + f"...[{len(q)} chars]"
            res = r.get("result") or ""
            if len(res) > max_result_per_trace:
                r["result"] = res[:max_result_per_trace] + f"...[{len(res)} chars]"
        return json.dumps(results, default=str)

    # ------------------------------------------------------------------
    # get_current_config
    # ------------------------------------------------------------------
    def _get_current_config() -> str:
        config_path = config["config_path"]
        try:
            return config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "No config.toml found."

    # ------------------------------------------------------------------
    # get_agent_prompt
    # ------------------------------------------------------------------
    def _get_agent_prompt(agent_name: str) -> str:
        prompt_path = openjarvis_home / "agents" / agent_name / "system_prompt.md"
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"No system prompt found for agent '{agent_name}'."

    # ------------------------------------------------------------------
    # get_tool_description
    # ------------------------------------------------------------------
    def _get_tool_description(tool_name: str) -> str:
        desc_path = openjarvis_home / "tools" / "descriptions.toml"
        try:
            content = desc_path.read_text(encoding="utf-8")
            # Simple TOML parsing for the description field
            in_section = False
            for line in content.splitlines():
                if line.strip() == f"[{tool_name}]":
                    in_section = True
                    continue
                if in_section and line.startswith("["):
                    break
                if in_section and "description" in line:
                    return line.split("=", 1)[1].strip().strip('"')
            return f"Tool '{tool_name}' found but no description field."
        except FileNotFoundError:
            return "No descriptions.toml found."

    # ------------------------------------------------------------------
    # list_available_tools
    # ------------------------------------------------------------------
    def _list_available_tools() -> str:
        # Read from the on-disk descriptions.toml
        desc_path = openjarvis_home / "tools" / "descriptions.toml"
        tools_list = []
        try:
            content = desc_path.read_text(encoding="utf-8")
            current_tool = None
            for line in content.splitlines():
                if line.startswith("[") and line.endswith("]"):
                    current_tool = line[1:-1]
                    tools_list.append(
                        {
                            "name": current_tool,
                            "description": "",
                            "category": "general",
                            "agents": [],
                        }
                    )
                elif current_tool and "description" in line and "=" in line:
                    desc = line.split("=", 1)[1].strip().strip('"')
                    if tools_list:
                        tools_list[-1]["description"] = desc
        except FileNotFoundError:
            pass
        return json.dumps(tools_list, default=str)

    # ------------------------------------------------------------------
    # list_personal_benchmark
    # ------------------------------------------------------------------
    def _list_personal_benchmark(limit: int = 50) -> str:
        tasks = []
        for sample in benchmark_samples[:limit]:
            tasks.append(
                {
                    "task_id": sample.trace_id,
                    "query": sample.query,
                    "reference_answer": sample.reference_answer[:500],
                    "category": getattr(sample, "category", "chat"),
                }
            )
        return json.dumps(tasks, default=str)

    # ------------------------------------------------------------------
    # run_student_on_task
    # ------------------------------------------------------------------
    def _run_student_on_task(task_id: str) -> str:
        sample = next((s for s in benchmark_samples if s.trace_id == task_id), None)
        if sample is None:
            return json.dumps({"error": f"Task {task_id} not found in benchmark"})
        result = student_runner(sample.query, session_id=session_id)
        return json.dumps(
            {
                "task_id": task_id,
                "output": str(getattr(result, "content", result)),
                "score": getattr(result, "score", 0.0),
                "trace_id": getattr(result, "trace_id", ""),
                "latency_seconds": getattr(result, "latency_seconds", 0.0),
                "tokens_used": getattr(result, "tokens_used", 0),
            },
            default=str,
        )

    # ------------------------------------------------------------------
    # run_self_on_task
    # ------------------------------------------------------------------
    def _run_self_on_task(task_id: str, max_tokens: int = 2048) -> str:
        sample = next((s for s in benchmark_samples if s.trace_id == task_id), None)
        if sample is None:
            return json.dumps({"error": f"Task {task_id} not found in benchmark"})
        response = teacher_engine.generate(
            messages=[{"role": "user", "content": sample.query}],
            model=teacher_model,
            max_tokens=max_tokens,
        )
        return json.dumps(
            {
                "task_id": task_id,
                "output": response.get("content", ""),
                "reasoning": "",
                "cost_usd": response.get("cost_usd", 0.0),
                "tokens_used": response.get("usage", {}).get("total_tokens", 0),
            },
            default=str,
        )

    # ------------------------------------------------------------------
    # compare_outputs
    # ------------------------------------------------------------------
    def _compare_outputs(student_output: str, teacher_output: str, task: str) -> str:
        score, reasoning = judge.score_trace(
            type(
                "FakeTrace",
                (),
                {
                    "query": task,
                    "result": student_output,
                    "steps": [],
                    "messages": [],
                    "agent": "student",
                    "model": "local",
                    "total_tokens": 0,
                    "total_latency_seconds": 0,
                    "metadata": {},
                },
            )()
        )
        teacher_score, _ = judge.score_trace(
            type(
                "FakeTrace",
                (),
                {
                    "query": task,
                    "result": teacher_output,
                    "steps": [],
                    "messages": [],
                    "agent": "teacher",
                    "model": "frontier",
                    "total_tokens": 0,
                    "total_latency_seconds": 0,
                    "metadata": {},
                },
            )()
        )
        return json.dumps(
            {
                "task_id": "",
                "student_score": score,
                "teacher_score": teacher_score,
                "judge_reasoning": reasoning,
            },
            default=str,
        )

    # ------------------------------------------------------------------
    # Assemble
    # ------------------------------------------------------------------
    return [
        DiagnosticTool(
            name="list_traces",
            description=(
                "Browse traces by agent, outcome, feedback range."
                " Returns a JSON list of trace summaries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 20,
                    },
                    "agent": {
                        "type": "string",
                        "description": "Filter by agent name",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Filter by outcome: success/failure",
                    },
                    "min_feedback": {
                        "type": "number",
                        "description": "Minimum feedback score",
                    },
                    "max_feedback": {
                        "type": "number",
                        "description": "Maximum feedback score",
                    },
                },
            },
            fn=_list_traces,
        ),
        DiagnosticTool(
            name="get_trace",
            description=(
                "Read a single trace including query, result, steps, and metrics."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "trace_id": {
                        "type": "string",
                        "description": "The trace ID to retrieve",
                    },
                },
                "required": ["trace_id"],
            },
            fn=_get_trace,
        ),
        DiagnosticTool(
            name="search_traces",
            description=(
                "Full-text search across traces. Returns matching trace summaries."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
            fn=_search_traces,
        ),
        DiagnosticTool(
            name="get_current_config",
            description="Read the current OpenJarvis config.toml.",
            parameters={"type": "object", "properties": {}},
            fn=_get_current_config,
        ),
        DiagnosticTool(
            name="get_agent_prompt",
            description="Read the current system prompt for a named agent.",
            parameters={
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Agent name (e.g. 'simple')",
                    },
                },
                "required": ["agent_name"],
            },
            fn=_get_agent_prompt,
        ),
        DiagnosticTool(
            name="get_tool_description",
            description="Read the LM-facing description of a tool.",
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Tool name (e.g. 'web_search')",
                    },
                },
                "required": ["tool_name"],
            },
            fn=_get_tool_description,
        ),
        DiagnosticTool(
            name="list_available_tools",
            description="List all tools and which agents currently have them enabled.",
            parameters={"type": "object", "properties": {}},
            fn=_list_available_tools,
        ),
        DiagnosticTool(
            name="list_personal_benchmark",
            description=(
                "Browse personal benchmark tasks with their reference answers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max tasks to return",
                        "default": 50,
                    },
                },
            },
            fn=_list_personal_benchmark,
        ),
        DiagnosticTool(
            name="run_student_on_task",
            description=(
                "Re-execute the local student agent on a benchmark task."
                " Returns the student's output and score."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Benchmark task ID",
                    },
                },
                "required": ["task_id"],
            },
            fn=_run_student_on_task,
        ),
        DiagnosticTool(
            name="run_self_on_task",
            description=(
                "Run yourself (the teacher) on a benchmark task"
                " to produce a reference answer."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Benchmark task ID",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Max tokens for response",
                        "default": 2048,
                    },
                },
                "required": ["task_id"],
            },
            fn=_run_self_on_task,
        ),
        DiagnosticTool(
            name="compare_outputs",
            description=(
                "Compare student and teacher outputs on a task using the TraceJudge."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "student_output": {
                        "type": "string",
                        "description": "The student's output",
                    },
                    "teacher_output": {
                        "type": "string",
                        "description": "The teacher's output",
                    },
                    "task": {
                        "type": "string",
                        "description": "The original task/query",
                    },
                },
                "required": ["student_output", "teacher_output", "task"],
            },
            fn=_compare_outputs,
        ),
    ]
