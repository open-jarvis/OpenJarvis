"""Process-wide retry + concurrency hardening for cloud OpenAI calls.

Why this exists
---------------

When we run the hybrid paradigms (Minions, Advisors, Conductor, …) at
n=100 against ``gpt-5`` / ``gpt-5-mini`` over the prepaid OpenAI quota,
sustained concurrency walls the org-level rate limit and the OpenAI SDK
raises :class:`openai.RateLimitError`. The SDK's own retry path is short
(default ``max_retries=2`` on a small backoff) — under sustained pressure
every wave of retries hits the same wall and the runner records 19-69
errored rows per cell, degenerating the result.

Mirrors the existing ``_patch_anthropic_globally`` pattern in
``minions.py``: monkey-patch the SDK at module level so it applies even
to libraries that build their own ``openai.OpenAI()`` clients
(HazyResearch Minions's ``OpenAIClient``, Archon's adapters,
``mini_swe_agent``, etc.). One call to :func:`patch_openai_globally` from
either ``_base.py`` or ``minions._apply_patches_once`` is enough — the
patch is idempotent and process-wide.

What it does
------------

1. Bumps ``openai.OpenAI()`` constructor defaults to
   ``timeout=600.0`` / ``max_retries=8`` (the SDK's own backoff is fine
   for transient blips; we layer our own loop on top for sustained walls).
2. Wraps ``chat.completions.create`` with:

   - A **per-org semaphore** (``OPENJARVIS_OPENAI_MAX_CONCURRENCY``,
     default 4) that throttles sustained concurrency. Single bursts are
     fine — prepaid quotas wall on sustained rate, not on a brief spike.
     The semaphore is **only acquired for cloud calls** (``api.openai.com``);
     vLLM calls routed through the OpenAI SDK (``base_url`` set to a
     local endpoint or ``api_key="EMPTY"``) bypass it.
   - Exponential backoff with jitter on :class:`openai.RateLimitError`,
     :class:`openai.APITimeoutError`, :class:`openai.APIConnectionError`,
     and 5xx :class:`openai.APIStatusError`. Starts at 2 s, caps at 60 s,
     up to 8 attempts (~3.5 min worst case). Honors a ``Retry-After``
     header when the SDK surfaces one.
   - On exhaustion, re-raises the last exception (it bubbles up to the
     runner, which records ``error="RateLimitError: ..."`` in
     ``results.jsonl`` — no silent drop).

Env knobs
---------

- ``OPENJARVIS_OPENAI_MAX_CONCURRENCY`` (default ``4``) — semaphore
  capacity. Set to e.g. ``2`` if the wall is still hit; set to ``0`` to
  disable throttling entirely (passes through to the SDK).
- ``OPENJARVIS_OPENAI_MAX_RETRIES`` (default ``8``) — outer retry loop
  cap (separate from the SDK's own ``max_retries``).
- ``OPENJARVIS_OPENAI_RETRY_BASE`` (default ``2.0``) — base seconds for
  exponential backoff. Schedule is ``min(60, base * 2**attempt) * jitter``.
- ``OPENJARVIS_OPENAI_RETRY_CAP`` (default ``60.0``) — max single-step
  sleep in seconds.
"""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Any, Callable, Optional, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Tunables (read once at module load, can be overridden via env)
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "") or default)
        return max(0, v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


_MAX_CONCURRENCY = _env_int("OPENJARVIS_OPENAI_MAX_CONCURRENCY", 4)
_MAX_RETRIES = _env_int("OPENJARVIS_OPENAI_MAX_RETRIES", 8)
_RETRY_BASE = _env_float("OPENJARVIS_OPENAI_RETRY_BASE", 2.0)
_RETRY_CAP = _env_float("OPENJARVIS_OPENAI_RETRY_CAP", 60.0)


# Single process-wide semaphore. ``BoundedSemaphore(0)`` would block
# forever, so when the env knob is 0 we hand back a no-op context manager.
class _NullSem:
    def __enter__(self) -> "_NullSem":
        return self

    def __exit__(self, *a: Any) -> None:
        return None


_SEM: Any
if _MAX_CONCURRENCY > 0:
    _SEM = threading.BoundedSemaphore(_MAX_CONCURRENCY)
else:
    _SEM = _NullSem()


_PATCHED = False
_PATCH_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_local_endpoint(client: Any) -> bool:
    """True if this OpenAI client points at a local vLLM endpoint.

    We detect via either ``api_key == "EMPTY"`` (the convention used by
    our ``_call_vllm`` and ``mini_swe_agent``) or a ``base_url`` whose
    hostname resolves to localhost. Either signal is enough; both are
    cheap to read.
    """
    try:
        api_key = getattr(client, "api_key", None)
        if api_key == "EMPTY":
            return True
    except Exception:
        pass
    try:
        base_url = str(getattr(client, "base_url", "") or "")
        if not base_url:
            return False
        host = urlparse(base_url).hostname or ""
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    except Exception:
        return False


def _extract_retry_after(exc: BaseException) -> Optional[float]:
    """Pull a Retry-After header off an APIStatusError if the SDK exposed it.

    OpenAI's SDK keeps the underlying ``httpx.Response`` on
    ``exc.response`` for ``APIStatusError`` subclasses. Header may be a
    seconds-integer or an HTTP-date; we only handle the integer form
    (the only thing OpenAI sends in practice).
    """
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    for name in ("retry-after", "Retry-After", "x-ratelimit-reset-requests"):
        val = headers.get(name) if hasattr(headers, "get") else None
        if val is None:
            continue
        try:
            secs = float(val)
            if 0 <= secs <= 600:
                return secs
        except (TypeError, ValueError):
            continue
    return None


def _is_retryable(exc: BaseException) -> bool:
    """Whether to retry this OpenAI exception class."""
    try:
        import openai
    except ImportError:
        return False
    if isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        ),
    ):
        return True
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", None)
        # 429 is RateLimitError already; 5xx is retryable; 408 is a
        # timeout the SDK didn't classify (rare).
        return status is not None and (status >= 500 or status in (408, 409, 429))
    return False


