"""Tavily search + Modal Python sandbox helpers for ToolOrchestraAgent."""

from __future__ import annotations

import re
from typing import Optional, Tuple

# ---- Tavily + Modal helpers -------------------------------------------------


def _call_tavily_search(query: str, max_results: int = 5) -> Tuple[str, int, int]:
    """One-shot Tavily search. Returns (text, p_tok=0, c_tok=0).

    Token counts are reported as zero (no LLM was billed); the OpenJarvis
    accounting layer separately tallies tool-call counts. Falls back to
    DuckDuckGo if Tavily is unreachable (see ``WebSearchTool``).
    """
    from openjarvis.tools.web_search import WebSearchTool

    tool = WebSearchTool(max_results=max_results)
    res = tool.execute(query=query, max_results=max_results)
    text = res.content or ""
    if not res.success and not text:
        text = "(no results)"
    return text, 0, 0


_MODAL_APP_NAME = "openjarvis-toolorchestra-sandbox"


def _call_modal_python(code: str, timeout_s: int = 60) -> Tuple[str, int]:
    """Execute a single Python snippet in a fresh Modal Sandbox.

    Returns ``(combined_stdout_stderr, returncode)``. Logs are capped at 8 KiB.
    Any exception (modal auth, network, sandbox boot failure) is captured into
    the returned string with a non-zero rc — we never raise back to the
    orchestrator loop. The sandbox is torn down at the end via ``terminate()``.
    """
    try:
        import modal

        app = modal.App.lookup(_MODAL_APP_NAME, create_if_missing=True)
        # python:3.12-slim is small + boots fast; the paper uses a generic
        # Python image too. We rely on stdlib only — no extra pip installs.
        image = modal.Image.debian_slim(python_version="3.12")
        sb = modal.Sandbox.create(
            "python",
            "-c",
            code,
            app=app,
            image=image,
            timeout=int(timeout_s),
        )
        sb.wait()
        try:
            out = sb.stdout.read() or ""
        except Exception:
            out = ""
        try:
            err = sb.stderr.read() or ""
        except Exception:
            err = ""
        rc = sb.returncode if sb.returncode is not None else -1
        try:
            sb.terminate()
        except Exception:
            pass
        combined = out + (("\n" + err) if err else "")
        if len(combined) > 8192:
            combined = combined[:8192] + "\n... (output truncated)"
        return combined, int(rc)
    except Exception as exc:
        return f"[modal-python error: {type(exc).__name__}: {exc}]", -1


_PY_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def _extract_first_python_block(text: str) -> Optional[str]:
    """Return the first ```python ... ``` block (or ```...```), or None."""
    m = _PY_CODE_RE.search(text or "")
    return m.group(1).strip() if m else None
