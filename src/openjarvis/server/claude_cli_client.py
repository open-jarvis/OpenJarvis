"""Client for the inspiring-cat Claude-CLI worker (submit-and-poll task API).

The worker exposes:
  POST /tasks              body {type: "claude_pro", payload: {prompt: str}} -> 201 {task_id, status}
  GET  /tasks/{task_id}    -> {id, type, status, result, error, ...}

`status` cycles through pending -> running -> done | failed.
Latency: 3-120s for Claude calls. No auth required at this writing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://inspiring-cat-production.up.railway.app"
DEFAULT_TASK_TYPE = "claude_pro"
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_POLL_INTERVAL_S = 1.5


@dataclass
class TaskResult:
    task_id: str
    status: str  # pending | running | done | failed
    result: Optional[str]
    error: Optional[str]


def _base_url() -> str:
    return os.environ.get("CLI_WORKER_URL", DEFAULT_BASE_URL).rstrip("/")


def _auth_headers() -> dict[str, str]:
    """Build auth headers for inspiring-cat /tasks calls.

    Priority order (first match wins):
      1. INSPIRING_CAT_WEBHOOK_SECRET — shared secret for the worker.
      2. CLAUDE_SESSION_TOKEN — Claude.ai session cookie/token.
    Public /tasks endpoints work without auth at writing time, so an empty
    header dict is acceptable.
    """
    secret = os.environ.get("INSPIRING_CAT_WEBHOOK_SECRET")
    if secret:
        return {
            "Authorization": f"Bearer {secret}",
            "X-Webhook-Secret": secret,
        }
    token = os.environ.get("CLAUDE_SESSION_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _build_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten an OpenAI-style messages list into a single prompt string.

    inspiring-cat expects a string `prompt` in the payload, not a messages
    array — so we render the conversation as plain text with role tags.
    """
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "") or ""
        if role == "system":
            parts.append(f"[SYSTEM]\n{content}")
        elif role == "assistant":
            parts.append(f"[ASSISTANT]\n{content}")
        else:
            parts.append(f"[USER]\n{content}")
    return "\n\n".join(parts)


async def submit(
    messages: list[dict[str, Any]],
    *,
    task_type: str = DEFAULT_TASK_TYPE,
    extra_payload: Optional[dict[str, Any]] = None,
) -> str:
    """Submit a Claude-CLI task; return the task_id immediately."""
    payload: dict[str, Any] = {"prompt": _build_prompt(messages)}
    if extra_payload:
        payload.update(extra_payload)
    body = {"type": task_type, "payload": payload}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_base_url()}/tasks",
            json=body,
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise RuntimeError(f"inspiring-cat returned no task_id: {data!r}")
        logger.info("Claude-CLI task submitted: %s", task_id)
        return task_id


async def poll(task_id: str) -> TaskResult:
    """Single GET against /tasks/{id}."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_base_url()}/tasks/{task_id}",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return TaskResult(
            task_id=data.get("id", task_id),
            status=data.get("status", "unknown"),
            result=data.get("result"),
            error=data.get("error"),
        )


async def await_completion(
    task_id: str,
    *,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> TaskResult:
    """Poll until status is done or failed, or until timeout_s elapses.

    Raises asyncio.TimeoutError on overall timeout. On failed status, returns
    the TaskResult so callers can inspect `error`.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        try:
            tr = await poll(task_id)
        except httpx.HTTPError as exc:
            logger.warning("Poll error for %s: %s", task_id, exc)
            tr = TaskResult(task_id=task_id, status="pending", result=None, error=None)

        if tr.status in ("done", "failed"):
            return tr

        if asyncio.get_event_loop().time() >= deadline:
            raise asyncio.TimeoutError(
                f"Claude-CLI task {task_id} did not complete within {timeout_s}s"
            )
        await asyncio.sleep(poll_interval_s)


async def is_healthy() -> bool:
    """Quick health probe; safe to call from startup. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_base_url()}/health")
            if resp.status_code != 200:
                return False
            data = resp.json()
            return bool(data.get("claude_available"))
    except Exception:
        return False


__all__ = [
    "TaskResult",
    "submit",
    "poll",
    "await_completion",
    "is_healthy",
]
