"""Shared helper for targeting an explicit OpenAI-compatible endpoint.

Used by the first-party eval backends (jarvis-direct, jarvis-agent) when
``--base-url`` is given: the eval must use exactly that endpoint, with no
silent fallback to whatever other engine discovery happens to find.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_endpoint_engine(
    base_url: str,
    api_key: Optional[str] = None,
    engine_key: Optional[str] = None,
):
    """Construct an :class:`OpenAICompatEngine` pinned to ``base_url``.

    Pre-flight health-checks the endpoint and raises a loud, actionable
    error when it is unreachable — engine discovery is never consulted.
    """
    from openjarvis.engine.openai_compat_engines import (
        OpenAICompatEngine,
        normalize_openai_base_url,
    )

    if engine_key:
        logger.warning(
            "Both an engine key (%r) and base_url (%r) were given; "
            "base_url wins — targeting the endpoint directly.",
            engine_key,
            base_url,
        )
    host = normalize_openai_base_url(base_url)
    engine = OpenAICompatEngine(host=host, api_key=api_key)
    if not engine.health():
        engine.close()
        raise RuntimeError(
            f"--base-url endpoint not reachable: {base_url} "
            f"(GET {host}/v1/models failed). Is an OpenAI-compatible server "
            "(e.g. `vllm serve`) running at that address? If it requires "
            "authentication (HTTP 401), pass --api-key or set "
            "JARVIS_BACKEND_API_KEY."
        )
    return engine


__all__ = ["build_endpoint_engine"]
