"""Reports which cloud providers have API keys configured in the backend env.

Frontend uses this to auto-unlock the Cloud Models tab tiles for providers
already credentialed at the server side, so the user doesn't have to paste
placeholder strings into key boxes.

  GET /v1/cloud/providers
    -> {"providers": {"groq": {"available": true, ...}, ...}}
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from openjarvis.server import claude_cli_client


router = APIRouter(prefix="/v1/cloud", tags=["cloud-providers"])


def _truthy_enabled(env_name: str | None) -> bool:
    """Match the cloud_router/cloud.py rule: unset = enabled, set must be truthy."""
    if not env_name:
        return True
    val = os.environ.get(env_name)
    if val is None:
        return True
    return val.strip().lower() in ("true", "1", "yes", "on")


def _first_key_set(env_names: tuple[str, ...]) -> bool:
    return any(os.environ.get(n) for n in env_names)


# Provider id -> (key env vars in priority order, optional ENABLED flag).
# Ordered to match the UI's CLOUD_PROVIDERS array.
_PROVIDERS: dict[str, dict[str, Any]] = {
    "openjarvis-auto": {
        # Pseudo-provider; always available — backend cascades on its own.
        "always_available": True,
    },
    "openai": {
        "key_envs": ("OPENAI_API_KEY",),
        "enabled_env": None,
    },
    "anthropic": {
        "key_envs": ("ANTHROPIC_API_KEY",),
        "enabled_env": None,
    },
    "google": {
        "key_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "enabled_env": None,
    },
    "openrouter": {
        "key_envs": ("OPENROUTER_API_KEY",),
        "enabled_env": "OPENROUTER_ENABLED",
    },
    "groq": {
        "key_envs": ("GROQ_API_KEY",),
        "enabled_env": "GROQ_ENABLED",
    },
    "deepseek": {
        "key_envs": ("DEEPSEEK_API_KEY",),
        "enabled_env": "DEEPSEEK_ENABLED",
    },
    "cerebras": {
        "key_envs": ("CEREBRAS_API_KEY",),
        "enabled_env": "CEREBRAS_ENABLED",
    },
    "sambanova": {
        "key_envs": ("SAMBANOVA_API_KEY",),
        "enabled_env": "SAMBANOVA_ENABLED",
    },
    "kimi": {
        "key_envs": ("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        "enabled_env": "KIMI_ENABLED",
    },
    "glm": {
        # Bridge_Zbigmodel_api is the user's existing non-standard env name.
        "key_envs": ("GLM_API_KEY", "ZHIPUAI_API_KEY", "Bridge_Zbigmodel_api"),
        "enabled_env": "GLM_ENABLED",
    },
    "huggingface": {
        "key_envs": ("HF_API_KEY", "HUGGINGFACE_API_KEY", "HF_TOKEN"),
        "enabled_env": "HF_ENABLED",
    },
    "v0": {
        "key_envs": ("V0_API_KEY",),
        "enabled_env": "V0_ENABLED",
    },
    "github-models": {
        "key_envs": ("GITHUB_MODELS_TOKEN", "GITHUB_PAT", "GITHUB_TOKEN"),
        "enabled_env": "GITHUB_MODELS_ENABLED",
    },
}


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    """Return per-provider availability based on backend env configuration.

    `available=true` means: the backend has a usable key AND the provider's
    ENABLED flag (if any) is set to a truthy value (or unset).
    """
    out: dict[str, Any] = {}
    for pid, cfg in _PROVIDERS.items():
        if cfg.get("always_available"):
            out[pid] = {
                "available": True,
                "reason": "backend cascade — no key required",
            }
            continue
        key_envs = tuple(cfg.get("key_envs", ()))
        enabled = _truthy_enabled(cfg.get("enabled_env"))
        has_key = _first_key_set(key_envs)
        available = has_key and enabled
        reason = ""
        if not has_key:
            reason = f"no key in env (checked {', '.join(key_envs)})"
        elif not enabled:
            reason = f"{cfg.get('enabled_env')} is set to a non-truthy value"
        out[pid] = {"available": available, "reason": reason}

    # Bonus: include claude-cli health if the worker is reachable
    out["claude-cli"] = {
        "available": await claude_cli_client.is_healthy(),
        "reason": "inspiring-cat /health probe",
    }
    return {"providers": out}


__all__ = ["router"]
