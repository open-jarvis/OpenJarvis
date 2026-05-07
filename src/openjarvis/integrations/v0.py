"""V0 (vercel.com/v0) chat completions client.

V0 exposes an OpenAI-compatible Chat Completions endpoint at
``https://api.v0.dev/v1`` (already wired into ``CloudEngine``'s
``_OPENAI_COMPAT_PROVIDERS`` for inference). This module wraps the same
endpoint as a *tool* so models can ask V0 to design / generate UI
components and capture the response (which typically includes a
deployable artifact URL).

Auth: ``V0_API_KEY``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class V0UnavailableError(RuntimeError):
    """Raised when V0_API_KEY is missing or a call fails."""


class V0Client:
    BASE_URL = "https://api.v0.dev/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        timeout: float = 120.0,
    ) -> None:
        self._key = api_key or os.environ.get("V0_API_KEY", "")
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def chat_create(
        self,
        prompt: str,
        *,
        model: str = "v0-1.5-md",
        system: Optional[str] = None,
    ) -> Any:
        """Send a single-turn prompt to V0; return the parsed response.

        V0's response typically embeds a Vercel preview/deploy URL in
        the assistant content; callers extract it as needed.
        """
        if not self.configured:
            raise V0UnavailableError("V0 not configured — set V0_API_KEY")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages}
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout) as c:
                resp = c.post(
                    f"{self.BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPError as exc:
            raise V0UnavailableError(f"V0 chat request failed: {exc}") from exc


_default: Optional[V0Client] = None


def get_default_client() -> V0Client:
    global _default
    if _default is None:
        _default = V0Client()
    return _default


__all__ = ["V0Client", "V0UnavailableError", "get_default_client"]
