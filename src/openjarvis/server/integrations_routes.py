"""GET /v1/integrations/status — per-integration health for the frontend.

Reports configuration + reachability for every integration registered
in :data:`openjarvis.core.env.ENV_REGISTRY`. The frontend uses this to
render an "Integrations" tab next to "Cloud Models" and to gate UI
affordances behind credentialed services.

This route does NOT call the underlying upstream APIs (which would be
slow + bill against the user). It only checks:
  * "configured": is the env var (or any alias) set?
  * "healthy": for services with a cheap reachability probe
    (Obsidian vault, n8n), perform a fast check; otherwise mirror
    "configured".

Probes are bounded by short per-integration timeouts so a slow service
doesn't stall the route.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter

from openjarvis.core.env import ENV_REGISTRY, EnvSpec, is_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])


def _entries_by_integration() -> dict[str, list[EnvSpec]]:
    out: dict[str, list[EnvSpec]] = {}
    for spec in ENV_REGISTRY.values():
        key = spec.integration or spec.name.lower()
        out.setdefault(key, []).append(spec)
    return out


def _probe(integration: str) -> tuple[Optional[bool], Optional[str]]:
    """Best-effort liveness probe. Returns (healthy, reason)."""
    if integration == "obsidian":
        try:
            from openjarvis.integrations.obsidian_vault import get_default_client

            ok = get_default_client().is_healthy()
            return ok, None if ok else "vault unreachable"
        except Exception as exc:  # pragma: no cover — defensive
            return False, f"probe error: {exc}"
    if integration == "n8n":
        try:
            from openjarvis.integrations.n8n import get_default_client

            client = get_default_client()
            if not client.configured:
                return False, "N8N_API_KEY or N8N_BASE_URL missing"
            client.list_workflows(limit=1)
            return True, None
        except Exception as exc:
            return False, f"probe error: {exc}"
    return None, None  # No probe — caller will mirror configured state.


@router.get("/status")
async def integrations_status() -> dict[str, Any]:
    """Return a per-integration status map.

    Shape::
        {
          "integrations": {
            "openai":     {"configured": true,  "healthy": true,  "vars": [...], "reason": ""},
            "obsidian":   {"configured": true,  "healthy": false, "vars": [...], "reason": "vault unreachable"},
            ...
          }
        }
    """
    grouped = _entries_by_integration()
    out: dict[str, Any] = {}

    for integration, specs in sorted(grouped.items()):
        # Configured = every required canonical env in this group is set
        # (with the env-alias pass already populating canonical names at
        # startup, this is just an os.environ presence check).
        var_states = []
        all_configured = True
        for spec in specs:
            ok = is_configured(spec.name)
            if not ok:
                all_configured = False
            var_states.append({
                "name": spec.name,
                "configured": ok,
                "secret": spec.secret,
                "purpose": spec.purpose,
                "aliases": list(spec.aliases),
            })

        healthy_probe, reason = _probe(integration)
        if healthy_probe is None:
            # No probe for this integration — health == configured.
            healthy = all_configured
            if not all_configured:
                missing = [v["name"] for v in var_states if not v["configured"]]
                reason = f"missing env: {', '.join(missing)}"
        else:
            healthy = bool(healthy_probe and all_configured)
            if not all_configured:
                missing = [v["name"] for v in var_states if not v["configured"]]
                reason = (reason + "; " if reason else "") + (
                    f"missing env: {', '.join(missing)}"
                )

        out[integration] = {
            "configured": all_configured,
            "healthy": healthy,
            "reason": reason or "",
            "vars": var_states,
        }

    return {"integrations": out}


__all__ = ["router"]