def _sleep_for(attempt: int, exc: BaseException) -> float:
    """Backoff for attempt index ``attempt`` (0-based)."""
    hinted = _extract_retry_after(exc)
    if hinted is not None and hinted > 0:
        # Respect a server-provided hint, but clamp to our cap so a
        # pathological header can't stall the run for hours.
        return min(_RETRY_CAP, hinted) + random.uniform(0, 0.5)
    base = min(_RETRY_CAP, _RETRY_BASE * (2**attempt))
    # Full jitter — better tail behavior than equal jitter when many
    # workers wake at the same moment.
    return random.uniform(0.0, base)


# ---------------------------------------------------------------------------
# Wrapping
# ---------------------------------------------------------------------------


def _wrap_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a ``chat.completions.create`` (or ``responses.create``) bound
    method's underlying function with retry + concurrency throttling.

    The wrapper is a regular function that takes ``self`` as the first
    arg, so it can replace ``Completions.create`` at the class level and
    still see the bound client through ``self._client``.
    """

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        client = getattr(self, "_client", None)
        local = client is not None and _is_local_endpoint(client)
        # Local vLLM calls bypass the per-org throttle (no rate limit) and
        # the long retry loop (vLLM is mostly either up or down — a 60s
        # backoff just delays surfacing the failure). But brief
        # ConnectionError blips do happen mid-sweep (socket queue, brief
        # server warmup pause): give the local path a SHORT retry — 3
        # attempts, 1s/2s/4s — so we don't error an entire row on a
        # transient refused connection. Anything else (BadRequest etc.)
        # still raises immediately.
        if local:
            local_last_exc: Optional[BaseException] = None
            for attempt in range(3):
                try:
                    return orig(self, *args, **kwargs)
                except BaseException as exc:  # noqa: BLE001
                    try:
                        import openai
                    except ImportError:
                        raise
                    if not isinstance(
                        exc,
                        (
                            openai.APIConnectionError,
                            openai.APITimeoutError,
                            openai.InternalServerError,
                        ),
                    ):
                        raise
                    local_last_exc = exc
                    if attempt >= 2:
                        break
                    time.sleep(2**attempt)
            assert local_last_exc is not None
            raise local_last_exc

        last_exc: Optional[BaseException] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                with _SEM:
                    return orig(self, *args, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                if attempt >= _MAX_RETRIES:
                    break
                delay = _sleep_for(attempt, exc)
                # Stderr, not stdout: heartbeat / progress lines must
                # stay parseable in the runner log.
                try:
                    import sys

                    print(
                        f"[openai-retry] attempt {attempt + 1}/{_MAX_RETRIES} "
                        f"{type(exc).__name__}: {str(exc)[:120]} — "
                        f"sleeping {delay:.1f}s",
                        file=sys.stderr,
                        flush=True,
                    )
                except Exception:
                    pass
                time.sleep(delay)
        # Exhausted. Re-raise so the runner records the row as errored.
        assert last_exc is not None
        raise last_exc

    wrapped._hybrid_patched = True  # type: ignore[attr-defined]
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def patch_openai_globally() -> None:
    """Idempotently monkey-patch the OpenAI SDK to add retry + throttling.

    Safe to call from multiple modules — guarded by ``_PATCHED`` under a
    lock. Patches both the ``Completions.create`` method and the
    ``OpenAI.__init__`` defaults.
    """
    global _PATCHED
    if _PATCHED:
        return
    with _PATCH_LOCK:
        if _PATCHED:
            return
        try:
            import openai
            from openai.resources.chat import completions as _comp_mod
        except ImportError:
            return

        # Bump constructor defaults so callers that don't pass timeout /
        # max_retries explicitly still get sensible values. ``setdefault``
        # so any explicit caller value wins.
        if not getattr(openai.OpenAI.__init__, "_hybrid_patched", False):
            _orig_init = openai.OpenAI.__init__

            def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
                kwargs.setdefault("timeout", 600.0)
                kwargs.setdefault("max_retries", _MAX_RETRIES)
                return _orig_init(self, *args, **kwargs)

            _patched_init._hybrid_patched = True  # type: ignore[attr-defined]
            openai.OpenAI.__init__ = _patched_init  # type: ignore[assignment]

        # Wrap chat.completions.create. The SDK exposes the bound method
        # via ``Completions.create``; we replace the class attribute so
        # every instance (including ones built inside external libs)
        # sees the wrapped version.
        if not getattr(_comp_mod.Completions.create, "_hybrid_patched", False):
            _comp_mod.Completions.create = _wrap_create(  # type: ignore[assignment]
                _comp_mod.Completions.create
            )

        # Also patch the async variant for completeness (none of our
        # paradigms use it today, but Archon / future paradigms might).
        try:
            from openai.resources.chat import completions as _comp_mod_async

            cls = getattr(_comp_mod_async, "AsyncCompletions", None)
            if cls is not None and not getattr(cls.create, "_hybrid_patched", False):
                # Async wrapper is structurally different — only patch
                # the bumped defaults via __init__; full retry loop on
                # async would need an async wrapper. Leave that for the
                # day a paradigm actually uses it.
                pass
        except ImportError:
            pass

        _PATCHED = True


def current_settings() -> Tuple[int, int, float, float]:
    """For tests / smoke runs: return (concurrency, retries, base, cap)."""
    return _MAX_CONCURRENCY, _MAX_RETRIES, _RETRY_BASE, _RETRY_CAP


__all__ = ["patch_openai_globally", "current_settings"]
